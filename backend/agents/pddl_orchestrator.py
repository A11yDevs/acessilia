from __future__ import annotations

import asyncio
import base64
import re
from collections import Counter
from collections.abc import Callable, Coroutine, Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from acessilia_sdk.toolbox.clients.adjudicate import page_judgement_probability
from acessilia_sdk.toolbox.clients.pdf import RENDER_MEDIA_TYPES
from docstruct.data_uri import decode_data_uri
from docstruct.geometry.boxes import best_effort_clip, holds_point
from docstruct.placeholders import has_meaningful_text, is_mostly_visual, is_placeholder_visual
from docstruct.tables.ast import (
    raw_rows_from_table_ast as _rows_from_table_ast,
    table_ast_column_count,
    TABLE_SECTIONS,
)
from docstruct.tables.garble import table_garble_reason
from docstruct.tables.text_rows import rows_from_visual_table_text
from docstruct.text.equations import preserve_equation_number, split_equation_number
from docstruct.text.implicit_products import (
    implicit_product_variables,
    mark_implicit_products,
)
from docstruct.text.inline_math import (
    Placement,
    assign_runs_to_cells,
    detect_inline_math_by_page,
    splice_inline_math,
    top_left_box,
)
from docstruct.text.latex import has_latex_markup, latex_text_agreement, ranked_latex_candidates
from docstruct.text.math_spans import block_prose, inline_math_sources
from docstruct.text.negation_overlay import (
    is_detached_overlay,
)

from backend.services.blocking import run_blocking
from backend.agents.data_agent import DataAgent
from backend.agents.output_schemas import DataOutput, VisionOutput
from backend.agents.provider_breaker import ProviderBreaker
from backend.agents.vision_agent import VisionAgent
from backend.core.agents.informational_structural import InformationalStructuralAgent
from backend.core.execution.executor import ExecutorAgent, MethodRegistry, StepProgress
from backend.core.execution.models import ExecutionReport, MethodResult
from backend.core.manifest.builder import (
    TYPE_BOUND_V23_KINDS,
    _derive_processing_needs,
    is_unstructured_page_placeholder,
    reconcile_reclassified_element_processing_needs,
    separate_equation_number,
)
from backend.core.manifest.models import (
    ManifestElement,
    ProcessingManifest,
)
from backend.core.manifest.toolbox_extractor import ToolboxManifestExtractor
from backend.core.planning.domain_bundle import DomainBundle
from backend.core.planning.models import NominalPlan, PlanningComparison, PlanStep
from backend.core.planning import toolbox_gate
from backend.core.planning.planner_agent import PlannerAgent
from backend.i18n import n, t
from backend.log_messages import (
    LOG_MEDIA_INSPECT_FAILED,
    LOG_PDDL_ELEMENT_CROP_FAILED,
    LOG_PDDL_EMPTY_VISION_DESCRIPTION,
    LOG_PDDL_FORMULA_RECOGNIZE_EMPTY,
    LOG_PDDL_FORMULA_RECOGNIZE_UNAVAILABLE,
    LOG_PDDL_FORMULA_TEXT_LAYER_DISAGREES,
    LOG_PDDL_FORMULAS_FELL_BACK_TO_VISION,
    LOG_PDDL_FORMULAS_RECOGNIZED,
    LOG_PDDL_IMAGES_ENRICHED,
    LOG_PDDL_PREFERRED_PLAN_MISSING,
    LOG_PDDL_TABLES_ENRICHED,
    LOG_PDDL_VISION_RETRY_PASS_PICTURES,
    LOG_PDDL_VISION_RETRY_PASS_TABLES,
    LOG_PDDL_TABLE_REREAD_ACCEPTED,
    LOG_PDDL_TABLE_REREAD_REJECTED,
    LOG_VISION_ELEMENT_DESCRIPTION,
)
from backend.stage_messages import (
    STAGE_ANALYZING_STRUCTURAL,
    STAGE_STRUCTURAL_EXTRACTION_FAILED,
    STAGE_DOCUMENT_TOO_MANY_PAGES,
    STAGE_ENRICHING_FORMULAS,
    STAGE_ENRICHING_IMAGE_DESCRIPTIONS,
    STAGE_ENRICHING_TABLES_OCR,
    STAGE_GENERATING_PDDL_PLAN,
    STAGE_VALIDATING_PLAN_DRY_RUN,
    STAGE_EXECUTING_PLAN,
    STAGE_DESCRIBING_IMAGE,
    STAGE_RECOGNIZING_FORMULA,
    STAGE_RECOGNIZING_TABLE,
    STAGE_EXECUTING_PLAN_STEP,
)
from backend.tools.formula_tools import label_spoken_formula, normalize_latex
from backend.tools.logger import logger
from backend.tools.media_inspect import inspect_source_media
from backend.tools.toolbox_math_tools import (
    MSG_MATHML_UNAVAILABLE,
    MSG_SPEECH_UNAVAILABLE,
    MathCapabilityUnavailable,
    toolbox_convert_latex,
    toolbox_recognize_formula,
    toolbox_verbalize_latex,
)
from backend.tools.toolbox_client import ToolboxError
from backend.core.pipeline.obligations import (
    _blocks_delivery,
    _formula_elements_for_obligation,
    _pages_label,
    _replannable_obligation_ids,
    _unsatisfied_selected_obligations,
    _unsatisfied_summary,
)
from backend.core.pipeline.elements import (
    _OVERLAY_HOST_TOLERANCE,
    _bbox,
    _element_to_block,
    _table_ast_from_rows,
    _table_element_has_structured_content,
    _text_kept_by_picture,
)
from backend.core.pipeline.payload import (
    build_pddl_structured_payload,
)
from backend.core.pipeline.handlers.common import (
    _missing_obligation,
    _target_elements,
)
from backend.core.pipeline.handlers.text import (
    _handle_chunk_verse_method,
    _handle_deterministic_heading_repair_method,
    _handle_extract_line_numbers_method,
    _handle_norm_fix_method,
    _handle_repetition_guard_method,
    _handle_tailjoin_method,
    _handle_unicode_repair_method,
)
from backend.core.pipeline.handlers.content import (
    _handle_pandoc_code_method,
    _handle_pandoc_table_method,
    _handle_vision_description_method,
)
from backend.core.pipeline.handlers.review import (
    _handle_human_review_method,
)
from backend.core.pipeline.handlers.fusion import (
    _handle_agreement_rule_method,
    _handle_dual_provider_fusion_method,
    _handle_single_provider_method,
    _handle_table_smart_fusion_method,
)
from backend.core.pipeline.handlers.order import (
    _handle_skeleton_order_method,
    _handle_xycut_order_method,
)
from backend.core.pipeline.secondary import (
    _CALIBRATED_PAIR,
    _SecondaryExtraction,
    _page_markdown,
    _secondary_or_failure,
)
from backend.core.pipeline.toolbox import (
    _source_artifact_id,
    _toolbox_render,
)
from backend.core.pipeline.handlers.inspection import (
    _handle_pymupdf_region_method,
    _handle_vision_page_inspection_method,
)

if TYPE_CHECKING:
    from acessilia_sdk.toolbox.clients.pdf import ClipOrigin, RenderedPage


def _implicit_product_variables(manifest: ProcessingManifest) -> frozenset[str]:
    """The letters the document uses as variables, from all its formulas.

    Read from every formula element and every inline span of the manifest, the
    same sources the canonical build reads, so a formula converted here and
    one converted there mark the same products.
    """
    sources: list[str] = []
    for element in manifest.elements:
        blocks = [
            _element_to_block(item)
            for item in [element, *_text_kept_by_picture(element)]
        ]
        for block in blocks:
            if block.get("type") == "math":
                sources.append(str(block.get("text") or ""))
            for text in block_prose(block):
                sources.extend(inline_math_sources(text))
    return implicit_product_variables(sources)


def _handle_mathml_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Converte o LaTeX das fórmulas alvo em MathML (metadata.mathml) via math.convert.

    Uma math.convert indisponível falha o método explicitamente (sem conversão
    local, ADR-0007), para o executor tentar outro método ou replanejar.
    """
    elements = _formula_elements_for_obligation(manifest, obligation_id)
    if not elements:
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhuma fórmula encontrada para a obrigação",
        )
    converted = 0
    variables = _implicit_product_variables(manifest)
    for element in elements:
        latex = mark_implicit_products(normalize_latex(element.text or ""), variables)
        try:
            mathml = toolbox_convert_latex(latex) if latex else ""
        except MathCapabilityUnavailable as exc:
            logger.warning("Handler mathml: {}", exc)
            return MethodResult(
                success=False,
                validated=False,
                message=t(MSG_MATHML_UNAVAILABLE).format(reason=exc.reason),
            )
        if mathml:
            element.metadata["mathml"] = mathml
            converted += 1
    if converted == len(elements):
        return MethodResult(
            success=True,
            validated=True,
            message=f"MathML gerado para {converted} fórmula(s)",
        )
    return MethodResult(
        success=False,
        validated=False,
        message=f"MathML gerado para {converted}/{len(elements)} fórmula(s)",
    )


def _handle_latex_verbalizer_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Gera a verbalização pt-BR das fórmulas (metadata.verbalization) via math.verbalize.

    Uma math.verbalize indisponível falha o método explicitamente (sem
    verbalizador local, ADR-0007).
    """
    elements = _formula_elements_for_obligation(manifest, obligation_id)
    if not elements:
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhuma fórmula encontrada para a obrigação",
        )
    verbalized = 0
    variables = _implicit_product_variables(manifest)
    for element in elements:
        latex = mark_implicit_products(normalize_latex(element.text or ""), variables)
        try:
            spoken = label_spoken_formula(toolbox_verbalize_latex(latex)) if latex else ""
        except MathCapabilityUnavailable as exc:
            logger.warning("Handler latex-verbalizer: {}", exc)
            return MethodResult(
                success=False,
                validated=False,
                message=t(MSG_SPEECH_UNAVAILABLE).format(reason=exc.reason),
            )
        if spoken:
            element.metadata["verbalization"] = spoken
            verbalized += 1
    if verbalized == len(elements):
        return MethodResult(
            success=True,
            validated=True,
            message=f"Verbalização gerada para {verbalized} fórmula(s)",
        )
    return MethodResult(
        success=False,
        validated=False,
        message=f"Verbalização gerada para {verbalized}/{len(elements)} fórmula(s)",
    )


