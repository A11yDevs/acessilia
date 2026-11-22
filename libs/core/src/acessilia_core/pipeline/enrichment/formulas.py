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

The agents it asks (the vision or the data agent) live in the core, in
``acessilia_core.agents`` (ADR-0016, step 2).
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from acessilia_core.agents.output_schemas import VisionOutput
from acessilia_core.agents.provider_breaker import ProviderBreaker
from acessilia_core.agents.vision_agent import VisionAgent
from acessilia_core.blocking import run_blocking
from acessilia_core.config import (
    DocumentConfig,
    ModelConfig,
    ToolboxConfig,
    VisionConfig,
)
from acessilia_core.i18n import t
from acessilia_core.i18n.log_messages import (
    LOG_PDDL_FORMULA_RECOGNIZE_EMPTY,
    LOG_PDDL_FORMULA_RECOGNIZE_UNAVAILABLE,
    LOG_PDDL_FORMULA_TEXT_LAYER_DISAGREES,
    LOG_PDDL_FORMULAS_FELL_BACK_TO_VISION,
    LOG_PDDL_FORMULAS_RECOGNIZED,
)
from acessilia_core.i18n.stage_messages import (
    STAGE_ENRICHING_FORMULAS,
    STAGE_RECOGNIZING_FORMULA,
)
from acessilia_core.logger import logger
from acessilia_core.manifest.builder import (
    TYPE_BOUND_V23_KINDS,
    reconcile_reclassified_element_processing_needs,
    separate_equation_number,
)
from acessilia_core.manifest.models import ManifestElement, ProcessingManifest
from acessilia_core.pipeline.obligations import _pages_label
from acessilia_core.pipeline.toolbox import _source_artifact_id, _toolbox_formula_crop
from acessilia_core.ports import RegionCache
from acessilia_core.toolbox.toolbox_math_tools import (
    MathCapabilityUnavailable,
    toolbox_recognize_formula,
)
from acessilia_sdk.toolbox.clients.pdf import RENDER_MEDIA_TYPES
from docstruct.text.equations import preserve_equation_number, split_equation_number
from docstruct.text.latex import (
    bare_latex as normalize_latex,
    has_latex_markup,
    latex_text_agreement,
)


