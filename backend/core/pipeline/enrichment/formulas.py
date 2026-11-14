"""Formula enrichment: the LaTeX of formulas the extractor left without it.

Before planning, ``_classify_formula_regions`` asks the vision model whether
each formula crop without LaTeX holds mathematics, a drawing or nothing it can
tell, and reclassifies or escalates it. ``_enrich_formula_latex`` then reads
the LaTeX of the mathematical ones: ``math.recognize`` first (through the SDK's
formula steps, ADR-0017), each candidate gated by its agreement with the text
layer, then the vision model as the fallback. The crop never falls back to the
whole page, and an outage of ``math.recognize`` is paid once per document.
Moved verbatim from the PDDL orchestrator once ADR-0017 was accepted (#402,
phase 3, step 6).

Like every module of ``backend/core`` that asks an agent (the vision or the
data agent), this one imports ``backend.agents``. The dependency is transient:
step 2 of ADR-0016's roadmap gathers the agents into the core before its
boundary test (step 5) refuses imports of ``backend`` from outside the core.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from acessilia_sdk.toolbox.clients.pdf import RENDER_MEDIA_TYPES
from docstruct.text.equations import preserve_equation_number, split_equation_number
from docstruct.text.latex import has_latex_markup, latex_text_agreement

from backend.agents.output_schemas import VisionOutput
from backend.agents.provider_breaker import ProviderBreaker
from backend.agents.vision_agent import VisionAgent
from backend.core.manifest.builder import (
    TYPE_BOUND_V23_KINDS,
    reconcile_reclassified_element_processing_needs,
    separate_equation_number,
)
from backend.core.manifest.models import (
    ManifestElement,
    ProcessingManifest,
)
from backend.core.pipeline.obligations import (
    _pages_label,
)
from backend.core.pipeline.toolbox import (
    _source_artifact_id,
    _toolbox_formula_crop,
)
from backend.core.i18n import t
from backend.core.i18n.log_messages import (
    LOG_PDDL_FORMULA_RECOGNIZE_EMPTY,
    LOG_PDDL_FORMULA_RECOGNIZE_UNAVAILABLE,
    LOG_PDDL_FORMULA_TEXT_LAYER_DISAGREES,
    LOG_PDDL_FORMULAS_FELL_BACK_TO_VISION,
    LOG_PDDL_FORMULAS_RECOGNIZED,
)
from backend.services.blocking import run_blocking
from backend.core.i18n.stage_messages import (
    STAGE_ENRICHING_FORMULAS,
    STAGE_RECOGNIZING_FORMULA,
)
from backend.tools.formula_tools import normalize_latex
from backend.tools.logger import logger
from backend.tools.toolbox_math_tools import (
    MathCapabilityUnavailable,
    toolbox_recognize_formula,
)


def _formula_recognition_crop(
    source_file: Path,
    element: ManifestElement,
    *,
    artifact_id: str | None = None,
    media_type: str | None = None,
) -> tuple[bytes | None, int]:
    """Crop to feed the formula recognizer, or ``None`` when there is no usable box.

    A whole page is deliberately not a fallback: the chip models expect a
    formula and would invent one from a page of prose. A saved
    ``region_crop`` is reused when present, so a restored or resumed manifest
    does not pay another render; in the normal flow region inspection runs
    after planning, so a formula reaches this function without one (unless
    its text normalizes to empty). Everything else is the SDK's
    ``crop_formula_region`` on the element's provenance box (ADR-0017).
    """
    provenance = element.provenance[0] if element.provenance else None
    page_number = (
        provenance.page_number if provenance is not None else (element.page_number or 0)
    )

    saved = element.metadata.get("region_crop")
    if isinstance(saved, str) and saved:
        try:
            return Path(saved).read_bytes(), page_number
        except OSError:
            logger.warning("Formula crop unreadable for {}: {}", element.id, saved)

    if page_number < 1:
        return None, 0
    try:
        crop = _toolbox_formula_crop(
            source_file,
            page_number,
            provenance.bbox if provenance is not None else None,
            media_type=media_type,
            artifact_id=artifact_id,
        )
    except Exception as exc:
        # A DOCX has no page to render, and the Toolbox may refuse the box;
        # both leave the formula without a crop instead of failing the job.
        logger.warning(
            "Formula crop failed for {} ({}): {}", element.id, type(exc).__name__, exc
        )
        return None, page_number
    return crop.image, page_number


def _reclassify_formula_picture(
    manifest: ProcessingManifest,
    element: ManifestElement,
    output: VisionOutput,
    image: bytes,
    *,
    source: str,
) -> None:
    """Keep the source evidence and reuse a non-mathematical description.

    The crop the model read becomes the picture (``metadata.src``), as for a
    region inspection, so the export shows the drawing it describes.
    ``source`` records which call reclassified it: the candidate inspection
    or the vision fallback of the formula recognition.
    """
    element.metadata["original_type"] = element.type
    element.metadata["original_text"] = element.text
    element.metadata["original_raw_label"] = element.raw_label
    element.type = "picture"
    element.raw_label = "picture"
    element.text = output.description
    element.metadata["vision_description_complete"] = True
    element.metadata["vision_language"] = output.language
    element.metadata["vision_confidence"] = output.confidence
    element.metadata["vision_elements"] = list(output.mentioned_elements)
    element.metadata["vision_warnings"] = list(output.warnings)
    element.metadata["src"] = "data:image/png;base64," + base64.b64encode(image).decode("ascii")
    element.metadata["formula_classification"] = {
        "status": "picture",
        "reason": source,
        "confidence": output.confidence,
        "warnings": list(output.warnings),
    }
    reconcile_reclassified_element_processing_needs(manifest, element, previous_type="formula")


def _escalate_unresolved_formula(
    manifest: ProcessingManifest, element: ManifestElement
) -> None:
    """Hand a region the model could not classify to a person, not to the math path.

    Its ``verbalize-formula`` goes to ``human-review``; ``normalize-formula``
    is dropped, since normalizing LaTeX the model could not tell is a formula
    would treat it as one.
    """
    retained = []
    for obligation in manifest.obligations:
        if obligation.target_ids == [element.id]:
            if obligation.kind in TYPE_BOUND_V23_KINDS["formula"]:
                continue
            if obligation.kind == "verbalize-formula":
                obligation.admissible_methods = ["human-review"]
                obligation.method_costs = {"human-review": 100}
        retained.append(obligation)
    manifest.obligations = retained
    manifest.summary.obligation_count = len(manifest.obligations)


async def _classify_formula_regions(
    manifest: ProcessingManifest,
    source_file: Path,
    *,
    mode: str,
    breaker: ProviderBreaker,
) -> None:
    """Check extractor formula labels before a mathematical recognizer sees them.

    A drawing is described once and reconciled as a picture before planning.
    A candidate the model explicitly cannot classify (``classification_uncertain``)
    keeps its source content and goes to human review. A call that gives no
    answer (open breaker, no crop, model failure, empty description) is no
    evidence against mathematics: the candidate stays ``unclassified`` and
    takes the formula path it took before this check, whose vision fallback
    can still reclassify it.
    """
    from backend.config.settings import settings

    if manifest.source.media_type not in RENDER_MEDIA_TYPES:
        return
    candidates = [
        element for element in manifest.elements
        if element.type == "formula"
        and not has_latex_markup(element.text)
        and not element.metadata.get("latex_markup")
    ]
    if not candidates:
        return
    slots = asyncio.Semaphore(max(1, settings.vision_concurrency))
    vision = VisionAgent(mode=mode)

    async def classify(element: ManifestElement) -> None:
        async with slots:
            output = None
            errors: list[str] = []
            reason = "provider_blocked"
            if not breaker.open:
                reason = "crop_unavailable"
                image, page = await run_blocking(
                    _formula_recognition_crop, source_file, element,
                    artifact_id=_source_artifact_id(manifest),
                    media_type=manifest.source.media_type,
                )
                if image:
                    reason = "model_failed"
                    output = await vision.describe_region(
                        image_bytes=image, classification="formula_candidate",
                        page_num=page, total_pages=len(manifest.pages), mode=mode,
                        full_budget=True, errors=errors,
                    )
                    breaker.record(isinstance(output, VisionOutput))
            status = "unclassified"
            if isinstance(output, VisionOutput):
                if output.classification_uncertain:
                    status, reason = "unresolved", "classification_uncertain"
                elif output.kind == "formula":
                    status, reason = "math", None
                elif output.description.strip():
                    _reclassify_formula_picture(
                        manifest, element, output, image, source="candidate_inspection"
                    )
                    return
                else:
                    reason = "empty_description"
            element.metadata["formula_classification"] = {
                "status": status,
                "reason": reason,
                "confidence": output.confidence if output is not None else None,
                "warnings": list(output.warnings) if output is not None else errors,
            }
            if status == "unresolved":
                _escalate_unresolved_formula(manifest, element)

    async with asyncio.TaskGroup() as group:
        for element in candidates:
            group.create_task(classify(element))


async def _enrich_formula_latex(
    manifest: ProcessingManifest,
    source_file: Path,
    *,
    mode: str,
    status_callback: Callable[[str], Coroutine[Any, Any, None]] | None = None,
    breaker: ProviderBreaker | None = None,
) -> None:
    """Give LaTeX to formulas the extractor delivered without it.

    That covers formulas with no text and, in born-digital PDFs, formulas
    whose text is the PDF text layer (``s(t) = s0 + v0t + 1 2 at2``): it
    keeps the symbols but not the fractions, exponents and limits, so MathML
    and speech built from it lose the structure. ``has_latex_markup`` tells
    the two apart.

    ``math.recognize`` (PP-FormulaNet) runs first; the vision model is the
    fallback, so a Toolbox outage degrades to the behavior the pipeline had
    before instead of leaving the formula without content. Recognition runs
    before planning, like the picture descriptions, so the ``mathml`` and
    ``latex-verbalizer`` methods then work on real LaTeX.

    When the formula has text-layer text, a recognition must agree with it
    (``latex_text_agreement`` ≥ ``FORMULA_TEXT_AGREEMENT_MIN``): PP-FormulaNet
    reports no confidence, and the text layer is the only independent reading
    of the same formula. A recognition below it is a misread; the next one is
    tried, and when none agrees the formula keeps its text-layer version, which
    is flat but faithful. The text layer is the reference, not the truth: a
    garbled one can refuse a correct reading, which ``formula_text_layer`` and
    ``rejected`` leave on record.

    During a ``math.recognize`` outage, text-layer formulas also go to the
    vision model, so an outage now costs one vision call per formula that has
    text, not only per empty one. That is deliberate: on the reference case the
    vision readings took the structure of 16 flat formulas from nothing to a
    98.4 structure-token recall. When vision disagrees with the text layer too,
    the call bought nothing and the formula stays flat.

    A provider can also answer without LaTeX, which is not an outage: a
    page-level one such as ``docling-math`` finds no formula in a chip, so
    every formula goes to vision. Each such fallback is logged at DEBUG, and
    one INFO line per document counts them and names the provider, so the
    misconfiguration reads in one line instead of one per formula.

    The vision fallback shares the job's provider breaker with the picture
    and table stages: a provider those stages declared down gets no call
    from here and each formula degrades to its text-layer text at once.

    Each recognized formula records ``metadata["formula_recognition"]``:
    ``method`` (the capability that gave the LaTeX: ``math.recognize`` or
    ``vision``; ``text-layer`` when nothing agreed), ``confidence``,
    ``text_agreement`` when there was text-layer text, ``rank`` when a
    ``math.recognize`` candidate other than the best-ranked one was used, and
    ``rejected``: refused readings keyed by method, with ``#n`` for the n-th
    ranked candidate (``math.recognize#2``), valued by their agreement
    (``None`` for no evidence). Consumers must read those keys as
    ``method`` or ``method#rank`` strings.

    Crops are independent, so they run concurrently, bounded by
    ``VISION_CONCURRENCY`` for the same reason as the picture descriptions:
    the vision fallback shares that provider budget. An outage is still paid
    once per document: the first ``MathCapabilityUnavailable`` sets a flag the
    remaining formulas read before calling recognition, and the probe itself
    is serialized so concurrent crops cannot each pay the same timeout.

    Two formulas on the same page still pay two renders: the Toolbox applies
    the clip, and caching a whole page to crop it locally would move pixel
    work into the core (ADR-0003), so page-level render reuse stays a
    follow-up.
    """
    from acessilia_sdk.toolbox.capabilities import provider_default

    from backend.config.settings import settings

    for element in manifest.elements:
        separate_equation_number(element)
    formulas = [
        element
        for element in manifest.elements
        if element.type == "formula"
        and not has_latex_markup(element.text)
        and not element.metadata.get("latex_markup")
        and element.metadata.get("formula_classification", {}).get("status") != "unresolved"
    ]
    if not formulas:
        return
    # Without a page to render there is no crop to recognize. DOCX/PPTX
    # formulas stay as the extractor delivered them instead of paying one
    # failed render per formula.
    if manifest.source.media_type not in RENDER_MEDIA_TYPES:
        return

    if status_callback:
        await status_callback(t(STAGE_ENRICHING_FORMULAS))

    # Resolved like ``ToolboxCapabilityClient``: an empty setting means the
    # registry default, which is the provider the request actually asked.
    recognize_provider = settings.toolbox_math_recognize_provider or provider_default(
        "toolbox_math_recognize_provider"
    )
    enrichment = _FormulaEnrichment(
        manifest=manifest,
        source_file=source_file,
        mode=mode,
        status_callback=status_callback,
        vision=VisionAgent(mode=mode),
        breaker=breaker or ProviderBreaker(settings.vision_breaker_threshold),
        slots=asyncio.Semaphore(max(1, settings.vision_concurrency)),
        total=len(formulas),
        recognize_provider=recognize_provider,
    )

    # The fold touches only its own element and runs without awaits, so
    # concurrent folds cannot interleave. The TaskGroup cancels the sibling
    # crops when one of them fails and re-raises as an ExceptionGroup, like the
    # picture descriptions; no task keeps mutating the manifest after it failed.
    async with asyncio.TaskGroup() as group:
        tasks = [
            group.create_task(enrichment.enrich_one(position, element))
            for position, element in enumerate(formulas, start=1)
        ]
    recognized = sum(task.result() for task in tasks)

    if recognized:
        logger.info(t(LOG_PDDL_FORMULAS_RECOGNIZED).format(count=recognized))
    if enrichment.empty_answers:
        logger.info(
            t(LOG_PDDL_FORMULAS_FELL_BACK_TO_VISION).format(
                count=enrichment.empty_answers, total=len(formulas), provider=recognize_provider,
            )
        )


class _FormulaEnrichment:
    """The state ``_enrich_formula_latex`` shares across one document's formulas."""

    def __init__(
        self,
        *,
        manifest: ProcessingManifest,
        source_file: Path,
        mode: str,
        status_callback: Callable[[str], Coroutine[Any, Any, None]] | None,
        vision: VisionAgent,
        breaker: ProviderBreaker,
        slots: asyncio.Semaphore,
        total: int,
        recognize_provider: str,
    ) -> None:
        self.manifest = manifest
        self.source_file = source_file
        self.mode = mode
        self.status_callback = status_callback
        self.vision = vision
        self.breaker = breaker
        self.slots = slots
        self.total = total
        self.recognize_provider = recognize_provider
        self.total_pages = len(manifest.pages)
        self.artifact_id = _source_artifact_id(manifest)
        self.progress_lock = asyncio.Lock()
        self.recognizer = _MathRecognizer()
        #: Crops ``math.recognize`` answered without LaTeX, outside an outage.
        self.empty_answers = 0

    async def enrich_one(self, position: int, element: ManifestElement) -> bool:
        """Recognize one formula and fold the answer into it; True when filled."""
        async with self.slots:
            if self.status_callback:
                async with self.progress_lock:
                    await self.status_callback(
                        t(STAGE_RECOGNIZING_FORMULA).format(
                            current=position,
                            total=self.total,
                            pages=_pages_label([element.page_number], self.total_pages),
                        )
                    )
            image_bytes, page_number = await run_blocking(
                _formula_recognition_crop,
                self.source_file,
                element,
                artifact_id=self.artifact_id,
                media_type=self.manifest.source.media_type,
            )
            if not image_bytes:
                return False

            original_text = element.text or ""
            gate = _TextLayerGate(normalize_latex(original_text))

            method = "math.recognize"
            candidates = await self.recognizer.recognize(image_bytes)
            if not candidates and self.recognizer.available:
                # An outage already warned once and skips this. An empty list
                # is usually an answer without LaTeX, which nothing else
                # records; a rejected crop or a transport error reaches it too,
                # but those were logged by ``toolbox_recognize_formula``. No
                # await separates ``recognize`` from this check, so the flag
                # and the counter cannot race with sibling crops.
                self.empty_answers += 1
                logger.debug(
                    t(LOG_PDDL_FORMULA_RECOGNIZE_EMPTY).format(
                        element_id=element.id, page=page_number, provider=self.recognize_provider,
                    )
                )
            latex, confidence, accepted_rank = _first_agreeing_candidate(candidates, gate, method)

            if not latex:
                method = "vision"
                output = await _formula_by_vision(
                    self.vision, self.breaker, image_bytes, page_number, self.total_pages, self.mode
                )
                if (
                    output is not None and output.kind == "description"
                    and output.description.strip() and not output.classification_uncertain
                ):
                    # A non-mathematical description corrects the label.
                    _reclassify_formula_picture(
                        self.manifest, element, output, image_bytes, source="recognition_fallback"
                    )
                    return False
                if output is not None and output.kind == "formula":
                    latex = gate.accept(method, normalize_latex(output.formula_latex or ""))
                    confidence = output.confidence

        return _record_formula_recognition(
            element,
            latex=latex,
            method=method,
            confidence=confidence,
            rank=accepted_rank,
            original_text=original_text,
            gate=gate,
            page_number=page_number,
        )


class _MathRecognizer:
    """``math.recognize`` for one document, whose outage is paid once.

    The first call is serialized and every other crop waits for its answer,
    so a batch that starts with the capability down pays the outage once
    instead of once per crop; after it succeeds, the remaining calls only read
    the flag and run concurrently. The first ``MathCapabilityUnavailable``
    turns ``available`` off for the rest of the document.
    """

    def __init__(self) -> None:
        self.available = True
        self._probe = asyncio.Lock()
        self._ready = asyncio.Event()

    async def _call(self, image_bytes: bytes) -> list[dict[str, Any]]:
        """One recognition call; an outage turns the flag off and means no LaTeX."""
        try:
            return await run_blocking(
                toolbox_recognize_formula,
                image_bytes,
                raise_on_unavailable=True,
            )
        except MathCapabilityUnavailable as exc:
            self.available = False
            # The full message names the provider and its HTTP status; the
            # class alone ("ToolboxError") hides a failing sidecar.
            logger.warning(t(LOG_PDDL_FORMULA_RECOGNIZE_UNAVAILABLE).format(error=exc))
            return []

    async def recognize(self, image_bytes: bytes) -> list[dict[str, Any]]:
        """One crop's LaTeX candidates, best first, unless the document found the outage."""
        if not self._ready.is_set():
            async with self._probe:
                if not self._ready.is_set():
                    try:
                        return await self._call(image_bytes)
                    finally:
                        self._ready.set()
        if not self.available:
            return []
        return await self._call(image_bytes)


class _TextLayerGate:
    """Whether a recognition agrees with a formula's text layer, and what was refused.

    ``rejected`` maps each refused method (``math.recognize#2``) to its
    agreement, ``None`` for no evidence; ``agreement`` is the score of the
    accepted reading.
    """

    def __init__(self, text_layer: str) -> None:
        self.text_layer = text_layer
        self.rejected: dict[str, float | None] = {}
        self.agreement: float | None = None

    def accept(self, method: str, latex: str) -> str:
        """``latex`` when it agrees with the text layer, else ``""``.

        With text-layer text but no visible symbol on either side (``()``),
        there is no evidence the recognition read the same formula, so it is
        refused like a disagreement.
        """
        from backend.config.settings import settings

        if not latex or not self.text_layer:
            return latex
        expression, _ = split_equation_number(latex)
        score = latex_text_agreement(expression, self.text_layer)
        if score is None or score < settings.formula_text_agreement_min:
            self.rejected[method] = None if score is None else round(score, 3)
            return ""
        self.agreement = round(score, 3)
        return latex


def _first_agreeing_candidate(
    candidates: list[dict[str, Any]], gate: _TextLayerGate, method: str
) -> tuple[str, Any, int]:
    """``(latex, confidence, rank)`` of the first ranked candidate the gate accepts.

    Every candidate gets its turn at the gate before vision is paid: a
    lower-ranked one that agrees with the text layer is still a recognition of
    this crop. Refusals are recorded per rank (``math.recognize``,
    ``math.recognize#2``...). ``("", None, 1)`` when none is accepted.
    """
    for rank, candidate in enumerate(candidates, start=1):
        latex = gate.accept(method if rank == 1 else f"{method}#{rank}", candidate["latex"])
        if latex:
            return latex, candidate["confidence"], rank
    return "", None, 1


async def _formula_by_vision(
    vision: VisionAgent,
    breaker: ProviderBreaker,
    image_bytes: bytes,
    page_number: int,
    total_pages: int,
    mode: str,
) -> VisionOutput | None:
    """The vision model's reading of a formula crop, or ``None`` without one.

    The pictures and tables share the breaker, and they run around this
    stage: once the provider is declared down, the formula keeps its
    text-layer version (the behavior before the fallback) instead of paying
    two more 600 s deadlines. Only the vision fallback is gated;
    ``math.recognize`` is probed once per document through its own flag.
    """
    if breaker.open:
        return None
    output = await vision.describe_region(
        image_bytes=image_bytes,
        classification="formula",
        page_num=page_number,
        total_pages=total_pages,
        mode=mode,
        full_budget=True,
    )
    breaker.record(output is not None)
    return output


def _record_formula_recognition(
    element: ManifestElement,
    *,
    latex: str,
    method: str,
    confidence: Any,
    rank: int,
    original_text: str,
    gate: _TextLayerGate,
    page_number: int,
) -> bool:
    """Fold a formula's recognition into it, or record why there is none; True when filled.

    ``_enrich_formula_latex`` documents ``metadata["formula_recognition"]``.
    """
    if gate.rejected:
        logger.info(
            t(LOG_PDDL_FORMULA_TEXT_LAYER_DISAGREES).format(
                element_id=element.id, page=page_number, rejected=gate.rejected,
            )
        )
    if not latex:
        if gate.rejected:
            element.metadata["formula_recognition"] = {
                "method": "text-layer",
                "rejected": gate.rejected,
            }
        return False
    recognition: dict[str, Any] = {"method": method, "confidence": confidence}
    if method == "math.recognize" and rank > 1:
        recognition["rank"] = rank
    if gate.text_layer:
        # The replaced text exactly as the extractor delivered it.
        element.metadata["formula_text_layer"] = original_text
        recognition["text_agreement"] = gate.agreement
    if gate.rejected:
        recognition["rejected"] = gate.rejected
    element.text = preserve_equation_number(latex, element.metadata)
    element.metadata["formula_recognition"] = recognition
    return True