def _handle_latex_normalizer_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Normalize the LaTeX of every formula target in place."""
    elements = [
        el
        for el in _target_elements(manifest, obligation_id)
        if el.type == "formula"
    ]
    if not elements:
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhuma fórmula encontrada para a obrigação",
        )

    normalized = 0
    for element in elements:
        cleaned = normalize_latex(element.text or "")
        if not cleaned:
            continue
        element.metadata["latex_normalized"] = cleaned
        normalized += 1

    if normalized != len(elements):
        return MethodResult(
            success=False,
            validated=False,
            message=(
                f"LaTeX normalizado em {normalized}/{len(elements)} fórmula(s)"
            ),
        )
    return MethodResult(
        success=True,
        validated=True,
        message=f"LaTeX normalizado em {normalized} fórmula(s)",
    )


#: Longest side of the page image sent to the judge. Two candidates plus the
#: image must fit one 8192-token slot of the production VLM server.
_JUDGE_PAGE_MAX_SIDE = 1600


def _render_page_png(
    source_path: Path,
    page_number: int,
    artifact_id: str | None = None,
    media_type: str | None = None,
) -> bytes:
    """Page ``page_number`` (1-based) of a PDF, PNG or JPEG as PNG, rendered by the Toolbox.

    At most 144 dpi, with the longest side bounded by ``_JUDGE_PAGE_MAX_SIDE``.
    """
    return _toolbox_render(
        source_path,
        page_number,
        media_type=media_type,
        dpi=144,
        max_side=_JUDGE_PAGE_MAX_SIDE,
        artifact_id=artifact_id,
    ).image

def _judge_page(image: bytes, candidate_a: str, candidate_b: str) -> dict[str, Any]:
    """Call document.adjudicate.page through the Toolbox (sync wrapper)."""
    import tempfile

    from acessilia_sdk.runtime import run_sync
    from acessilia_sdk.toolbox.clients import ToolboxAdjudicateClient

    from backend.tools.toolbox_client import make_toolbox_client

    async def call(path: Path) -> dict[str, Any]:
        client = make_toolbox_client(ToolboxAdjudicateClient)
        try:
            result = await client.judge_page(candidate_a, candidate_b, file_path=path)
        finally:
            await client.close()
        logger.info(
            "Toolbox: page adjudication finished (pB={})",
            result.get("document", {}).get("pB", "?"),
        )
        return result

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "page.png"
        path.write_bytes(image)
        return run_sync(call(path))


#: Characters per candidate the Toolbox's judge reads (``judge_max_chars`` of
#: ``qwen3-vl-8b`` in its ``providers-config.yaml``); beyond it the candidate is
#: cut on the Toolbox side, so the verdict does not cover the whole page.
_JUDGE_MAX_CHARS = 6000


def _handle_vlm_pairwise_judge_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Pairwise VLM judge between the two providers' pages.

    The Toolbox (``document.adjudicate.page``) returns the position-debiased
    probability that the secondary page is the more faithful transcription.
    Candidate A is the page the manifest carries and B the other provider's:
    the secondary page, or, on a page the deterministic router already took
    from the secondary provider (its elements carry that ``metadata.provider``),
    the primary elements it replaced. Such a page without the replaced elements
    in the artifact is skipped: comparing it with the secondary page would
    compare MinerU with itself and report a confirmation. Only pages
    where the two transcriptions diverge are judged (``should_judge``). Of
    docstruct's two-threshold rule (``decide_pair``) only the ``p_new >
    DEFAULT_NEW_THR`` branch applies: there is no previous judge to consult
    here. A confirmed page satisfies the obligation; a preferred alternative is
    recorded in ``page_judgement`` but not swapped in (that would reopen the
    manifest mid-plan), so the method fails and the non-critical obligation
    becomes a technical warning. An answer without a valid ``pB`` fails the
    method instead of counting as a confirmation.
    """
    from docstruct.fusion.judge import should_judge

    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)
    secondary, failure = _secondary_or_failure(manifest)
    if failure is not None:
        return failure

    judgements: dict[int, dict[str, Any]] = {}
    for page_number in sorted({e.page_number for e in elements if e.page_number}):
        texts = _judge_texts(manifest, secondary, page_number)
        if texts is None:
            continue
        content, other, primary_md, secondary_md = texts
        if not should_judge(primary_md, secondary_md):
            judgements[page_number] = {
                "content": content, "choice": content, "pB": None, "reason": "agree",
            }
            continue
        judgement, failure = _judge_one_page(
            manifest, page_number, content, other, primary_md, secondary_md
        )
        if failure is not None:
            return failure
        judgements[page_number] = judgement

    return _judgement_result(elements, judgements)


def _judge_texts(
    manifest: ProcessingManifest, secondary: _SecondaryExtraction, page_number: int
) -> tuple[str, str, str, str] | None:
    """``(content, other, candidate A, candidate B)`` of a page, or ``None`` to skip it.

    Candidate A is the page the manifest carries and B the other provider's.
    A page the router took from the secondary provider is skipped when the
    artifact does not keep the primary page it replaced, and any page is
    skipped when either transcription is empty.
    """
    primary_name = _CALIBRATED_PAIR[0]
    page_elements = [
        element
        for element in sorted(manifest.elements, key=lambda e: e.reading_order)
        if element.page_number == page_number
    ]
    adopted = any(
        element.metadata.get("provider") == secondary.provider
        for element in page_elements
    )
    if adopted:
        if page_number not in secondary.replaced_primary:
            logger.warning(
                "vlm-pairwise-judge: page {} came from {}, but the artifact does not "
                "keep the {} page it replaced; skipped",
                page_number,
                secondary.provider,
                primary_name,
            )
            return None
        content, other = secondary.provider, primary_name
        other_blocks = secondary.replaced_primary[page_number]
    else:
        content, other = primary_name, secondary.provider
        other_blocks = secondary.pages.get(page_number, [])
    primary_md = _page_markdown(
        (element.type, element.text) for element in page_elements
    )
    secondary_md = _page_markdown(
        (str(block.get("type") or ""), block.get("text"))
        for block in other_blocks
    )
    if not primary_md.strip() or not secondary_md.strip():
        logger.info(
            "vlm-pairwise-judge: página {} sem as duas transcrições; ignorada", page_number
        )
        return None
    return content, other, primary_md, secondary_md


def _judge_one_page(
    manifest: ProcessingManifest,
    page_number: int,
    content: str,
    other: str,
    primary_md: str,
    secondary_md: str,
) -> tuple[dict[str, Any] | None, MethodResult | None]:
    """Render a page, ask the judge, and read its answer: ``(judgement, failure)``.

    The judgement prefers ``other`` when ``pB > DEFAULT_NEW_THR``. A page
    that cannot be rendered, a refused or failed call, and an answer without a
    valid ``pB`` are failures of the method.
    """
    from docstruct.fusion.judge import DEFAULT_NEW_THR

    from backend.tools.toolbox_client import (
        ToolboxAuthenticationError,
        ToolboxContractViolation,
        ToolboxError,
    )

    source_path = Path(manifest.source.path)
    try:
        image = _render_page_png(
            source_path,
            page_number,
            _source_artifact_id(manifest),
            manifest.source.media_type,
        )
    except Exception as exc:  # noqa: BLE001 - rendering a broken source
        return None, MethodResult(
            success=False,
            validated=False,
            message=f"Página {page_number} não pôde ser renderizada: {exc}",
        )
    truncated = max(len(primary_md), len(secondary_md)) > _JUDGE_MAX_CHARS
    if truncated:
        logger.warning(
            "vlm-pairwise-judge: página {} passa de {} caracteres; "
            "o juiz lê a transcrição truncada",
            page_number,
            _JUDGE_MAX_CHARS,
        )
    logger.info("vlm-pairwise-judge: julgando a página {}", page_number)
    try:
        result = _judge_page(image, primary_md, secondary_md)
    except (ToolboxAuthenticationError, ToolboxContractViolation) as exc:
        return None, MethodResult(
            success=False,
            validated=False,
            message=f"Juiz VLM recusou a chamada: {type(exc).__name__}: {exc}",
        )
    except ToolboxError as exc:
        return None, MethodResult(
            success=False,
            validated=False,
            message=f"Juiz VLM indisponível: {type(exc).__name__}: {exc}",
        )
    document = result.get("document") or {}
    p_b = page_judgement_probability(document)
    if p_b is None:
        return None, MethodResult(
            success=False,
            validated=False,
            message=(
                f"Juiz VLM não devolveu pB válido para a página {page_number}: "
                f"{document.get('pB')!r}"
            ),
        )
    return {
        "content": content,
        "choice": other if p_b > DEFAULT_NEW_THR else content,
        "pB": p_b,
        "pB_ab": document.get("pB_ab"),
        "pA_ba": document.get("pA_ba"),
        "model": document.get("model"),
        "truncated": truncated,
    }, None