def _formula_recognition_crop(
    source_file: Path,
    element: ManifestElement,
    *,
    artifact_id: str | None = None,
    media_type: str | None = None,
    toolbox: ToolboxConfig,
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
            toolbox=toolbox,
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
    vision: VisionConfig,
    toolbox: ToolboxConfig,
    models: ModelConfig,
    region_cache: RegionCache | None,
    breaker: ProviderBreaker,
    on_progress: Callable[[], Awaitable[None]] | None = None,
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
    slots = asyncio.Semaphore(max(1, vision.concurrency))
    agent = VisionAgent(mode=mode, region_cache=region_cache, toolbox=toolbox, models=models)
    progress_lock = asyncio.Lock()

    async def classify(element: ManifestElement) -> None:
        async with slots:
            output = None
            errors: list[str] = []
            reason: str | None = "provider_blocked"
            if not breaker.open:
                reason = "crop_unavailable"
                image, page = await run_blocking(
                    _formula_recognition_crop, source_file, element,
                    artifact_id=_source_artifact_id(manifest),
                    media_type=manifest.source.media_type,
                    toolbox=toolbox,
                )
                if image:
                    reason = "model_failed"
                    output = await agent.describe_region(
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

    async def classify_and_notify(element: ManifestElement) -> None:
        """Classify one formula, then let the caller persist its outcome (#407)."""
        try:
            await classify(element)
        finally:
            if on_progress is not None:
                async with progress_lock:
                    await on_progress()

    async with asyncio.TaskGroup() as group:
        for element in candidates:
            group.create_task(classify_and_notify(element))


def _separate_equation_numbers(manifest: ProcessingManifest) -> None:
    """Move trailing equation labels into ``metadata.equation_number`` in place."""
    for element in manifest.elements:
        separate_equation_number(element)


def _formulas_needing_latex(manifest: ProcessingManifest) -> list[ManifestElement]:
    """Return formulas without LaTeX markup that are not already marked unresolved."""
    return [
        element
        for element in manifest.elements
        if element.type == "formula"
        and not has_latex_markup(element.text)
        and not element.metadata.get("latex_markup")
        and element.metadata.get("formula_classification", {}).get("status")
        != "unresolved"
    ]


@dataclass(frozen=True)
class _MathReading:
    latex: str
    confidence: Any
    rank: int


@dataclass(frozen=True)
class _VisionReading:
    latex: str
    confidence: Any
    reclassified: bool


async def _enrich_formula_latex(
    manifest: ProcessingManifest,
    source_file: Path,
    *,
    mode: str,
    document: DocumentConfig,
    vision: VisionConfig,
    toolbox: ToolboxConfig,
    models: ModelConfig,
    region_cache: RegionCache | None,
    status_callback: Callable[[str], Coroutine[Any, Any, None]] | None = None,
    breaker: ProviderBreaker | None = None,
    on_progress: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """Give LaTeX to formulas the extractor delivered without it.

    Runs ``_separate_equation_numbers`` across the manifest first, then
    delegates recognition of renderable candidates to :class:`_FormulaEnrichment`
    (which documents the ``metadata["formula_recognition"]`` contract and the
    text-layer gating, outage, breaker, and concurrency semantics).
    """
    from acessilia_sdk.toolbox.capabilities import provider_default

    _separate_equation_numbers(manifest)
    formulas = _formulas_needing_latex(manifest)
    # Without a page to render there is no crop to recognize. DOCX/PPTX
    # formulas stay as the extractor delivered them instead of paying one
    # failed render per formula.
    if not formulas or manifest.source.media_type not in RENDER_MEDIA_TYPES:
        return
    if status_callback:
        await status_callback(t(STAGE_ENRICHING_FORMULAS))

    # Resolved like ``ToolboxCapabilityClient``: an empty setting means the
    # registry default, which is the provider the request actually asked.
    recognize_provider = toolbox.providers[
        "toolbox_math_recognize_provider"
    ] or provider_default("toolbox_math_recognize_provider")
    enrichment = _FormulaEnrichment(
        manifest=manifest,
        source_file=source_file,
        mode=mode,
        status_callback=status_callback,
        vision=VisionAgent(
            mode=mode, region_cache=region_cache, toolbox=toolbox, models=models
        ),
        breaker=breaker or ProviderBreaker(vision.breaker_threshold),
        slots=asyncio.Semaphore(max(1, vision.concurrency)),
        total=len(formulas),
        recognize_provider=recognize_provider,
        toolbox=toolbox,
        agreement_min=document.formula_text_agreement_min,
        on_progress=on_progress,
    )
    await enrichment.run_batch(formulas)


class _FormulaEnrichment:
    """The state ``_enrich_formula_latex`` shares across one document's formulas.

    Covers formulas with no text and, in born-digital PDFs, formulas whose text
    is the PDF text layer (``s(t) = s0 + v0t + 1 2 at2``): ``has_latex_markup``
    tells them apart. ``math.recognize`` (PP-FormulaNet) runs first; the vision
    model is the fallback, so a Toolbox outage degrades gracefully instead of
    leaving formulas without content. Recognition runs before planning, like the
    picture descriptions, so ``mathml`` and ``latex-verbalizer`` work on real
    LaTeX.

    When a formula has text-layer text, a recognition must agree with it
    (``latex_text_agreement`` >= ``FORMULA_TEXT_AGREEMENT_MIN``): PP-FormulaNet
    reports no confidence, and the text layer is the only independent reading of
    the same formula. A recognition below threshold is tried against the next
    ranked candidate; when none agrees the formula keeps its text-layer version
    and leaves ``formula_text_layer`` and ``rejected`` on record. During a
    ``math.recognize`` outage, text-layer formulas also go to vision. A provider
    answering without LaTeX (e.g. a page-level ``docling-math`` provider on a
    chip) is not an outage: each fallback logs at DEBUG and one INFO summary
    counts them per document.

    The vision fallback shares the job's provider breaker with the picture and
    table stages: once open, each formula degrades to its text-layer text at
    once. Crops run concurrently bounded by ``VisionConfig.concurrency``, while
    the first ``math.recognize`` probe is serialized so an outage is paid once
    per document. Two formulas on the same page still pay two renders (ADR-0003).

    Each recognized formula records ``metadata["formula_recognition"]``:
    ``method`` (``math.recognize``, ``vision``, or ``text-layer`` when nothing
    agreed), ``confidence``, ``text_agreement`` when there was text-layer text,
    ``rank`` when a lower-ranked ``math.recognize`` candidate was used, and
    ``rejected`` (refused readings keyed by ``method`` or ``method#rank``,
    valued by their agreement score or ``None`` for no evidence).
    """

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
        toolbox: ToolboxConfig,
        agreement_min: float,
        on_progress: Callable[[], Awaitable[None]] | None = None,
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
        self.toolbox = toolbox
        self.agreement_min = agreement_min
        self.on_progress = on_progress
        self.total_pages = len(manifest.pages)
        self.artifact_id = _source_artifact_id(manifest)
        self.progress_lock = asyncio.Lock()
        self.recognizer = _MathRecognizer(toolbox)
        #: Crops ``math.recognize`` answered without LaTeX, outside an outage.
        self.empty_answers = 0

    async def run_batch(self, formulas: list[ManifestElement]) -> None:
        # The fold touches only its own element and runs without awaits, so
        # concurrent folds cannot interleave. The TaskGroup cancels the sibling
        # crops when one of them fails and re-raises as an ExceptionGroup, like the
        # picture descriptions; no task keeps mutating the manifest after it failed.
        async with asyncio.TaskGroup() as group:
            tasks = [
                group.create_task(self.enrich_and_notify(position, element))
                for position, element in enumerate(formulas, start=1)
            ]
        recognized = sum(task.result() for task in tasks)
        if recognized:
            logger.info(t(LOG_PDDL_FORMULAS_RECOGNIZED).format(count=recognized))
        if self.empty_answers:
            logger.info(
                t(LOG_PDDL_FORMULAS_FELL_BACK_TO_VISION).format(
                    count=self.empty_answers,
                    total=len(formulas),
                    provider=self.recognize_provider,
                )
            )

    async def enrich_and_notify(self, position: int, element: ManifestElement) -> bool:
        """Recognize one formula, then let the caller persist its outcome (#407)."""
        try:
            return await self.enrich_one(position, element)
        finally:
            if self.on_progress is not None:
                async with self.progress_lock:
                    await self.on_progress()

    async def _report_progress(self, position: int, element: ManifestElement) -> None:
        if not self.status_callback:
            return
        async with self.progress_lock:
            await self.status_callback(
                t(STAGE_RECOGNIZING_FORMULA).format(
                    current=position,
                    total=self.total,
                    pages=_pages_label([element.page_number], self.total_pages),
                )
            )

    async def _recognize_by_math(
        self,
        element: ManifestElement,
        image_bytes: bytes,
        page_number: int,
        gate: _TextLayerGate,
    ) -> _MathReading:
        candidates = await self.recognizer.recognize(image_bytes)
        if not candidates and not self.recognizer.available:
            # No reading from math.recognize because it was down, not
            # because it answered without LaTeX.
            element.metadata["formula_recognition_failure"] = "recognizer_unavailable"
        elif not candidates and self.recognizer.available:
            # An outage already warned once and skips this. No await separates
            # ``recognize`` from this check, so the flag and counter cannot race.
            self.empty_answers += 1
            logger.debug(
                t(LOG_PDDL_FORMULA_RECOGNIZE_EMPTY).format(
                    element_id=element.id,
                    page=page_number,
                    provider=self.recognize_provider,
                )
            )
        latex, confidence, rank = _first_agreeing_candidate(
            candidates, gate, "math.recognize"
        )
        return _MathReading(latex=latex, confidence=confidence, rank=rank)

    async def _fallback_to_vision(
        self,
        element: ManifestElement,
        image_bytes: bytes,
        page_number: int,
        gate: _TextLayerGate,
    ) -> _VisionReading:
        blocked = self.breaker.open
        output = await _formula_by_vision(
            self.vision, self.breaker, image_bytes, page_number, self.total_pages, self.mode
        )
        if output is None:
            element.metadata["formula_recognition_failure"] = (
                "provider_blocked" if blocked else "model_failed"
            )
            return _VisionReading(latex="", confidence=None, reclassified=False)
        if (
            output.kind == "description"
            and output.description.strip()
            and not output.classification_uncertain
        ):
            # A non-mathematical description corrects the label.
            _reclassify_formula_picture(
                self.manifest, element, output, image_bytes, source="recognition_fallback"
            )
            return _VisionReading(latex="", confidence=None, reclassified=True)
        if output.kind == "formula":
            latex = gate.accept("vision", normalize_latex(output.formula_latex or ""))
            return _VisionReading(
                latex=latex, confidence=output.confidence, reclassified=False
            )
        return _VisionReading(latex="", confidence=None, reclassified=False)

    async def enrich_one(self, position: int, element: ManifestElement) -> bool:
        """Recognize one formula and fold the answer into it; True when filled.

        A formula whose reading a provider outage changed records why in
        ``metadata["formula_recognition_failure"]``: ``recognizer_unavailable``
        (``math.recognize`` was down) or, when the vision fallback got no
        answer, ``provider_blocked`` (an open breaker) or ``model_failed``. A
        run that records one is not cached (#544 review), as for pictures.
        """
        element.metadata.pop("formula_recognition_failure", None)
        async with self.slots:
            await self._report_progress(position, element)
            image_bytes, page_number = await run_blocking(
                _formula_recognition_crop,
                self.source_file,
                element,
                artifact_id=self.artifact_id,
                media_type=self.manifest.source.media_type,
                toolbox=self.toolbox,
            )
            if not image_bytes:
                return False

            original_text = element.text or ""
            gate = _TextLayerGate(normalize_latex(original_text), self.agreement_min)
            method = "math.recognize"
            reading = await self._recognize_by_math(
                element, image_bytes, page_number, gate
            )
            latex, confidence, accepted_rank = (
                reading.latex,
                reading.confidence,
                reading.rank,
            )
            if not latex:
                method = "vision"
                vision_reading = await self._fallback_to_vision(
                    element, image_bytes, page_number, gate
                )
                if vision_reading.reclassified:
                    return False
                latex, confidence = vision_reading.latex, vision_reading.confidence

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

    def __init__(self, toolbox: ToolboxConfig) -> None:
        self.toolbox = toolbox
        self.available = True
        self._probe = asyncio.Lock()
        self._ready = asyncio.Event()

    async def _call(self, image_bytes: bytes) -> list[dict[str, Any]]:
        """One recognition call; an outage turns the flag off and means no LaTeX."""
        try:
            return await run_blocking(
                toolbox_recognize_formula,
                image_bytes,
                toolbox=self.toolbox,
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

    def __init__(self, text_layer: str, agreement_min: float) -> None:
        self.text_layer = text_layer
        self.agreement_min = agreement_min
        self.rejected: dict[str, float | None] = {}
        self.agreement: float | None = None

    def accept(self, method: str, latex: str) -> str:
        """``latex`` when it agrees with the text layer, else ``""``.

        With text-layer text but no visible symbol on either side (``()``),
        there is no evidence the recognition read the same formula, so it is
        refused like a disagreement.
        """
        if not latex or not self.text_layer:
            return latex
        expression, _ = split_equation_number(latex)
        score = latex_text_agreement(expression, self.text_layer)
        if score is None or score < self.agreement_min:
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

    :class:`_FormulaEnrichment` documents ``metadata["formula_recognition"]``.
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