def _judgement_result(
    elements: list[ManifestElement], judgements: dict[int, dict[str, Any]]
) -> MethodResult:
    """Record each page's judgement on its elements and report the method's outcome.

    A page whose judge prefers the other provider fails the method: the swap
    is recorded, not applied. Otherwise the pages are confirmed.
    """
    if not judgements:
        return MethodResult(
            success=False,
            validated=False,
            message="Sem páginas com as duas transcrições para o juiz VLM",
        )
    for element in elements:
        if element.page_number in judgements:
            element.metadata["page_judgement"] = judgements[element.page_number]

    preferred = {
        page: judgement
        for page, judgement in judgements.items()
        if judgement["choice"] != judgement["content"]
    }
    if preferred:
        return MethodResult(
            success=False,
            validated=False,
            message=(
                "Juiz VLM prefere o outro provider ("
                + ", ".join(
                    f"p{page}: {j['choice']} pB={j['pB']:.2f}"
                    for page, j in sorted(preferred.items())
                )
                + "); a troca de página não é aplicada automaticamente"
            ),
        )
    return MethodResult(
        success=True,
        validated=True,
        message="Juiz VLM confirma a página aplicada: "
        + ", ".join(
            f"{page} ({j['content']}, pB={j['pB']:.2f})"
            if j["pB"] is not None
            else f"{page} ({j['content']}, concordam)"
            for page, j in sorted(judgements.items())
        ),
    )


DETERMINISTIC_METHOD_HANDLERS: dict[
    str, Callable[[ProcessingManifest, str], MethodResult]
] = {
    #: Method name -> handler for every method whose work is already done before
    #: planning (or can be done without a model call). A method the manifest can
    #: require but that is absent from here is reported to the planner as
    #: unavailable, so the plan never contains a step that can only fail.
    "vision-description": _handle_vision_description_method,
    "pandoc-table": _handle_pandoc_table_method,
    "pandoc-code": _handle_pandoc_code_method,
    "pymupdf-region": _handle_pymupdf_region_method,
    "vision-page-inspection": _handle_vision_page_inspection_method,
    "latex-normalizer": _handle_latex_normalizer_method,
    "norm-fix": _handle_norm_fix_method,
    "unicode-repair": _handle_unicode_repair_method,
    "rep-guard": _handle_repetition_guard_method,
    "line-number-extractor": _handle_extract_line_numbers_method,
    "verse-chunker": _handle_chunk_verse_method,
    "tailjoin": _handle_tailjoin_method,
    "tailjoin-positioned": _handle_tailjoin_method,
    "xycut-order": _handle_xycut_order_method,
    "skeleton-order": _handle_skeleton_order_method,
    "table-smart-fusion": _handle_table_smart_fusion_method,
    "agreement-rule": _handle_agreement_rule_method,
    "deterministic-heading-repair": _handle_deterministic_heading_repair_method,
}


class StructuralExtractionError(RuntimeError):
    """The Toolbox could not extract the document structure (job-level failure)."""


class DocumentTooLargeError(ValueError):
    """The document has more pages than ``MAX_PAGES`` (job-level failure)."""


def _check_page_count(page_count: int) -> None:
    """Reject an oversized document as a whole with a user-facing message.

    A verified PDF count may be checked before costly extraction. The
    authoritative manifest count is checked afterwards for every format,
    including those without a reliable preflight count. Neither check allows
    partial processing beyond MAX_PAGES.

    Raises:
        DocumentTooLargeError: When the page count exceeds MAX_PAGES.
    """
    from backend.config.settings import settings

    if page_count > settings.max_pages:
        raise DocumentTooLargeError(
            t(STAGE_DOCUMENT_TOO_MANY_PAGES).format(
                page_count=page_count, max_pages=settings.max_pages
            )
        )


def _check_page_limit_before_extraction(inspection: dict[str, Any] | None) -> None:
    """Reject only PDF counts verified by the existing remote PDF parser.

    Scanned content streams, unknown counts and non-PDF formats are not a
    reliable early limit. They retain the authoritative post-extraction check.
    No local operational parser is introduced (ADR-0003).
    """
    if not isinstance(inspection, dict):
        return
    count = inspection.get("page_count")
    if (
        inspection.get("is_pdf") is True
        and inspection.get("page_count_source") == "pymupdf"
        and type(count) is int
        and count > 0
    ):
        _check_page_count(count)


def _check_page_limit(manifest: ProcessingManifest) -> None:
    """Authoritative limit after extraction, including formats without preflight."""
    _check_page_count(len(manifest.pages))


class PddlAccessibilityOrchestrator:
    """Drives the PDDL pipeline: informational-extraction -> planner -> executor.

    Args:
        planner_backend (str): Which planner backend to prefer for nominal-plan generation; defaults to "internal".
        preferred_plan (str): Which plan source to prefer when multiple are available; defaults to "internal".
        execute_dry_run (bool): When True the produced plan is only validated in dry-run instead of executed for real; defaults to True.
        fast_downward (Path | None): Optional filesystem path to a fast-downward binary used when planner_backend is fast-downward; defaults to None.
        fast_downward_alias (str | None): Optional shell alias to invoke fast_downward through instead of the raw path; defaults to None.
        fast_downward_search (str): Fast-downward search heuristic string passed when the backend is active; defaults to "astar(blind())".
        enable_ocr (bool): Whether the docling extraction backend should run its OCR pass; defaults to True.
        extractor_backend (str): Which manifest-extraction backend to use.
            Supported values:
            - "toolbox" — ToolboxManifestExtractor (remote via Acessilia Toolbox)
            - "toolbox-layout" / "toolbox_layout" — mapped to "toolbox" (same REST API)
            Defaults to "toolbox".
    """

    def __init__(
        self,
        *,
        planner_backend: str = "internal",
        preferred_plan: str = "internal",
        execute_dry_run: bool = True,
        fast_downward: Path | None = None,
        fast_downward_alias: str | None = None,
        fast_downward_search: str = "astar(blind())",
        enable_ocr: bool = True,
        extractor_backend: str = "toolbox",
        max_replans: int = 2,
    ) -> None:
        self.planner_backend = planner_backend
        self.preferred_plan = preferred_plan
        self.execute_dry_run = execute_dry_run
        self.max_replans = max(0, max_replans)
        self.fast_downward = fast_downward
        self.fast_downward_alias = fast_downward_alias
        self.fast_downward_search = fast_downward_search
        self.extractor_backend = extractor_backend.strip().lower()

        if self.extractor_backend in ("toolbox", "toolbox-layout", "toolbox_layout"):
            logger.info(
                "PDDL extractor_backend={}: usando ToolboxManifestExtractor",
                self.extractor_backend,
            )
            extractor = ToolboxManifestExtractor(enable_ocr=enable_ocr)
        else:
            raise ValueError(
                f"Extractor local '{self.extractor_backend}' desativado. "
                f"Use extractor_backend='toolbox' para o pipeline PDDL+Toolbox."
            )

        self.information_structural = InformationalStructuralAgent(
            extractor
        )
        self.planner = PlannerAgent()
        self.executor = self._build_executor()

    @staticmethod
    def _build_executor() -> ExecutorAgent:
        registry = MethodRegistry()

        # Model-backed or cross-cutting methods already wired by the pipeline.
        registry.register("mathml", _handle_mathml_method)
        registry.register("latex-verbalizer", _handle_latex_verbalizer_method)
        registry.register(
            "dual-provider-fusion", _handle_dual_provider_fusion_method
        )
        registry.register("single-provider", _handle_single_provider_method)
        registry.register("vlm-pairwise-judge", _handle_vlm_pairwise_judge_method)
        for method, handler in DETERMINISTIC_METHOD_HANDLERS.items():
            registry.register(method, handler)

        # `human-review` has its own semantics: it is the terminal escalation the
        # pipeline performs when no automated method can satisfy an obligation.
        registry.register("human-review", _handle_human_review_method)

        return ExecutorAgent(registry, domain=DomainBundle.load())

    async def execute(
        self,
        file_path: Path,
        tmpdir: Path,
        status_callback: Callable[[str], Coroutine[Any, Any, None]] | None = None,
        mode: str | None = None,
        structured_output: bool = False,
        custom_prompt: str | None = None,
        thinking_mode: bool = False,
    ) -> str | dict[str, Any]:
        effective_mode = mode or "medio"

        if custom_prompt or thinking_mode:
            raise ValueError("Custom instructions and thinking mode are unavailable for this pipeline")

        source_path = file_path.resolve()
        # media.inspect runs first: a slide deck is extracted and structured
        # slide by slide, which has to be decided before extraction.
        media_inspection, media_configuration = await _inspect_media(source_path)
        _check_page_limit_before_extraction(media_inspection)
        presentation = _is_presentation(media_inspection)

        if status_callback:
            await status_callback(t(STAGE_ANALYZING_STRUCTURAL))
        manifest = await self._extract_structure(source_path, presentation)
        _check_page_limit(manifest)
        manifest.extractor.configuration["region_inspection_mode"] = effective_mode
        manifest.extractor.configuration.update(media_configuration)

        await self._enrich_before_planning(
            manifest, file_path, source_path, effective_mode, media_inspection, status_callback
        )

        if status_callback:
            await status_callback(t(STAGE_GENERATING_PDDL_PLAN))
        # One catalogue snapshot per document, so the first plan and every replan
        # see the same Toolbox.
        availability = await toolbox_gate.decide(manifest)
        _log_availability(availability)
        gated = availability.unavailable_methods
        plan, comparison = await run_blocking(
            self._build_plan, manifest, extra_unavailable=gated
        )

        execution_report: ExecutionReport | None = None
        if status_callback:
            await status_callback(
                t(STAGE_VALIDATING_PLAN_DRY_RUN)
                if self.execute_dry_run
                else t(STAGE_EXECUTING_PLAN)
            )
        # `execute_dry_run` selects the *mode* of execution; it used to also gate
        # whether the executor ran at all, so setting it to false produced a plan
        # that was never executed and a report of None. Real execution is now the
        # other branch instead of silence.
        loop = asyncio.get_running_loop()
        manifest, execution_report = await run_blocking(
            self.executor.execute,
            plan,
            manifest,
            dry_run=self.execute_dry_run,
            progress=_plan_progress(manifest, status_callback, loop),
        )
        manifest, execution_report, plan, comparison = await self._replan_until_done(
            manifest, execution_report, plan, comparison, gated, status_callback, loop
        )
        self._check_unsatisfied(manifest, execution_report)

        payload = build_pddl_structured_payload(
            file_path=file_path,
            manifest=manifest,
            plan=plan,
            planner_backend=self.planner_backend,
            execution_report=execution_report,
            comparison=comparison,
            toolbox_availability=availability.to_metadata(),
        )

        if structured_output:
            return payload
        return payload["text"]

    async def _extract_structure(self, source_path: Path, presentation: bool) -> ProcessingManifest:
        """The document's manifest from ``document.structure.extract``.

        A Toolbox failure becomes a ``StructuralExtractionError`` whose message
        names only the capability and the kind of failure.
        """
        try:
            return await run_blocking(
                self.information_structural.process,
                source_path,
                language="pt-BR",
                presentation=presentation,
            )
        except ToolboxError as exc:
            # The SDK already retried and failed over; there is no local
            # extractor to fall back on (docs/adr/0003), so the job fails here.
            # The message reaches the end user, so it names the capability and
            # the kind of failure only; the full cause, which carries internal
            # Toolbox endpoints, goes to the log and stays chained.
            logger.error("Structural extraction failed on the Toolbox: {}", exc)
            raise StructuralExtractionError(
                t(STAGE_STRUCTURAL_EXTRACTION_FAILED).format(
                    capability="document.structure.extract", error=type(exc).__name__
                )
            ) from exc

    async def _enrich_before_planning(
        self,
        manifest: ProcessingManifest,
        file_path: Path,
        source_path: Path,
        effective_mode: str,
        media_inspection: dict[str, Any] | None,
        status_callback: Callable[[str], Coroutine[Any, Any, None]] | None,
    ) -> None:
        """Describe pictures, recognize formulas and inline math, read tables.

        The steps run in this order and share one provider breaker; the inline
        math of prose and of tables share one text-span reader. ``source_path``
        is ``file_path`` resolved.
        """
        if status_callback:
            await status_callback(t(STAGE_ENRICHING_IMAGE_DESCRIPTIONS))
        # Pictures, formulas and tables reach the vision provider from the
        # same pipeline, so one that went down does not get called again for
        # every remaining object.
        from backend.config.settings import settings

        breaker = ProviderBreaker(settings.vision_breaker_threshold)
        await _classify_formula_regions(
            manifest, source_path, mode=effective_mode, breaker=breaker,
        )
        await _enrich_picture_descriptions(
            manifest,
            source_path,
            mode=effective_mode,
            media_inspection=media_inspection,
            status_callback=status_callback,
            breaker=breaker,
        )
        text_spans = _TextSpanReader(manifest, source_path)
        await _mark_inline_math(manifest, source_path, text_spans)
        await _enrich_formula_latex(
            manifest,
            source_path,
            mode=effective_mode,
            status_callback=status_callback,
            breaker=breaker,
        )

        if status_callback:
            await status_callback(t(STAGE_ENRICHING_TABLES_OCR))
        await _enrich_table_structures(
            manifest,
            file_path.resolve(),
            status_callback=status_callback,
            breaker=breaker,
        )
        # After the table enrichment, which can replace a table's cells.
        await _mark_table_inline_math(manifest, source_path, text_spans)

    async def _replan_until_done(
        self,
        manifest: ProcessingManifest,
        execution_report: ExecutionReport,
        plan: Any,
        comparison: Any,
        gated: Any,
        status_callback: Callable[[str], Coroutine[Any, Any, None]] | None,
        loop: asyncio.AbstractEventLoop,
    ) -> tuple[ProcessingManifest, ExecutionReport, Any, Any]:
        """Plan and execute again while the report asks for it, up to ``max_replans``.

        Returns the last manifest, report, plan and comparison.
        """
        # A `replan-required` report means the executor recorded `(tried ?o ?m)`
        # for a method that failed and left the obligation pending. Without this
        # loop the status was terminal in production: the pipeline returned a plan
        # it already knew was wrong, and `complete-job` never ran, so no document
        # was produced.
        replans = 0
        while (
            execution_report.replan_required
            and replans < self.max_replans
            and not self.execute_dry_run
        ):
            # Steps after a failure still run, so one execution can leave an
            # obligation exhausted (no method left) next to another that has an
            # alternative. The planner rejects exhausted obligations, so they are
            # left out of the replan; an exhausted critical one fails the job.
            exhausted = [
                obligation for obligation in manifest.obligations
                if obligation.status == "failed"
            ]
            if any(_blocks_delivery(obligation, manifest) for obligation in exhausted):
                break
            roots = _replannable_obligation_ids(manifest)
            if not roots:
                break
            replans += 1
            logger.info(
                "PDDL: replanejando ({}/{}) após {}",
                replans,
                self.max_replans,
                execution_report.status,
            )
            plan, comparison = await run_blocking(
                self._build_plan,
                manifest,
                extra_unavailable=gated,
                selected_roots=roots,
            )
            manifest, execution_report = await run_blocking(
                self.executor.execute,
                plan,
                manifest,
                dry_run=False,
                progress=_plan_progress(manifest, status_callback, loop),
            )
        return manifest, execution_report, plan, comparison

    @staticmethod
    def _check_unsatisfied(manifest: ProcessingManifest, execution_report: ExecutionReport) -> None:
        """Fail the job when an obligation that blocks delivery is open.

        A run that did not complete fails when nothing is open (the failure is
        elsewhere) or a critical obligation is; with only refinements open, the
        document is delivered with a technical warning.
        """
        if execution_report.status not in {"completed", "dry-run-completed"}:
            unsatisfied = _unsatisfied_selected_obligations(manifest)
            critical = [
                obligation for obligation in unsatisfied
                if _blocks_delivery(obligation, manifest)
            ]
            if not unsatisfied or critical:
                # The ids name every target element and run to kilobytes on a
                # long document, so they go to the log; the job error, which
                # reaches the user by e-mail, says what is open and where.
                logger.warning(
                    "PDDL: unsatisfied obligations: {}",
                    ", ".join(obligation.id for obligation in unsatisfied),
                )
                raise RuntimeError(_unsatisfied_summary(manifest))
            # Only refinements are left open; the extracted content is still
            # complete, so the document is delivered with a technical warning.
            logger.warning(
                "PDDL: concluindo com obrigações não críticas pendentes: {}",
                ", ".join(obligation.id for obligation in unsatisfied),
            )

    def _build_plan(
        self,
        manifest: ProcessingManifest,
        *,
        extra_unavailable: Iterable[str] = (),
        selected_roots: Iterable[str] | None = None,
    ) -> tuple[NominalPlan, PlanningComparison | None]:
        # Tell the compiler which methods the executor can actually run. Without
        # this the planner happily emits steps for methods that have no handler,
        # and the failure only surfaces at execution time -- after the model-backed
        # work has already been paid for. ``extra_unavailable`` adds the methods
        # the Toolbox availability gate rules out for this document.
        unavailable = sorted(
            set(self._unavailable_methods(manifest)) | set(extra_unavailable)
        )
        if self.planner_backend == "both":
            _, plans, comparison = self.planner.compare(
                manifest,
                selected_roots=selected_roots,
                unavailable_methods=unavailable,
                fast_downward=self.fast_downward,
                fast_downward_alias=self.fast_downward_alias,
                fast_downward_search=self.fast_downward_search,
                preferred_backend=self.preferred_plan,
            )
            if self.preferred_plan not in plans:
                raise RuntimeError(
                    t(LOG_PDDL_PREFERRED_PLAN_MISSING).format(
                        backend=self.preferred_plan
                    )
                )
            return plans[self.preferred_plan], comparison

        _, plan = self.planner.plan(
            manifest,
            selected_roots=selected_roots,
            unavailable_methods=unavailable,
            backend=self.planner_backend,
            fast_downward=self.fast_downward,
            fast_downward_alias=self.fast_downward_alias,
            fast_downward_search=self.fast_downward_search,
        )
        return plan, None

    def _unavailable_methods(self, manifest: ProcessingManifest) -> list[str]:
        """Methods this manifest can ask for that no registered handler implements.

        The set is restricted to the methods the manifest actually declares: the
        compiler rejects unknown names on purpose, so passing every method that
        exists anywhere would be reported as a typo instead of a capability gap.
        """
        registered = set(self.executor.registry.names())
        requested = {
            method
            for obligation in manifest.obligations
            for method in obligation.admissible_methods
        }
        return sorted(requested - registered)


#: Why a picture was left undescribed, recorded in metadata["vision_failure_reason"]
#: for the operator: the crop could not be rendered, the source has no page to
#: render and the extraction embedded no image in the picture (a DOCX or HTML
#: picture, so the model was never asked), the vision call failed (its error
#: goes to metadata["vision_failure_detail"]), or the answer had no text.
VisionFailureReason = Literal[
    "crop_unavailable", "image_unavailable", "model_failed", "empty_description"
]


def _record_vision_failure(
    element: ManifestElement, reason: VisionFailureReason, detail: str | None = None
) -> None:
    """Mark ``element`` as undescribed and say why, so a later pass describes it again."""
    element.metadata.pop("vision_description_complete", None)
    element.metadata["vision_failure_reason"] = reason
    if detail:
        element.metadata["vision_failure_detail"] = detail
    else:
        element.metadata.pop("vision_failure_detail", None)


async def _enrich_picture_descriptions(
    manifest: ProcessingManifest,
    source_file: Path,
    *,
    mode: str,
    media_inspection: dict[str, Any] | None = None,
    status_callback: Callable[[str], Coroutine[Any, Any, None]] | None = None,
    breaker: ProviderBreaker | None = None,
) -> None:
    from backend.config.settings import settings

    _inject_full_page_picture(manifest, media_inspection)

    pictures = _pictures_to_describe(manifest)
    if not pictures:
        return

    vision = VisionAgent(mode=mode)
    breaker = breaker or ProviderBreaker(settings.vision_breaker_threshold)
    total_pages = len(manifest.pages)

    # Descriptions are independent, so they run concurrently, bounded by
    # VISION_CONCURRENCY to stay inside what the model provider accepts (a
    # rate-limited hosted API, or a local Ollama that queues beyond its own
    # parallelism). The progress callback is serialized separately: two
    # admitted tasks would otherwise interleave the state writes behind it
    # (the API's status persistence, the Telegram progress message), and even
    # serialized the emission order may vary with completion, so nothing here
    # promises FIFO delivery.
    slots = asyncio.Semaphore(max(1, settings.vision_concurrency))
    progress_lock = asyncio.Lock()

    async def describe_one(position: int, element: ManifestElement) -> bool:
        """Describe one picture and fold the answer into it; True when enriched."""
        fallback_page_number = element.page_number
        if fallback_page_number is None and len(manifest.pages) == 1:
            fallback_page_number = manifest.pages[0].page_number

        async with slots:
            if status_callback:
                async with progress_lock:
                    await status_callback(
                        t(STAGE_DESCRIBING_IMAGE).format(
                            current=position,
                            total=len(pictures),
                            pages=_pages_label([fallback_page_number], len(manifest.pages)),
                        )
                    )
            if breaker.open:
                _record_vision_failure(element, "model_failed", breaker.skip_detail())
                return False
            image_bytes, page_number = await run_blocking(
                _extract_picture_bytes,
                source_file,
                element,
                fallback_page_number,
                _source_artifact_id(manifest),
                manifest.source.media_type,
            )
            if not image_bytes:
                _record_vision_failure(
                    element,
                    "crop_unavailable" if page_number >= 1 else "image_unavailable",
                )
                return False

            errors: list[str] = []
            vision_output = await vision.describe_region(
                image_bytes=image_bytes,
                # A whole presentation slide gets the page prompt and budget.
                classification=(
                    "full_page_image" if element.metadata.get("slide_visual") else "embedded_image"
                ),
                page_num=page_number,
                total_pages=total_pages,
                mode=mode,
                errors=errors,
            )
            breaker.record(isinstance(vision_output, VisionOutput))

        if not isinstance(vision_output, VisionOutput):
            _record_vision_failure(element, "model_failed", errors[-1] if errors else None)
            return False
        return _fold_picture_description(manifest, element, vision_output, page_number)

    # The fold above touches only its own element and runs without awaits, so
    # concurrent folds cannot interleave. The TaskGroup cancels the sibling
    # descriptions when one of them fails and re-raises as an ExceptionGroup,
    # matching the sequential stage this replaced — the first failure aborted
    # the stage — without leaving tasks mutating the manifest after it failed.
    async with asyncio.TaskGroup() as group:
        tasks = [
            group.create_task(describe_one(position, element))
            for position, element in enumerate(pictures, start=1)
        ]
    enriched = sum(task.result() for task in tasks)
    enriched += await _retry_failed(
        [
            (position, element)
            for position, element in enumerate(pictures, start=1)
            if element.metadata.get("vision_failure_reason") in _RETRIED_VISION_FAILURES
        ],
        describe_one,
        kind="pictures",
        breaker=breaker,
    )

    if enriched:
        logger.info(t(LOG_PDDL_IMAGES_ENRICHED).format(count=enriched))


def _pictures_to_describe(manifest: ProcessingManifest) -> list[ManifestElement]:
    """The elements the vision step describes, none already described.

    The pictures; without any, in a mostly visual document, the elements that
    stand in for visual content (``is_placeholder_visual``); and without
    those either, in a one-page mostly visual document, its first element
    that is not an unstructured-page placeholder (a page inspection reads
    that one).
    """
    pictures = [
        element
        for element in manifest.elements
        if element.type == "picture"
        and not element.metadata.get("vision_description_complete")
    ]
    if not pictures and is_mostly_visual(manifest.elements):
        pictures = [
            element
            for element in manifest.elements
            if is_placeholder_visual(element)
            and not element.metadata.get("vision_description_complete")
        ]

    if (
        not pictures
        and is_mostly_visual(manifest.elements)
        and len(manifest.pages) == 1
        and manifest.elements
    ):
        pictures = [element for element in manifest.elements
                    if not element.metadata.get("vision_description_complete")
                    and not is_unstructured_page_placeholder(element)][:1]
    return pictures


def _fold_picture_description(
    manifest: ProcessingManifest,
    element: ManifestElement,
    vision_output: VisionOutput,
    page_number: int,
) -> bool:
    """Fold the vision model's answer into ``element``; True when it is now described.

    A formula answer makes the element a formula; a description makes it a
    picture. The element is marked described when the model answered, or
    when its extractor text is still meaningful; otherwise its text is
    cleared and it is recorded as an empty description.
    """
    logger.debug(
        t(LOG_VISION_ELEMENT_DESCRIPTION).format(
            element_id=element.id,
            page_num=page_number,
            chars=len(vision_output.description),
            description=vision_output.description,
        )
    )
    element.metadata["vision_language"] = vision_output.language
    element.metadata["vision_confidence"] = vision_output.confidence
    element.metadata["vision_elements"] = list(vision_output.mentioned_elements)
    if vision_output.warnings:
        element.metadata["vision_warnings"] = list(vision_output.warnings)

    if vision_output.kind == "formula":
        element.text = vision_output.formula_latex or ""
        answered = bool(element.text.strip())
        _retype_element(manifest, element, "formula")
    else:
        # An empty answer keeps text the extractor already had; whether
        # that text is worth keeping is decided below.
        answered = bool(vision_output.description.strip())
        if answered:
            element.text = vision_output.description
        _retype_element(manifest, element, "picture")
    if element.page_number is None and page_number >= 1:
        element.page_number = page_number
    # The model's own text stands however short ("Logo" is a description);
    # text left over from the extractor after an empty answer must still be
    # meaningful. Otherwise the picture is reported as undescribed, so the
    # operator sees the model refused instead of a silent gap, and stays
    # eligible for a later pass.
    if answered or has_meaningful_text(element):
        element.metadata["vision_description_complete"] = True
        element.metadata.pop("vision_failure_reason", None)
        element.metadata.pop("vision_failure_detail", None)
        return True
    # What is left is an extractor placeholder ("body") or OCR noise, which
    # must not become the alt text.
    element.text = ""
    _record_vision_failure(element, "empty_description")
    logger.warning(
        t(LOG_PDDL_EMPTY_VISION_DESCRIPTION).format(
            element_id=element.id
        )
    )
    return False


def _retype_element(
    manifest: ProcessingManifest, element: ManifestElement, new_type: Literal["formula", "picture"]
) -> None:
    """Make ``element`` a ``new_type``, keeping its ``original_type``, and update its needs.

    Nothing changes when it already is one.
    """
    if element.type == new_type:
        return
    previous_type = element.type
    element.metadata["original_type"] = element.type
    element.type = new_type
    element.raw_label = new_type
    reconcile_reclassified_element_processing_needs(
        manifest,
        element,
        previous_type=previous_type,
    )


#: Picture failures a second try may fix: the provider gave no answer, or an
#: empty one (empty answers are never cached, so the try reaches the model). A
#: crop that could not be rendered will not render the second time either.
_RETRIED_VISION_FAILURES = frozenset({"model_failed", "empty_description"})


async def _retry_failed(
    failed: list[tuple[int, ManifestElement]],
    attempt: Callable[[int, ManifestElement], Coroutine[Any, Any, bool]],
    *,
    kind: str,
    breaker: ProviderBreaker,
) -> int:
    """Try once more, one at a time, what a vision stage left without a
    usable answer: the calls the model failed, and the pictures it answered
    empty.

    A provider that failed for a while (006.pdf v5 lost every picture after
    slide 10) may be back after a wait. The breaker lets the first try through
    even when open, and a failure of it opens the breaker again, so a provider
    that is still down costs one call, not one per object. Returns how many
    objects the pass enriched.
    """
    from backend.config.settings import settings

    if not failed:
        return 0
    delay = max(0, settings.vision_retry_pass_delay_seconds)
    kind_msgids = (
        LOG_PDDL_VISION_RETRY_PASS_PICTURES
        if kind == "pictures"
        else LOG_PDDL_VISION_RETRY_PASS_TABLES
    )
    logger.warning(
        n(*kind_msgids, len(failed)).format(count=len(failed), delay=delay)
    )
    await asyncio.sleep(delay)
    breaker.probe()
    enriched = 0
    for position, element in failed:
        enriched += await attempt(position, element)
    return enriched


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
    its text normalizes to empty). Everything else is rendered from the
    element's provenance box.
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
    clip, origin = best_effort_clip(provenance.bbox if provenance is not None else None)
    if clip is None:
        return None, page_number
    try:
        page = _toolbox_render(
            source_file,
            page_number,
            media_type=media_type,
            dpi=200,
            clip=clip,
            clip_origin=origin,
            artifact_id=artifact_id,
        )
    except Exception as exc:
        # A DOCX has no page to render, and the Toolbox may refuse the box;
        # both leave the formula without a crop instead of failing the job.
        logger.warning(
            "Formula crop failed for {} ({}): {}", element.id, type(exc).__name__, exc
        )
        return None, page_number
    left, top, right, bottom = page.clip
    if right - left < 4 or bottom - top < 4:
        return None, page_number
    return page.image, page_number


#: Element types whose text the exporters render as prose with inline math.
_INLINE_MATH_ELEMENT_TYPES = frozenset({"paragraph", "list_item", "caption", "footnote"})


class _TextSpanReader:
    """The text layer's spans of one document, each page fetched once (#260).

    The prose and table steps of the inline math detection run at different
    points of the pipeline; reading through one reader, a page is requested
    from the Toolbox once, and a capability that failed is not asked again.
    """

    def __init__(self, manifest: ProcessingManifest, source_path: Path) -> None:
        self._manifest = manifest
        self._source_path = source_path
        self._pages: dict[int, dict[str, Any]] = {}
        self._failed = False

    async def pages(self, wanted: Iterable[int]) -> dict[int, dict[str, Any]] | None:
        """The spans of every page read so far, ``wanted`` included; ``None`` when
        the Toolbox cannot read them (recorded as ``unavailable``)."""
        from acessilia_sdk.toolbox.errors import ToolboxError

        from backend.tools.text_spans import fetch_text_spans

        if self._failed:
            return None
        missing = sorted(set(wanted) - set(self._pages))
        if missing:
            try:
                self._pages.update(
                    await fetch_text_spans(
                        self._source_path, missing, artifact_id=_source_artifact_id(self._manifest)
                    )
                )
            except ToolboxError as exc:
                logger.info("Inline math detection skipped: document.text.spans failed ({})", exc)
                self._manifest.extractor.configuration["inline_math_detection"] = "unavailable"
                self._failed = True
                return None
        return self._pages


def _inline_math_enabled(manifest: ProcessingManifest) -> bool:
    from backend.config.settings import settings

    return (
        settings.inline_math_detection == "fonts"
        and manifest.source.media_type == "application/pdf"
    )


def _boxed_pages(elements: Iterable[ManifestElement]) -> list[int]:
    return sorted(
        {
            provenance.page_number
            for element in elements
            for provenance in element.provenance
            if provenance.bbox is not None
        }
    )


async def _mark_inline_math(
    manifest: ProcessingManifest,
    source_path: Path,
    text_spans: _TextSpanReader | None = None,
) -> dict[str, int]:
    """Write the inline math of PDF prose as ``$…$``, from the text layer's fonts (#265).

    Docling reports no inline formula region for a typeset PDF, so
    ``s(t) = t³`` arrives as ``s ( t ) = t 3``. The text layer still has the
    fonts and baselines (ADR 0011): the Toolbox's ``document.text.spans``
    returns them, ``docstruct.text.inline_math`` finds each run of math in an
    element's lines and rebuilds its LaTeX, and splices it into the element's
    text where both character sequences align. The canonical enrichment then
    converts each span (MathML, speech).

    A negation slash the run composed into its relation (``h \neq 0``) is
    recorded on its detached-slash element (``negation_overlay`` outcome
    ``inline-math``), so the later reattachment does not compose another
    ``=`` of the paragraph. Returns ``{elements, marked, unmatched}``; the
    detection is skipped for other media, with ``INLINE_MATH_DETECTION=off``
    and when the Toolbox cannot read the spans.
    """
    counts = {"elements": 0, "marked": 0, "unmatched": 0}
    if not _inline_math_enabled(manifest):
        return counts
    candidates = [
        element
        for element in manifest.elements
        if element.type in _INLINE_MATH_ELEMENT_TYPES
        and (element.text or "").strip()
        and "inline_math_detection" not in element.metadata
        and any(provenance.bbox is not None for provenance in element.provenance)
    ]
    pages = _boxed_pages(candidates)
    if not pages:
        return counts
    spans = await (text_spans or _TextSpanReader(manifest, source_path)).pages(pages)
    if spans is None:
        return counts

    heights = {page.page_number: page.height for page in manifest.pages}
    overlays = [element for element in manifest.elements if is_detached_overlay(element.text)]
    for element in candidates:
        detection = detect_inline_math_by_page(_placements(element), spans, heights)
        if not detection.runs:
            continue
        result = splice_inline_math(element.text or "", detection)
        counts["elements"] += 1
        counts["marked"] += len(result.marked)
        counts["unmatched"] += len(result.unmatched)
        element.metadata["inline_math_detection"] = {
            "marked": len(result.marked),
            "unmatched": len(result.unmatched),
        }
        if not result.marked:
            continue
        element.text = result.text
        for run in result.marked:
            for slash in run.negations:
                _claim_negation_overlay(overlays, element, slash, run.page, spans, heights)
    manifest.extractor.configuration["inline_math_detection"] = "fonts"
    if counts["elements"]:
        logger.info("Inline math from the text layer's fonts: {}", counts)
    return counts


async def _mark_table_inline_math(
    manifest: ProcessingManifest,
    source_path: Path,
    text_spans: _TextSpanReader | None = None,
) -> dict[str, int]:
    """Write the inline math of PDF table cells as ``$…$`` (#260).

    The prose step's detection over the table's text-layer lines, run after
    the table enrichment so a table read again keeps its marks. A table's
    cells carry no boxes: ``assign_runs_to_cells`` gives each run to the cell
    whose text holds it, and each cell is spliced on its own. A fraction set
    in a header cell (two stacked script-size lines) becomes ``\\frac``.
    Returns ``{elements, marked, unmatched}``, skipping as the prose step does.
    """
    counts = {"elements": 0, "marked": 0, "unmatched": 0}
    if not _inline_math_enabled(manifest):
        return counts
    tables = [
        element
        for element in manifest.elements
        if element.type == "table"
        and isinstance(element.metadata.get("table_ast"), dict)
        and "inline_math_detection" not in element.metadata
        and any(provenance.bbox is not None for provenance in element.provenance)
    ]
    pages = _boxed_pages(tables)
    if not pages:
        return counts
    spans = await (text_spans or _TextSpanReader(manifest, source_path)).pages(pages)
    if spans is None:
        return counts

    heights = {page.page_number: page.height for page in manifest.pages}
    overlays = [element for element in manifest.elements if is_detached_overlay(element.text)]
    for table in tables:
        detection = detect_inline_math_by_page(_placements(table), spans, heights)
        if not detection.runs:
            continue
        cells = [
            cell
            for section in TABLE_SECTIONS
            for row in table.metadata["table_ast"].get(section) or []
            if isinstance(row, dict)
            for cell in row.get("cells") or []
            if isinstance(cell, dict) and isinstance(cell.get("text"), str)
        ]
        detections, left_out = assign_runs_to_cells(detection, [cell["text"] for cell in cells])
        marked, unmatched = [], list(left_out)
        for cell, cell_detection in zip(cells, detections):
            if not cell_detection.runs:
                continue
            result = splice_inline_math(cell["text"], cell_detection)
            cell["text"] = result.text
            marked.extend(result.marked)
            unmatched.extend(result.unmatched)
        counts["elements"] += 1
        counts["marked"] += len(marked)
        counts["unmatched"] += len(unmatched)
        table.metadata["inline_math_detection"] = {
            "marked": len(marked),
            "unmatched": len(unmatched),
        }
        for run in marked:
            for slash in run.negations:
                _claim_negation_overlay(overlays, table, slash, run.page, spans, heights)
    if counts["elements"]:
        logger.info("Inline math of table cells from the text layer's fonts: {}", counts)
    return counts


def _placements(element: ManifestElement) -> list[Placement]:
    """The element's pages and boxes, as ``docstruct.text.inline_math`` reads them."""
    return [(provenance.page_number, provenance.bbox) for provenance in element.provenance]


def _claim_negation_overlay(
    overlays: list[ManifestElement],
    host: ManifestElement,
    slash: tuple[float, float, float, float],
    page: int,
    spans: dict[int, dict[str, Any]],
    heights: dict[int, float | None],
) -> None:
    """Record the detached slash at ``slash`` as composed by the inline math of ``host``."""
    x, y = (slash[0] + slash[2]) / 2, (slash[1] + slash[3]) / 2
    for overlay in overlays:
        if "negation_overlay" in overlay.metadata:
            continue
        located = _bbox(overlay, page)
        if located is None:
            continue
        box = top_left_box(located[1], page, spans, heights)
        if box is None:
            continue
        if holds_point(box, x, y, _OVERLAY_HOST_TOLERANCE * 2):
            overlay.metadata["negation_overlay"] = {"outcome": "inline-math", "host": host.id}
            return


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
            candidates = ranked_latex_candidates(await self.recognizer.recognize(image_bytes))
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
        """Recognize one crop, unless the document already found the outage."""
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


async def _inspect_media(
    source_path: Path,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Runs ``media.inspect`` and degrades visibly when it fails.

    The inspection feeds the standalone-image heuristic and the presentation
    decision, and neither is required, so no failure of the step fails the
    job: any ``Exception`` (a ``ToolboxError``, but also an SDK bug or a client
    configuration error) makes the run continue without the signal, logs a
    warning and records the cause. Cancellation is not caught, since
    ``asyncio.CancelledError`` derives from ``BaseException``.

    Returns the inspection and the outcome for
    ``manifest.extractor.configuration``, since it runs before the manifest
    exists: ``media_inspection`` is ``toolbox``, ``disabled`` (by
    ``TOOLBOX_MEDIA_INSPECT_ENABLED``), ``source_missing`` or ``failed``, plus
    ``media_inspection_error`` on failure, and ``document_genre`` with its
    ``genre_signals`` when the Toolbox reports them.
    """
    from backend.config.settings import settings

    try:
        media_inspection = await inspect_source_media(source_path)
    except Exception as exc:  # noqa: BLE001 - the step degrades, never fails the job
        cause = f"{type(exc).__name__}: {exc}"
        logger.warning(
            t(LOG_MEDIA_INSPECT_FAILED).format(
                filename=source_path.name, error=cause
            )
        )
        return None, {"media_inspection": "failed", "media_inspection_error": cause}
    if media_inspection is not None:
        status = "toolbox"
    elif not settings.toolbox_media_inspect_enabled:
        status = "disabled"
    else:
        status = "source_missing"
    configuration: dict[str, Any] = {"media_inspection": status}
    if isinstance(media_inspection, dict) and media_inspection.get("document_genre"):
        configuration["document_genre"] = media_inspection["document_genre"]
        configuration["genre_signals"] = list(media_inspection.get("genre_signals") or [])
    return media_inspection, configuration


def _is_presentation(media_inspection: dict[str, Any] | None) -> bool:
    """Whether ``media.inspect`` reported a slide deck.

    A Toolbox older than pure-media-inspect 1.1.0 reports no genre, and a
    failed inspection reports nothing: both are treated as a document.
    """
    return (
        isinstance(media_inspection, dict)
        and media_inspection.get("document_genre") == "presentation"
    )


def _inject_full_page_picture(
    manifest: ProcessingManifest,
    media_inspection: dict[str, Any] | None,
) -> None:
    """Injeta um elemento `picture` sintético de página inteira.

    Quando a entrada é uma imagem raster isolada (``media_inspect`` classifica
    como imagem e sinaliza ``requires_visual_inspection=true``) e o extrator
    estrutural não produziu nenhum bloco visual (picture/formula), o orquestrador
    não teria alvo para audiodescrição. Este fallback cria um elemento `picture`
    que cobre a página inteira para que o VisionAgent descreva a imagem.

    O sinal é consumido apenas como heurística de enriquecimento: não altera o
    problema PDDL (predicados ``media_inspected``/``media_profile_classified``
    pertencem ao domínio da Toolbox).
    """
    if not isinstance(media_inspection, dict):
        return
    if not media_inspection.get("is_image"):
        return
    if not media_inspection.get("requires_visual_inspection"):
        return

    has_visual_element = any(
        element.type in {"picture", "formula"} for element in manifest.elements
    )
    if has_visual_element or any(
        is_unstructured_page_placeholder(element) for element in manifest.elements
    ):
        # An empty page is already planned for visual inspection.
        return

    max_reading_order = max(
        (element.reading_order for element in manifest.elements), default=0
    )
    page_number = (
        manifest.pages[0].page_number if manifest.pages else 1
    )

    element = ManifestElement(
        id=f"element-injected-picture-{len(manifest.elements) + 1:06d}",
        type="picture",
        raw_label="picture",
        reading_order=max_reading_order + 1,
        hierarchy_level=1,
        text=None,
        page_number=page_number,
        metadata={
            "injected_picture": True,
            "media_inspection": media_inspection,
        },
    )
    manifest.elements.append(element)

    if manifest.pages:
        manifest.pages[0].element_ids.append(element.id)

    observations, obligations = _derive_processing_needs([element])
    manifest.observations.extend(observations)
    manifest.obligations.extend(obligations)

    manifest.summary.element_count = len(manifest.elements)
    manifest.summary.observation_count = len(manifest.observations)
    manifest.summary.obligation_count = len(manifest.obligations)
    manifest.summary.element_types = dict(
        sorted(Counter(item.type for item in manifest.elements).items())
    )


async def _enrich_table_structures(
    manifest: ProcessingManifest,
    source_file: Path,
    *,
    status_callback: Callable[[str], Coroutine[Any, Any, None]] | None = None,
    breaker: ProviderBreaker | None = None,
) -> None:
    from backend.config.settings import settings

    table_elements, garbled = _tables_to_read(manifest)
    if not table_elements:
        return

    data_agent = DataAgent()
    breaker = breaker or ProviderBreaker(settings.vision_breaker_threshold)

    async def read_one(position: int, element: ManifestElement) -> bool:
        """Read one table from its image, or keep it as it is; True when enriched."""
        reason = garbled.get(element.id)
        if reason is None and _backfill_table_from_existing_text(element):
            return True

        fallback_page_number = element.page_number
        if fallback_page_number is None and len(manifest.pages) == 1:
            fallback_page_number = manifest.pages[0].page_number

        if status_callback:
            await status_callback(
                t(STAGE_RECOGNIZING_TABLE).format(
                    current=position,
                    total=len(table_elements),
                    pages=_pages_label([fallback_page_number], len(manifest.pages)),
                )
            )
        # The breaker is consulted before the crop: a provider the pictures
        # declared down must not cost one Toolbox render per remaining table.
        # The second pass calls this anyway for its probe, because the probe
        # is let through before any `read_one` sees the breaker.
        if breaker.open:
            if reason is not None:
                _keep_misread_table(
                    element,
                    fallback_page_number or 0,
                    reason,
                    breaker.skip_detail(),
                    _table_review_attempts(element, 0),
                )
            _record_table_read_failure(element, "model_failed")
            return False
        image_bytes, page_number = await run_blocking(
            _extract_picture_bytes,
            source_file,
            element,
            fallback_page_number,
            _source_artifact_id(manifest),
            manifest.source.media_type,
        )
        if not image_bytes:
            _record_table_read_failure(element, "crop_unavailable")
            if reason is not None:
                _keep_misread_table(
                    element, page_number, reason, "no image of the table",
                    _table_review_attempts(element, 0),
                )
            return False

        table_output, answered, why, attempt = await _read_table(
            data_agent, breaker, element, image_bytes, page_number, reason
        )
        if table_output is None:
            _record_unread_table(element, page_number, reason, answered, why, attempt)
            return False
        _fold_table_reading(element, table_output, page_number, reason, attempt)
        return True

    enriched = 0
    for position, element in enumerate(table_elements, start=1):
        enriched += await read_one(position, element)
    enriched += await _retry_failed(
        [
            (position, element)
            for position, element in enumerate(table_elements, start=1)
            if element.metadata.get("table_read_failure") == "model_failed"
        ],
        read_one,
        kind="tables",
        breaker=breaker,
    )

    if enriched:
        logger.info(t(LOG_PDDL_TABLES_ENRICHED).format(count=enriched))


def _tables_to_read(manifest: ProcessingManifest) -> tuple[list[ManifestElement], dict[str, str]]:
    """The tables to read from their image, and why each misread one is read again.

    A table without a usable structure is read. With ``TABLE_VISUAL_REVIEW``,
    so is a table read in the wrong shape (rows collapsed into one, cells
    doubled): it has structure but not the right one, and ``garbled`` maps
    its id to the reason (``table_garble_reason``).
    """
    from backend.config.settings import settings

    garbled: dict[str, str] = {}
    if settings.table_visual_review:
        for element in manifest.elements:
            if element.type == "table" and _table_element_has_structured_content(element):
                reason = table_garble_reason(
                    _rows_from_table_ast(element.metadata["table_ast"])
                )
                if reason:
                    garbled[element.id] = reason
    table_elements = [
        element
        for element in manifest.elements
        if element.type == "table"
        and (element.id in garbled or not _table_element_has_structured_content(element))
    ]
    return table_elements, garbled


async def _read_table(
    data_agent: DataAgent,
    breaker: ProviderBreaker,
    element: ManifestElement,
    image_bytes: bytes,
    page_number: int,
    reason: str | None,
) -> tuple[DataOutput | None, bool, str, int]:
    """Ask the data agent for a table: ``(reading, answered, why, attempts)``.

    A misread table (``reason``) gets a few readings: the model may drop
    columns or rows on one try and read the table whole on the next, and a
    reading that is not the same table read better is refused
    (``_table_reread_disqualified``). ``reading`` is ``None`` when none was
    kept; ``answered`` says whether the model answered at all, ``why`` why
    nothing was kept, and ``attempts`` how many readings were made.
    """
    attempts = _TABLE_REREAD_ATTEMPTS if reason is not None else 1
    table_output = None
    answered = False
    why = "no table was read"
    attempt = 0
    for attempt in range(1, attempts + 1):
        if breaker.open:
            why = breaker.skip_detail()
            attempt -= 1  # this try was not made
            break
        candidate = await data_agent.process_region(
            image_bytes=image_bytes,
            classification="table",
            page_num=page_number,
            fallback_text=element.text or "",
        )
        # The data agent returns None for any failure, an unusable answer
        # included, so the breaker may count one of those too.
        breaker.record(candidate is not None)
        answered = answered or isinstance(candidate, DataOutput)
        if not isinstance(candidate, DataOutput) or candidate.kind != "table":
            continue
        if reason is not None:
            why = _table_reread_disqualified(
                element.metadata["table_ast"], candidate.table_rows()
            )
            if why:
                continue
        table_output = candidate
        break
    return table_output, answered, why, attempt


def _record_unread_table(
    element: ManifestElement,
    page_number: int,
    reason: str | None,
    answered: bool,
    why: str,
    attempt: int,
) -> None:
    """Record that no reading of a table was kept.

    A reading refused as worse than the table, or an answer that it is not a
    table, is the model's answer; only no answer at all is a failure a rerun
    may not repeat. A misread table stays as it was, with why.
    """
    if answered:
        # The provider is up and answered; a failure an earlier pass
        # recorded on this element is no longer true.
        element.metadata.pop("table_read_failure", None)
    else:
        _record_table_read_failure(element, "model_failed")
    if reason is not None:
        _keep_misread_table(
            element, page_number, reason, why, _table_review_attempts(element, attempt)
        )


def _fold_table_reading(
    element: ManifestElement,
    table_output: DataOutput,
    page_number: int,
    reason: str | None,
    attempt: int,
) -> None:
    """Write a kept table reading into ``element``, keeping a replaced misread AST."""
    element.metadata.pop("table_read_failure", None)
    rows = table_output.table_rows()
    table_ast = table_output.table_ast()
    if reason is not None:
        element.metadata["table_ast_replaced"] = element.metadata["table_ast"]
        element.metadata["table_review"] = {
            "reason": reason, "outcome": "replaced",
            "attempts": _table_review_attempts(element, attempt),
        }
        logger.info(
            t(LOG_PDDL_TABLE_REREAD_ACCEPTED).format(
                element_id=element.id, page=page_number, reason=reason,
            )
        )

    element.metadata["table_ast"] = table_ast
    element.metadata["table_linearization_hint"] = "data-agent-structured"
    element.metadata["table_row_count"] = len(rows)
    element.metadata["table_column_count"] = table_ast_column_count(table_ast)
    element.metadata["table_has_header"] = any(
        cell.header or cell.scope != "none"
        for row in table_output.rows
        for cell in row.cells
    )
    element.metadata["data_language"] = table_output.language
    element.metadata["data_confidence"] = table_output.confidence
    if table_output.warnings:
        element.metadata["data_warnings"] = list(table_output.warnings)
    element.text = ""
    if element.page_number is None and page_number >= 1:
        element.page_number = page_number


#: Why a table was left unread, recorded in metadata["table_read_failure"]: the
#: crop could not be rendered, or the data agent returned no answer at all.
TableReadFailure = Literal["crop_unavailable", "model_failed"]


def _record_table_read_failure(element: ManifestElement, reason: TableReadFailure) -> None:
    """Mark ``element`` as a table no reading came back for, and say why."""
    element.metadata["table_read_failure"] = reason


def _table_review_attempts(element: ManifestElement, attempts: int) -> int:
    """How many readings a table has had, with ``attempts`` more.

    Every pass that reads a table again stores the count it made, so the
    metadata says how many readings the table got in total (3 on one pass, 1
    more on the next), not only the last pass's.
    """
    review = element.metadata.get("table_review")
    previous = review.get("attempts", 0) if isinstance(review, dict) else 0
    return previous + attempts


def _keep_misread_table(
    element: ManifestElement, page_number: int, reason: str, why: str, attempts: int
) -> None:
    """Record that a misread table stays as it was read, and why."""
    element.metadata["table_review"] = {
        "reason": reason, "outcome": "kept", "why": why, "attempts": attempts,
    }
    logger.warning(
        t(LOG_PDDL_TABLE_REREAD_REJECTED).format(
            element_id=element.id, page=page_number, reason=reason, why=why,
        )
    )


#: Share of the words two readings of a table must share, each way, for the
#: new one to replace the misread one: it is the same table read better, so
#: most of its words were there, misplaced (a crop of the wrong region, or an
#: invented table, shares few), and it must keep most of the misread one's
#: words (on 006.pdf the model once returned only the header row).
_TABLE_REREAD_MIN_SHARED = 0.5

#: Readings asked for a misread table before it is kept as it is.
_TABLE_REREAD_ATTEMPTS = 3

_TABLE_WORD = re.compile(r"\w{2,}")


def _table_reread_disqualified(
    misread_ast: dict[str, Any], rows: list[list[str]]
) -> str | None:
    """Why a new reading of a misread table must not replace it, or None."""
    reason = table_garble_reason(rows)
    if reason:
        return f"the new reading is misread too: {reason}"
    misread_rows = _rows_from_table_ast(misread_ast)
    width = max((len(row) for row in rows), default=0)
    misread_width = max((len(row) for row in misread_rows), default=0)
    if width < misread_width:
        return f"the new reading has {width} column(s), the table {misread_width}"
    words = {word for row in rows for cell in row for word in _TABLE_WORD.findall(cell.casefold())}
    if not words:
        return "the new reading has no text"
    misread = {
        word for row in misread_rows for cell in row for word in _TABLE_WORD.findall(cell.casefold())
    }
    shared = len(words & misread) / len(words)
    if shared < _TABLE_REREAD_MIN_SHARED:
        return f"only {shared:.0%} of its words are in the table it would replace"
    kept = len(words & misread) / len(misread) if misread else 1.0
    if kept < _TABLE_REREAD_MIN_SHARED:
        return f"it keeps only {kept:.0%} of the words of the table it would replace"
    return None


def _backfill_table_from_existing_text(element: ManifestElement) -> bool:
    text = (element.text or "").strip()
    if not text:
        return False

    rows = rows_from_visual_table_text(text)
    if not rows:
        return False

    table_ast = _table_ast_from_rows(rows)
    if table_ast is None:
        return False

    element.metadata["table_ast"] = table_ast
    element.metadata["table_linearization_hint"] = "text-heuristic"
    element.metadata["table_row_count"] = len(rows)
    element.metadata["table_column_count"] = max((len(row) for row in rows), default=0)
    element.metadata["table_has_header"] = bool(rows and len(rows[0]) >= 2)
    element.text = ""
    return True


#: Longest side of a picture crop sent to the vision model. The render runs at
#: 160 dpi and the Toolbox refuses more than 20 MP, so an unbounded crop of a
#: large standalone image (its page is sized in pixels) is rejected before the
#: model sees it. Bounding the side keeps every source renderable, and the
#: vision model's 8192-token slot would downscale it further anyway.
_PICTURE_MAX_SIDE = 2000

#: Largest image decoded from a picture's embedded ``src``. A DOCX or HTML
#: image is the author's file, not a bounded render, so an oversized one is
#: left undescribed instead of being held in memory and sent to the model.
_EMBEDDED_PICTURE_MAX_BYTES = 20 * 1024 * 1024

#: Embedded image types sent to the vision model as they are: the raster
#: formats the providers read (and that ``pdf.render`` also accepts as input).
#: A vector image (SVG) is not something the model can be shown.
_EMBEDDED_PICTURE_TYPES = frozenset({"image/png", "image/jpeg", "image/jpg"})


def _extract_picture_bytes(
    source_file: Path,
    element: ManifestElement,
    fallback_page_number: int | None,
    artifact_id: str | None = None,
    media_type: str | None = None,
) -> tuple[bytes | None, int]:
    """The picture's box rendered by the Toolbox, or its whole page.

    A box the Toolbox refuses (outside the page) or a sliver of one is not a
    picture, so the page is described instead. Any other failure, the Toolbox
    being unavailable included, is not retried with the page: it is logged
    with its cause and the element is left without an image.

    A picture with no page (a DOCX or HTML source) has nothing to render; its
    image is the one the extraction embedded in it, if any, returned with
    page ``0``.
    """
    from acessilia_sdk.toolbox import ToolboxCapabilityError, ToolboxIncompatibleEndpoint

    provenance = element.provenance[0] if element.provenance else None
    page_number = provenance.page_number if provenance is not None else (fallback_page_number or 0)
    if page_number < 1:
        image = decode_data_uri(
            element.metadata.get("src"),
            media_types=_EMBEDDED_PICTURE_TYPES,
            max_bytes=_EMBEDDED_PICTURE_MAX_BYTES,
        )
        return image, 0

    def render(clip=None, origin: ClipOrigin = "TOPLEFT") -> RenderedPage:
        return _toolbox_render(
            source_file, page_number, media_type=media_type, dpi=160,
            max_side=_PICTURE_MAX_SIDE, clip=clip,
            clip_origin=origin, artifact_id=artifact_id,
        )

    clip, origin = best_effort_clip(provenance.bbox if provenance is not None else None)
    try:
        if clip is None:
            return render().image, page_number
        try:
            page = render(clip, origin)
        except ToolboxIncompatibleEndpoint:
            raise
        except ToolboxCapabilityError:
            # The Toolbox refuses (HTTP 400) a box that does not intersect the page.
            return render().image, page_number
        left, top, right, bottom = page.clip
        if right - left < 4 or bottom - top < 4:
            return render().image, page_number
        return page.image, page_number
    except Exception:
        logger.exception(
            t(LOG_PDDL_ELEMENT_CROP_FAILED).format(element_id=element.id)
        )
        return None, page_number


def _plan_progress(
    manifest: ProcessingManifest,
    status_callback: Callable[[str], Coroutine[Any, Any, None]] | None,
    loop: asyncio.AbstractEventLoop,
) -> StepProgress | None:
    """Report each obligation step, with its pages, through ``status_callback``.

    The executor runs on a worker thread while the callback is a coroutine of
    the event loop, so the report is scheduled on ``loop`` and awaited from the
    thread: the step only starts once its stage is recorded, which is what lets
    a job killed mid-step still say which step and page it was on. A failing
    report, including a broken translation of the label, is logged and never
    fails the step.

    The user sees only the step and its pages; the obligation kind and method
    are internal names, so they go to the debug log.
    """
    if status_callback is None:
        return None
    page_by_element = {element.id: element.page_number for element in manifest.elements}
    pages_by_obligation = {
        obligation.id: [page_by_element.get(target) for target in obligation.target_ids]
        for obligation in manifest.obligations
    }

    def report(step: PlanStep, position: int, total: int) -> None:
        if step.action != "execute-obligation" or step.obligation_id is None:
            return
        pages = pages_by_obligation.get(step.obligation_id, [])
        logger.debug(
            "PDDL: step {}/{} {} via {}, pages {}",
            position,
            total,
            step.obligation_id,
            step.method,
            pages,
        )
        try:
            message = t(STAGE_EXECUTING_PLAN_STEP).format(
                current=position,
                total=total,
                pages=_pages_label(pages, len(manifest.pages)),
            )
            asyncio.run_coroutine_threadsafe(status_callback(message), loop).result(
                timeout=_PROGRESS_REPORT_TIMEOUT_SECONDS
            )
        except Exception as exc:  # noqa: BLE001 - progress must not fail the plan
            logger.warning("PDDL: progress of step {} not recorded: {}", position, exc)

    return report


#: Upper bound on how long a plan step waits for its progress to be recorded.
_PROGRESS_REPORT_TIMEOUT_SECONDS = 10.0


def _log_availability(availability: toolbox_gate.AvailabilityDecision) -> None:
    if not availability.blocked:
        return
    blocked = "; ".join(
        f"{method}: {', '.join(reasons)}"
        for method, reasons in availability.blocked.items()
    )
    if availability.enforced:
        logger.warning(
            "Gate da Toolbox (catálogo {}): métodos fora do plano — {}",
            availability.catalog_revision or "indisponível",
            blocked,
        )
    else:
        logger.warning(
            "Gate da Toolbox em observação (catálogo {}): removeria — {}",
            availability.catalog_revision or "indisponível",
            blocked,
        )
