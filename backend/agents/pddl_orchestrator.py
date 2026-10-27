from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import os
import re
import tempfile
from collections import Counter
from collections.abc import Callable, Coroutine, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from docstruct.blocks.callouts import dedupe_callout_titles as _dedupe_callout_titles
from docstruct.fusion.similarity import PAGENUM_RE
from docstruct.fusion.tailjoin import is_page_number as _is_page_number
from docstruct.geometry import reading_role
from docstruct.tables.ast import (
    effective_section_width,
    linearize_table_for_text,
    raw_rows_from_table_ast as _rows_from_table_ast,
)
from docstruct.tables.garble import table_garble_reason
from docstruct.text.inline_math import TextSpan, detect_inline_math, splice_inline_math
from docstruct.text.latex import has_latex_markup, latex_text_agreement
from docstruct.text.norm_fix import norm_fix
from docstruct.text.negation_overlay import (
    compose_negation,
    is_detached_overlay,
    locate_in_grid,
    locate_in_text,
    negates,
)
from docstruct.text.unicode_repair import (
    Detection,
    UnicodeRepairContext,
    detect_legacy_unicode,
    repair_legacy_unicode,
)

from backend.services.blocking import run_blocking
from backend.agents.data_agent import DataAgent
from backend.agents.output_schemas import DataOutput, PageInspectionOutput, VisionOutput
from backend.agents.vision_agent import VisionAgent
from backend.core.agents.fusion_agent import FusionAgent
from backend.core.agents.informational_structural import InformationalStructuralAgent
from backend.core.execution.executor import ExecutorAgent, MethodRegistry, StepProgress
from backend.core.execution.models import ExecutionReport, MethodResult
from backend.core.execution.messages import EXE_COMPLETED_OBLIGATIONS_UNSATISFIED
from backend.core.manifest.builder import (
    SECONDARY_EXTRACTION_KIND,
    _derive_processing_needs,
    is_unstructured_page_placeholder,
    reconcile_reclassified_element_processing_needs,
    unicode_repair_text,
)
from backend.core.manifest.models import (
    Artifact,
    ManifestElement,
    Obligation,
    PageDescriptor,
    ProcessingManifest,
    is_bottom_left,
)
from backend.core.manifest.toolbox_extractor import ToolboxManifestExtractor
from backend.core.planning.domain_bundle import DomainBundle
from backend.core.planning.models import NominalPlan, PlanningComparison, PlanStep
from backend.core.planning import toolbox_gate
from backend.core.planning.planner_agent import PlannerAgent
from backend.i18n import locale_for_user, n, reset_request_locale, set_request_locale, t
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
    STAGE_PAGE,
    STAGE_PAGE_OF,
    STAGE_PAGES,
    STAGE_PAGE_UNKNOWN,
)
from backend.tools.code_tools import normalize_code_text
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

if TYPE_CHECKING:
    from acessilia_sdk.toolbox.clients.pdf import ClipOrigin, RenderedPage

#: Canonical English msgid for the alt text of a picture the vision model left
#: undescribed; why it was left so goes to the operator, not the reader.
MSG_UNDESCRIBED_PICTURE_ALT: str = "Image without a text description."

#: Canonical English msgid for an institutional header read as one paragraph:
#: the logo, then its header lines; {lines} is substituted by callers after lookup.
MSG_LETTERHEAD_TEXT: str = "Logo. {lines}."

#: Canonical English singular/plural msgids for the document's warning on the
#: pictures and tables a failure left without a description or a reading.
MSG_PICTURES_NOT_DESCRIBED: tuple[str, str] = (
    "{count} image could not be described.",
    "{count} images could not be described.",
)
MSG_TABLES_NOT_READ: tuple[str, str] = (
    "{count} table could not be read.",
    "{count} tables could not be read.",
)


def _formula_elements_for_obligation(
    manifest: ProcessingManifest, obligation_id: str
) -> list[ManifestElement]:
    obligation = next(
        (o for o in manifest.obligations if o.id == obligation_id), None
    )
    if obligation is None:
        return []
    targets = set(obligation.target_ids)
    return [
        el for el in manifest.elements if el.id in targets and el.type == "formula"
    ]


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
    for element in elements:
        latex = normalize_latex(element.text or "")
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
    for element in elements:
        latex = normalize_latex(element.text or "")
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


def _run_extract_fused(
    source_path: Path, *, artifact_id: str | None = None
) -> dict:
    """Executa ``extract_fused`` respeitando o contexto de event loop.

    Detecta a presença de um event loop **antes** de criar a coroutine,
    evitando criar um objeto coroutine que ficaria sem ``await`` (e
    produziria ``RuntimeWarning: coroutine ... was never awaited``).

    Nota de arquitetura: quando chamado a partir de um thread com event
    loop ativo (Agno Workflow, API), ``.result()`` ainda bloqueia o loop
    chamador até a fusão terminar. O contrato dos handlers permanece
    síncrono; quem invoca o executor a partir de código async deve rodar
    o executor inteiro via ``await run_blocking(...)`` para não
    bloquear o event loop principal.
    """
    import concurrent.futures

    from backend.pipeline.fusion import extract_fused

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # Contexto síncrono (executor determinístico, CLI, testes):
        # não existe event loop ativo neste thread.
        return asyncio.run(extract_fused(source_path, artifact_id=artifact_id))

    # Já existe um event loop neste thread; como o handler é síncrono,
    # a coroutine é executada em um thread dedicado com seu próprio loop.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(
            lambda: asyncio.run(
                extract_fused(source_path, artifact_id=artifact_id)
            )
        ).result()


def _fusion_agent() -> FusionAgent:
    """Fusion agent used to reach the deterministic fusion primitives.

    The `docstruct` functions take classified blocks, counters and tuning
    parameters; `FusionAgent.process_*` is the in-repo entry point that supplies
    them, so handlers call that instead of a primitive whose signature they would
    otherwise have to guess.
    """
    return FusionAgent()


def _element_bbox(
    element: ManifestElement,
    manifest: ProcessingManifest,
) -> tuple[float, float, float, float] | None:
    """Element bounding box normalized to the unit page expected by docstruct."""
    for item in element.provenance:
        box = getattr(item, "bbox", None)
        if box is None:
            continue
        page = next(
            (
                page
                for page in manifest.pages
                if page.page_number == item.page_number
            ),
            None,
        )
        if page is None or not page.width or not page.height:
            return None
        top, bottom = box.top, box.bottom
        if is_bottom_left(box.coord_origin, top, bottom):
            top, bottom = page.height - top, page.height - bottom
        return (
            box.left / page.width,
            top / page.height,
            box.right / page.width,
            bottom / page.height,
        )
    return None


def _target_elements(
    manifest: ProcessingManifest, obligation_id: str
) -> list[ManifestElement]:
    """Elements an obligation points at, in reading order."""
    obligation = next(
        (o for o in manifest.obligations if o.id == obligation_id), None
    )
    if obligation is None:
        return []
    targets = set(obligation.target_ids)
    return sorted(
        (el for el in manifest.elements if el.id in targets),
        key=lambda el: el.reading_order,
    )


def _missing_obligation(obligation_id: str) -> MethodResult:
    return MethodResult(
        success=False,
        validated=False,
        message=f"Obrigação não encontrada: {obligation_id}",
    )


def _handle_vision_description_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Require every picture target to already carry a description.

    The description itself is produced before planning (`_enrich_picture_descriptions`
    asks the vision model), so this method validates that the work the planner is
    asking for actually happened instead of pretending to perform it. A picture
    that is still undescribed is a real failure and keeps the next admissible
    method available; `describe-image` is non-critical, so it does not fail the job.
    """
    elements = [
        el
        for el in _target_elements(manifest, obligation_id)
        if el.type == "picture"
    ]
    if not elements:
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhuma imagem encontrada para a obrigação",
        )

    undescribed = [
        el for el in elements
        if not (
            bool((el.text or "").strip())
            if el.metadata.get("vision_description_complete")
            else _has_meaningful_text(el)
        )
    ]
    if undescribed:
        return MethodResult(
            success=False,
            validated=False,
            message=(
                "Imagem sem descrição textual: "
                + ", ".join(
                    f"{el.id} ({reason})"
                    if (reason := el.metadata.get("vision_failure_reason"))
                    else el.id
                    for el in undescribed
                )
            ),
        )
    return MethodResult(
        success=True,
        validated=True,
        message=f"Descrição validada para {len(elements)} imagem(ns)",
    )


def _handle_pandoc_table_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Require the table targets to carry a structured AST."""
    elements = [
        el for el in _target_elements(manifest, obligation_id) if el.type == "table"
    ]
    if not elements:
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhuma tabela encontrada para a obrigação",
        )

    missing = []
    for element in elements:
        try:
            usable = _table_element_has_structured_content(element)
            table_ast = element.metadata.get("table_ast")
            if usable:
                usable = any(
                    value.strip() for row in _rows_from_table_ast(table_ast) for value in row
                )
                linearize_table_for_text({"table_ast": table_ast})
        except (TypeError, ValueError, AttributeError):
            usable = False
        if not usable:
            missing.append(element)
    if missing:
        return MethodResult(
            success=False,
            validated=False,
            message=(
                "Tabela sem estrutura tabular: "
                + ", ".join(el.id for el in missing)
            ),
        )
    return MethodResult(
        success=True,
        validated=True,
        message=f"Estrutura tabular validada para {len(elements)} tabela(s)",
    )


def _handle_pandoc_code_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Normalize code targets in place and record the normalized language."""
    elements = [
        el for el in _target_elements(manifest, obligation_id) if el.type == "code"
    ]
    if not elements:
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhum bloco de código encontrado para a obrigação",
        )

    normalized = 0
    for element in elements:
        text = normalize_code_text(element.text or "")
        if not text:
            continue
        element.text = text
        element.metadata["code_normalized"] = True
        normalized += 1

    if normalized != len(elements):
        return MethodResult(
            success=False,
            validated=False,
            message=(
                f"Código normalizado em {normalized}/{len(elements)} bloco(s)"
            ),
        )
    return MethodResult(
        success=True,
        validated=True,
        message=f"Código normalizado em {normalized} bloco(s)",
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


def _handle_norm_fix_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Apply the deterministic text cleanups (ligatures, hyphenation, NBSP)."""
    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)

    fixed = 0
    for element in elements:
        current = element.text or ""
        if not current:
            continue
        cleaned = norm_fix(current)
        if cleaned != current:
            element.text = cleaned
            element.metadata["norm_fixed"] = True
        fixed += 1

    if not fixed:
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhum texto elegível para normalização",
        )
    return MethodResult(
        success=True,
        validated=True,
        message=f"Normalização determinística aplicada em {fixed} elemento(s)",
    )


#: Manifest element type -> block type accepted by the Unicode repair. Types
#: absent here (formula, code, table, picture) are never rewritten.
_UNICODE_REPAIR_BLOCK_TYPES = {
    "paragraph": "prose",
    "heading": "heading",
    "title": "heading",
    "list_item": "prose",
    "caption": "prose",
    "footnote": "prose",
    "page_header": "prose",
    "page_footer": "prose",
}

#: Sections of a table AST whose cells carry text.
_TABLE_SECTIONS = ("header", "body", "footer")

#: Word-internal spaced accents needed before standalone ones (an accent
#: separated from its word) are treated as the same extraction defect. A
#: document that merely mentions an accent has none of the word-internal shape,
#: so it keeps its text; a legacy TeX extraction has hundreds.
_UNICODE_STANDALONE_SPACING_MIN = 5


def _repair_table_cells(
    element: ManifestElement, context: UnicodeRepairContext
) -> tuple[bool, set[str], int, bool]:
    """Repair a table caption and every cell in place.

    Returns ``(edited, rules, edits, needs_review)``. The table keeps its
    structure; only the text of the caption and of the cells changes.
    """
    table_ast = element.metadata.get("table_ast")
    if not isinstance(table_ast, dict):
        return False, set(), 0, False

    edited = False
    rules: set[str] = set()
    edits = 0
    review = False

    def repair_text(current: str) -> str:
        nonlocal edited, edits, review
        decision = repair_legacy_unicode(current, context=context)
        if decision.repaired != current:
            edited = True
        rules.update(edit.rule for edit in decision.edits)
        edits += len(decision.edits)
        review = review or decision.needs_review
        return decision.repaired

    caption = table_ast.get("caption")
    if isinstance(caption, str) and caption:
        table_ast["caption"] = repair_text(caption)
    for section_name in _TABLE_SECTIONS:
        section = table_ast.get(section_name)
        if not isinstance(section, list):
            continue
        for row in section:
            if not isinstance(row, dict):
                continue
            cells = row.get("cells")
            if not isinstance(cells, list):
                continue
            for cell in cells:
                if not isinstance(cell, dict):
                    continue
                text = cell.get("text")
                if isinstance(text, str) and text:
                    cell["text"] = repair_text(text)
    return edited, rules, edits, review


#: Slack, in PDF points, when finding the element a negation slash lies in.
_OVERLAY_HOST_TOLERANCE = 1.5
#: A text line is about this many slash heights tall (glyph plus leading).
_OVERLAY_LINE_HEIGHTS = 1.25


def _bbox(element: ManifestElement, page: int | None = None) -> tuple[int, Any] | None:
    """``(page, box)`` of the element: on ``page`` when given, else the first boxed one.

    An element can carry provenances on more than one page; a slash is only
    compared with the part of an element that lies on the slash's own page.
    """
    for provenance in element.provenance or []:
        if provenance.bbox is not None and page in (None, provenance.page_number):
            return provenance.page_number, provenance.bbox
    return None


def _vertical(box: Any) -> tuple[float, float]:
    """``(upper, lower)`` edges in a downward axis, whatever the box's origin."""
    if box.coord_origin == "BOTTOMLEFT":
        return -box.top, -box.bottom
    return min(box.top, box.bottom), max(box.top, box.bottom)


def _table_grid(element: ManifestElement) -> list[list[tuple[str, dict[str, Any] | None]]]:
    """The table's rows on its visual column grid: a cell spanning ``n`` columns
    takes ``n`` slots, its text in the first, so a slash's column position
    matches the cell under it. Row spans are not expanded (the slash's row is
    estimated from the AST rows), and every column is taken as equally wide —
    the AST carries no widths; ``locate_in_grid``'s margin refuses close calls.
    """
    table_ast = element.metadata.get("table_ast")
    if not isinstance(table_ast, dict):
        return []
    grid: list[list[tuple[str, dict[str, Any] | None]]] = []
    for section in _TABLE_SECTIONS:
        for row in table_ast.get(section) or []:
            if not isinstance(row, dict):
                continue
            slots: list[tuple[str, dict[str, Any] | None]] = []
            for cell in row.get("cells") or []:
                if not isinstance(cell, dict):
                    continue
                span = max(1, int(cell.get("colspan") or 1))
                slots.append((str(cell.get("text") or ""), cell))
                slots.extend(("", None) for _ in range(span - 1))
            grid.append(slots)
    return grid


def _reattach_negation_overlays(manifest: ProcessingManifest) -> dict[str, int]:
    """Give each detached ``≠`` slash back to the relation it negates.

    A legacy TeX text layer may extract the slash TeX lays over ``=`` as its own
    element (``U+0338`` alone), leaving ``h = 0`` where the page says
    ``h ≠ 0``. The slash's box is the only link back: the element containing it
    is found on the same page, the slash's position inside it is estimated, and
    ``docstruct.text.negation_overlay`` picks the relation only when the choice
    is unambiguous — composing the wrong ``=`` would invert a true statement.
    A formula whose text is already LaTeX (recognized, #253) is not touched.

    Every slash element is then left out of the payload (``negation_overlay``
    metadata, with the outcome: ``composed``, ``host-is-latex``, ``ambiguous``,
    ``no-candidate``, ``ambiguous-host`` or ``no-host``), since a lone
    combining mark says nothing to a reader. A slash already recorded is
    skipped, so running the handler again (a plan retry) keeps the first
    outcome instead of re-reading a host whose text it already changed.
    Returns the count per outcome.

    This runs only with the repair obligation (``LEGACY_UNICODE_REPAIR=repair``).
    ``detect`` keeps its meaning — report, deliver as extracted — so there the
    slash elements stay in the outputs, like every other legacy artifact.
    """
    outcomes: dict[str, int] = {}
    overlays = [
        element
        for element in manifest.elements
        if is_detached_overlay(element.text) and "negation_overlay" not in element.metadata
    ]
    for overlay in overlays:
        located = _bbox(overlay)
        outcome, host_id = "no-host", None
        if located is not None:
            page, box = located
            x = (box.left + box.right) / 2
            upper, lower = _vertical(box)
            y = (upper + lower) / 2
            slash_height = (lower - upper) or 12.0
            hosts = []
            for element in manifest.elements:
                if element is overlay or is_detached_overlay(element.text):
                    continue
                other = _bbox(element, page)
                if other is None:
                    continue
                top, bottom = _vertical(other[1])
                if (
                    other[1].left - _OVERLAY_HOST_TOLERANCE <= x <= other[1].right + _OVERLAY_HOST_TOLERANCE
                    and top - _OVERLAY_HOST_TOLERANCE <= y <= bottom + _OVERLAY_HOST_TOLERANCE
                ):
                    hosts.append((element, other[1], top, bottom))
            if len(hosts) > 1:
                outcome = "ambiguous-host"
            elif hosts:
                host, host_box, top, bottom = hosts[0]
                host_id = host.id
                height = max(bottom - top, 1e-6)
                width = max(host_box.right - host_box.left, 1e-6)
                # The host tolerance lets a slash sit just outside the box:
                # clamp once, so the text and the grid paths see the same span.
                y_fraction = min(max((y - top) / height, 0.0), 1.0)
                x_fraction = min(max((x - host_box.left) / width, 0.0), 1.0)
                outcome = _compose_in_host(host, x_fraction, y_fraction, height, slash_height)
                if outcome == "composed":
                    host.metadata["negation_overlays"] = host.metadata.get("negation_overlays", 0) + 1
        overlay.metadata["negation_overlay"] = {"outcome": outcome, "host": host_id}
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    if outcomes:
        logger.info("Detached negation slashes: {}", outcomes)
    return outcomes


def _compose_in_host(
    host: ManifestElement,
    x_fraction: float,
    y_fraction: float,
    height: float,
    slash_height: float,
) -> str:
    """Negate the relation under the slash in ``host``; returns the outcome."""
    if host.type == "table":
        grid = _table_grid(host)
        if not any(negates(char) for row in grid for text, _ in row for char in text):
            return "no-candidate"
        columns = max((len(row) for row in grid), default=0)
        found = locate_in_grid(
            [[text for text, _ in row] for row in grid],
            row_position=y_fraction * len(grid),
            column_position=x_fraction * columns,
        )
        if found is None:
            return "ambiguous"
        row, column, index = found
        cell = grid[row][column][1]
        if cell is None:
            return "ambiguous"
        cell["text"] = compose_negation(str(cell["text"]), index)
        return "composed"
    if host.type == "formula" and has_latex_markup(host.text):
        return "host-is-latex"
    text = host.text or ""
    if not any(negates(char) for char in text):
        return "no-candidate"
    lines = max(1, round(height / (slash_height * _OVERLAY_LINE_HEIGHTS)))
    index = locate_in_text(
        text, lines=lines, line_position=y_fraction * lines, x_fraction=x_fraction
    )
    if index is None:
        return "ambiguous"
    host.text = compose_negation(text, index)
    return "composed"


def _handle_unicode_repair_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Repair legacy Unicode: NFD, dotless i, spacing diacritics, the crase and split ligatures.

    Only selected, prose-like elements are touched. Word-internal spacing
    accents are repaired whenever the element shows them; standalone accents
    are only repaired when the document has enough word-internal evidence
    (recorded in the manifest observation). The decision metadata records the
    edits and keeps ``needs_review`` for signals that remain, without copying
    the whole text into the manifest.
    """
    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)

    # Before the per-element repair, so the reattached ``≠`` is in the text
    # the repair reads, and the slash elements are not counted for review.
    _reattach_negation_overlays(manifest)

    language = manifest.language or "pt-BR"
    eligible: list[tuple[ManifestElement, str]] = []
    detections: dict[str, Detection] = {}
    for element in elements:
        text = unicode_repair_text(element)
        if not text or is_detached_overlay(element.text):
            continue
        if element.type == "table":
            block_type = "table"
        else:
            block_type = _UNICODE_REPAIR_BLOCK_TYPES.get(element.type)
            if block_type is None:
                continue
        eligible.append((element, block_type))
        detections[element.id] = detect_legacy_unicode(text)

    if not eligible:
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhum texto elegível para reparo Unicode",
        )

    # The threshold is document-level. The builder emits one obligation for all
    # eligible elements, and records the count in its observation; read it from
    # there so a future split of the obligation cannot change the decision.
    observation = next(
        (
            item
            for item in getattr(manifest, "observations", [])
            if item.kind == "repair-legacy-unicode-detected"
        ),
        None,
    )
    if observation is not None and "spacing_word_internal" in observation.evidence:
        word_internal = int(observation.evidence["spacing_word_internal"])
    else:
        word_internal = sum(
            detection.spacing_word_internal for detection in detections.values()
        )
    allow_standalone = word_internal >= _UNICODE_STANDALONE_SPACING_MIN
    inspected = len(eligible)
    repaired = 0
    review = 0
    for element, block_type in eligible:
        detection = detections[element.id]
        original = element.text or ""
        # A word-internal spacing accent (``C´ alculo``) is legacy extraction
        # evidence. Standalone accents (separated from their word) are only
        # included when the document has enough of the word-internal shape;
        # the lib never touches protected spans. The crase and split-ligature
        # rules rest on that same document-level evidence alone: an element
        # may carry ``` a`` or ``fi ca`` without any spaced accent of its own.
        allow_spacing = detection.spacing_diacritics > 0
        context = UnicodeRepairContext(
            language=language,
            block_type="prose" if block_type == "table" else block_type,
            page=element.page_number,
            allow_spacing_diacritics=allow_spacing,
            allow_standalone_spacing_diacritics=allow_spacing and allow_standalone,
            allow_legacy_tex_artifacts=allow_standalone,
        )
        if block_type == "table":
            edited, rules, edits, needs_review = _repair_table_cells(
                element, context
            )
            if edited:
                repaired += 1
            if needs_review:
                review += 1
            element.metadata["unicode_repair"] = {
                "edited": edited,
                "rules": sorted(rules),
                "edits": edits,
                "needs_review": needs_review,
                "confidence": None,
            }
            continue
        decision = repair_legacy_unicode(original, context=context)
        if decision.repaired != original:
            element.text = decision.repaired
            repaired += 1
        element.metadata["unicode_repair"] = {
            "edited": decision.repaired != original,
            "rules": sorted({edit.rule for edit in decision.edits}),
            "edits": len(decision.edits),
            "needs_review": decision.needs_review,
            "confidence": decision.confidence,
        }
        if decision.needs_review:
            review += 1
    return MethodResult(
        success=True,
        validated=True,
        message=(
            f"Reparo Unicode aplicado em {repaired}/{inspected} elemento(s); "
            f"{review} para revisão"
        ),
    )


def _render_inspection_region(
    source: Path,
    element: ManifestElement,
    *,
    media_type: str | None = None,
    artifact_id: str | None = None,
) -> tuple[bytes, int, list[float]]:
    """Render only the requested, validated source region on the Toolbox.

    Crop metadata from the extractor is never trusted: the page identity and
    the box are checked here, and the Toolbox renders exactly that box and
    reports the region it applied. The page range is the document's, as the
    Toolbox reports it, like every other render: a page beyond it is refused
    there. An element without a page is accepted only in a one-page document.
    """
    provenance = element.provenance[0] if element.provenance else None
    number = provenance.page_number if provenance else element.page_number
    if provenance and element.page_number is not None and number != element.page_number:
        raise ValueError("Region page identity is inconsistent")
    if number is not None and (type(number) is not int or number < 1):
        raise ValueError("Region page is missing or out of range")
    clip: tuple[float, float, float, float] | None = None
    origin: ClipOrigin = "TOPLEFT"
    bbox = provenance.bbox if provenance else None
    if bbox is not None:
        values = (bbox.left, bbox.top, bbox.right, bbox.bottom)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Region coordinates must be finite")
        # Unlike ordering, a crop certifies what the vision model describes,
        # so it requires an explicit origin instead of inferring one.
        if bbox.coord_origin not in {"TOPLEFT", "BOTTOMLEFT"}:
            raise ValueError("Region coordinate origin is unknown")
        clip, origin = values, bbox.coord_origin
    page = _toolbox_render(
        source, number or 1, media_type=media_type, dpi=160, clip=clip,
        clip_origin=origin, artifact_id=artifact_id,
    )
    if number is None and page.page_count != 1:
        raise ValueError("Region page is missing or out of range")
    return page.image, number or 1, list(page.clip)

def _inspect_region(image: bytes, number: int, total_pages: int, mode: str) -> VisionOutput | None:
    async def inspect():
        return await VisionAgent(mode=mode).describe_region(
            image_bytes=image, classification="embedded_image", page_num=number,
            total_pages=total_pages, mode=mode, full_budget=True,
        )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(inspect())
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(inspect())).result()


def _save_region_artifact(content: bytes, scope: str, kind: str, suffix: str, media_type: str) -> Artifact:
    from backend.config.settings import settings

    digest = hashlib.sha256(content).hexdigest()
    path = settings.data_dir / "artifacts" / "regions" / scope / f"{digest}.{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return Artifact(
        id=f"artifact-{kind}-{scope[:16]}-{digest[:16]}", kind=kind,
        path=str(path), media_type=media_type, sha256=digest,
    )


def _handle_pymupdf_region_method(manifest: ProcessingManifest, obligation_id: str) -> MethodResult:
    """Inspect real source pixels and update targets only after every result validates."""
    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)
    try:
        source = Path(manifest.source.path)
        with source.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != manifest.source.sha256:
                raise ValueError("Region source differs from the manifest")
        inspected = []
        for element in elements:
            if element.type != "unknown":
                raise ValueError("Region inspection requires an unknown target element")
            image, number, rectangle = _render_inspection_region(
                source,
                element,
                media_type=manifest.source.media_type,
                artifact_id=_source_artifact_id(manifest),
            )
            declared_pages = {
                page.page_number for page in manifest.pages if element.id in page.element_ids
            }
            if declared_pages and declared_pages != {number}:
                raise ValueError("Region page differs from the manifest page index")
            output = _inspect_region(
                image, number, max(len(manifest.pages), number),
                str(manifest.extractor.configuration.get("region_inspection_mode", "medio")),
            )
            if not isinstance(output, VisionOutput):
                raise ValueError(f"Region inspection failed for {element.id}")
            output = VisionOutput.model_validate(output.model_dump())
            text = output.description if output.kind == "description" else normalize_latex(output.formula_latex or "")
            if not text.strip():
                raise ValueError(f"Region inspection returned empty content for {element.id}")
            inspected.append((element, image, number, rectangle, output, text))

        artifacts = []
        replacements = {}
        for element, image, number, rectangle, output, text in inspected:
            scope = hashlib.sha256(json.dumps([
                manifest.manifest_id, manifest.source.sha256, manifest.revision, obligation_id, element.id,
            ]).encode()).hexdigest()
            crop = _save_region_artifact(image, scope, "region-crop", "png", "image/png")
            evidence = {
                "source_sha256": manifest.source.sha256, "element_id": element.id,
                "page_number": number, "bbox": rectangle, "crop_sha256": crop.sha256,
                "result": output.model_dump(),
            }
            record = _save_region_artifact(
                json.dumps(evidence, ensure_ascii=False, sort_keys=True).encode(),
                scope, "region-inspection", "json", "application/json",
            )
            replacement = element.model_copy(deep=True)
            replacement.metadata.update(
                original_type=element.type, vision_description_complete=True,
                vision_language=output.language, vision_confidence=output.confidence,
                vision_warnings=output.warnings, region_crop=crop.path,
                region_inspection=record.id,
            )
            replacement.text = text
            replacement.type = "formula" if output.kind == "formula" else "picture"
            if replacement.type == "picture":
                replacement.metadata["src"] = (
                    "data:image/png;base64," + base64.b64encode(image).decode("ascii")
                )
            replacement.raw_label = replacement.type
            replacement.page_number = number
            replacements[element.id] = replacement
            artifacts.extend([crop, record])
        manifest.elements = [replacements.get(element.id, element) for element in manifest.elements]
        manifest.summary.element_types = dict(Counter(element.type for element in manifest.elements))
        return MethodResult(
            success=True, validated=True,
            message=f"Inspected {len(elements)} source region(s)", artifacts=artifacts,
        )
    except Exception as exc:
        return MethodResult(
            success=False, validated=False,
            message=f"Region inspection failed: {type(exc).__name__}: {exc}",
        )


#: Inputs ``pdf.render@2`` opens. The pipeline also accepts TIFF, BMP, GIF and
#: WebP; the Toolbox does not render those, and there is no local fallback.
_RENDERABLE_MEDIA_TYPES = frozenset({"application/pdf", "image/png", "image/jpeg"})


def _source_artifact_id(manifest: ProcessingManifest) -> str | None:
    """The Toolbox artifact of the source document, when the extractor stored one.

    Artifact ids are content addressed, so the id is used only when its digest
    is the manifest's source SHA-256: an id of any other document (a restored
    or reassembled manifest, a wrong id) would have the Toolbox render pixels
    the evidence does not describe. Otherwise the file itself is sent.
    """
    from acessilia_sdk.toolbox import ArtifactRef, ToolboxContractViolation

    value = (manifest.extractor.configuration or {}).get("artifact_id")
    if not isinstance(value, str) or not value:
        return None
    try:
        ref = ArtifactRef.parse(value)
    except ToolboxContractViolation:
        return None
    return value if ref.digest == manifest.source.sha256 else None


def _toolbox_render(
    source: Path,
    page_number: int,
    *,
    media_type: str | None = None,
    dpi: int,
    max_side: int | None = None,
    clip: tuple[float, float, float, float] | None = None,
    clip_origin: ClipOrigin = "TOPLEFT",
    artifact_id: str | None = None,
) -> RenderedPage:
    """Render a page (or a region of it) on the Toolbox with ``pdf.render@2``.

    There is no local rendering (docs/adr/0003): the Toolbox converts, clips,
    bounds and refuses oversized renders, and reports what it applied. With
    ``artifact_id`` the source already stored by the extractor is referenced
    instead of uploaded; the file is sent only if the Toolbox no longer has it.

    The upload is labelled from the file extension; ``media_type`` (the
    manifest's) must agree with that label. Inputs outside
    ``_RENDERABLE_MEDIA_TYPES`` are refused here with a ``ValueError``, before
    any request, so the method fails with that reason and not a Toolbox error.
    """
    from acessilia_sdk.toolbox.clients import ToolboxPdfClient
    from acessilia_sdk.toolbox.transport import media_type_for

    from backend.tools.toolbox_client import make_toolbox_client, run_sync

    sent_as = media_type_for(source)
    if media_type is not None and media_type != sent_as:
        raise ValueError(
            f"Source is {media_type} in the manifest but would be sent as {sent_as}"
        )
    if sent_as not in _RENDERABLE_MEDIA_TYPES:
        raise ValueError(
            f"pdf.render@2 renders PDF, PNG and JPEG inputs, not {sent_as}"
        )

    async def render():
        client = make_toolbox_client(
            ToolboxPdfClient, resend_file_on_missing_artifact=artifact_id is not None
        )
        try:
            return await client.render(
                file_path=source,
                artifact_id=artifact_id,
                page_number=page_number,
                dpi=dpi,
                max_side=max_side,
                clip=clip,
                clip_origin=clip_origin,
            )
        finally:
            await client.close()

    return run_sync(render())


def _render_source_page(
    source: Path, media_type: str, number: int, artifact_id: str | None = None
) -> bytes:
    """The PNG of page ``number`` of a PDF, PNG or JPEG input, rendered by the Toolbox."""
    from backend.config.settings import settings

    return _toolbox_render(
        source, number, media_type=media_type, dpi=settings.pdf_split_dpi,
        artifact_id=artifact_id,
    ).image

def _inspect_page(image: bytes, number: int, total_pages: int, mode: str) -> PageInspectionOutput:
    from backend.tools.toolbox_client import run_sync

    return run_sync(
        VisionAgent(mode=mode).inspect_page(
            image_bytes=image, page_num=number, total_pages=total_pages
        )
    )


def _handle_vision_page_inspection_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Look at a page the extractor left empty: describe it, or accept it as blank.

    The page is rendered by the Toolbox and judged by the vision model. A page
    with content replaces its placeholder with a ``picture`` that carries the
    page image and its accessible description; a blank page keeps the
    placeholder, marked ``blank_page`` so the canonical document skips it. The
    manifest changes only after every target page validates. Any failure (the
    Toolbox, the model, an invalid answer) fails the method, so a page is never
    dropped silently; the obligation is critical.
    """
    elements = [
        element
        for element in _target_elements(manifest, obligation_id)
        if is_unstructured_page_placeholder(element)
    ]
    if not elements:
        return _missing_obligation(obligation_id)
    try:
        source = Path(manifest.source.path)
        with source.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != manifest.source.sha256:
                raise ValueError("Page source differs from the manifest")
        total_pages = max(len(manifest.pages), 1)
        mode = str(manifest.extractor.configuration.get("region_inspection_mode", "medio"))

        inspected = []
        for element in elements:
            number = element.page_number or 1
            image = _render_source_page(
                source, manifest.source.media_type, number, _source_artifact_id(manifest)
            )
            output = _inspect_page(image, number, total_pages, mode)
            if not isinstance(output, PageInspectionOutput):
                raise TypeError("Page inspection returned no structured output")
            inspected.append((element, number, image, output))

        artifacts: list[Artifact] = []
        replacements: dict[str, ManifestElement] = {}
        blank = 0
        for element, number, image, output in inspected:
            scope = hashlib.sha256(json.dumps([
                manifest.manifest_id, manifest.source.sha256, manifest.revision,
                obligation_id, element.id,
            ]).encode()).hexdigest()
            page_image = _save_region_artifact(image, scope, "page-render", "png", "image/png")
            record = _save_region_artifact(
                json.dumps(
                    {
                        "source_sha256": manifest.source.sha256,
                        "element_id": element.id,
                        "page_number": number,
                        "page_image_sha256": page_image.sha256,
                        "result": output.model_dump(),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode(),
                scope, "page-inspection", "json", "application/json",
            )
            artifacts.extend([page_image, record])
            replacement = element.model_copy(deep=True)
            replacement.metadata.update(
                page_inspection=record.id,
                vision_language=output.language,
                vision_confidence=output.confidence,
                vision_warnings=list(output.warnings),
            )
            if output.kind == "blank":
                replacement.metadata["blank_page"] = True
                blank += 1
            else:
                replacement.type = "picture"
                replacement.raw_label = "picture"
                replacement.text = output.description
                replacement.metadata.update(
                    original_type=element.type,
                    vision_description_complete=True,
                    src="data:image/png;base64," + base64.b64encode(image).decode("ascii"),
                )
            replacements[element.id] = replacement

        manifest.elements = [replacements.get(item.id, item) for item in manifest.elements]
        manifest.summary.element_types = dict(Counter(item.type for item in manifest.elements))
        return MethodResult(
            success=True,
            validated=True,
            message=(
                f"Inspected {len(inspected)} unstructured page(s): "
                f"{len(inspected) - blank} described, {blank} blank"
            ),
            artifacts=artifacts,
        )
    except Exception as exc:
        return MethodResult(
            success=False,
            validated=False,
            message=f"Page inspection failed: {type(exc).__name__}: {exc}",
        )


def _handle_repetition_guard_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Remove repeated token loops from the obligation's current page text."""
    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)

    fusion_agent = _fusion_agent()
    cut_total = 0
    for element in elements:
        result = fusion_agent.process_guard_repetition(element.text or "")
        cut = int(result["tokens_cut"])
        if not cut:
            continue
        element.text = result["text"]
        element.metadata["repetition_guard"] = {"tokens_cut": cut}
        cut_total += cut

    if not cut_total:
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhuma repetição degenerada encontrada nos alvos",
        )
    return MethodResult(
        success=True,
        validated=True,
        message=f"Guarda de repetição removeu {cut_total} token(s)",
    )


def _element_blocks(
    elements: list[ManifestElement],
    manifest: ProcessingManifest,
) -> list[dict[str, Any]]:
    """Manifest elements as the fusion stack's block dicts.

    The deterministic primitives in `docstruct` operate on classified blocks, not
    on bare strings, so the elements are adapted once here instead of each handler
    guessing at a signature.
    """
    blocks: list[dict[str, Any]] = []
    for element in elements:
        bbox = _element_bbox(element, manifest)
        blocks.append(
            {
                "md": element.text or "",
                "text": element.text or "",
                "kind": _block_kind(element),
                "type": element.type,
                "role": _element_role(element),
                "box": list(bbox) if bbox else None,
            }
        )
    return blocks


def _element_role(element: ManifestElement) -> str | None:
    """Fusion block role for an element.

    The manifest builder records page furniture in `element.type`
    (`page_header`/`page_footer`) and does not populate `metadata["role"]`, so the
    role is derived from the type when the metadata does not carry one.
    """
    role = (element.metadata or {}).get("role")
    if role:
        return role
    return {"page_header": "header", "page_footer": "footer"}.get(element.type)


def _block_kind(element: ManifestElement) -> str:
    """Fusion block kind for an element type (`DiffBlock.kind` vocabulary)."""
    if element.type == "heading":
        return "heading"
    if element.type == "table":
        return "table"
    if element.type == "formula":
        return "formula"
    return "text"


def _handle_extract_line_numbers_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Pull marginal verse line numbers out of the target blocks.

    Uses `FusionAgent.process_extract_line_numbers`, which is the supported entry
    point: `docstruct.fusion.line_numbers.extract_line_numbers` needs a block list
    plus a stats counter and a provenance tag, so calling it with a plain string
    raised `TypeError` on every step.
    """
    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)

    result = _fusion_agent().process_extract_line_numbers(
        _element_blocks(elements, manifest)
    )
    extracted = int(result.get("stats", {}).get("line-numbers-agent-count", 0))
    if not extracted:
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhum número de linha marginal encontrado",
        )
    for element in elements:
        element.metadata["line_numbers_extracted"] = extracted
    return MethodResult(
        success=True,
        validated=True,
        message=f"{extracted} número(s) de linha extraído(s)",
    )


def _handle_chunk_verse_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Split verse/record blocks into chunks the evaluator can re-group.

    `docstruct.fusion.verse.chunk_verse` takes already-split lines plus a character
    budget, so the handler goes through `FusionAgent.process_chunk_verse`, which
    detects the verse lines itself.
    """
    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)

    result = _fusion_agent().process_chunk_verse(_element_blocks(elements, manifest))
    # `verse_blocks` reports `verse-{tag}-{whole,kept,split,chunks}`; only the
    # blocks it actually split are evidence that the method did anything.
    chunks = result.get("stats", {}).get("verse-agent-split", 0)
    if not chunks:
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhum bloco de verso elegível para fragmentação",
        )
    for element in elements:
        element.metadata["verse_chunks"] = chunks
    return MethodResult(
        success=True,
        validated=True,
        message=f"Verso fragmentado em {chunks} pedaço(s)",
    )


def _tailjoin_position(manifest: ProcessingManifest) -> str | None:
    """Vertical position ("top"/"bot") of the page number in the manifest.

    `join_tail` only applies the position-conditioned `tj3` rule when it knows
    where the page number sits, which is the distinction between `tailjoin` and
    `tailjoin-positioned`.
    """
    for element in manifest.elements:
        role = _element_role(element)
        if role in {"header", "footer", "page_number"} and _is_page_number(
            element.text or ""
        ):
            bbox = _element_bbox(element, manifest)
            if bbox is None:
                continue
            return "top" if (bbox[1] + bbox[3]) / 2 < 0.5 else "bot"
    return None


def _handle_tailjoin_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Join the trailing short blocks (header/footer/page number).

    `docstruct.fusion.tailjoin.join_tail` requires the tail mode, a maximum short
    block length and the number of blocks to consider, so it cannot be called with
    the text alone. `FusionAgent.process_join_tail` supplies those defaults.
    """
    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)

    texts = [(element.text or "") for element in elements]
    merged = _fusion_agent().process_join_tail(
        texts, position=_tailjoin_position(manifest)
    )
    if len(merged) >= len(texts):
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhum bloco de cauda elegível para união",
        )
    for element in elements:
        element.metadata["tailjoined"] = True
    return MethodResult(
        success=True,
        validated=True,
        message=(
            f"Blocos de cauda unidos: {len(texts)} -> {len(merged)} bloco(s)"
        ),
    )


# --- Methods that choose between the two providers of FUSION_MODE=dual -------
#
# table-smart-fusion, skeleton-order and agreement-rule port Dr.DocBench rules
# (tree_differ_v2.py of the drbench-2026-snapshot tag and
# docstruct.fusion.adjudication.decide_v1). They read the secondary provider's
# extraction that the structure extractor keeps as a manifest artifact. The
# rules were calibrated on the docling + mineru pair, so any other pair fails
# explicitly instead of applying a preference nobody measured.

_CALIBRATED_PAIR = ("docling", "mineru")
#: Accepted Dr.DocBench table preference (TEDS): MinerU's table, unless Docling's
#: has spans or is the only one.
_TABLE_PREFERENCE = "mineru"
#: Minimum intersection over union to pair two blocks by position.
_MIN_BLOCK_IOU = 0.3
#: Minimum text similarity to pair two blocks that could not be paired by position.
_MIN_BLOCK_TEXT_RATIO = 0.8
#: Share of a page's elements that must be paired to follow the skeleton order.
_MIN_SKELETON_MATCH = 0.5

_Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class _SecondaryExtraction:
    provider: str
    #: page number -> raw elements of the secondary provider, in reading order.
    pages: dict[int, list[dict[str, Any]]]
    sizes: dict[int, tuple[float, float]]
    #: page number -> primary elements of a page the manifest took from the
    #: secondary provider (fusion.apply_page_routes), in reading order.
    replaced_primary: dict[int, list[dict[str, Any]]] = field(default_factory=dict)

    def bbox(self, element: dict[str, Any]) -> _Box | None:
        """Normalized box of a raw Toolbox element (same frame as _element_bbox)."""
        for item in element.get("provenance") or []:
            if not isinstance(item, dict) or not item.get("bbox"):
                continue
            box = item["bbox"]
            page = _page_number(item.get("page_number", element.get("page_number")))
            width, height = self.sizes.get(page, (0.0, 0.0)) if page else (0.0, 0.0)
            if not width or not height:
                return None
            try:
                left, right = float(box["left"]), float(box["right"])
                top, bottom = float(box["top"]), float(box["bottom"])
            except (KeyError, TypeError, ValueError):
                return None
            if is_bottom_left(box.get("coord_origin"), top, bottom):
                top, bottom = height - top, height - bottom
            return _ordered_box(
                left / width, top / height, right / width, bottom / height
            )
        return None


def _page_number(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _load_secondary_extraction(
    manifest: ProcessingManifest,
) -> tuple[_SecondaryExtraction | None, str]:
    """The secondary provider's extraction, if recorded and unchanged.

    When it cannot be used, the second item says why (missing, replaced or
    unreadable), so the method result can tell those cases apart.
    """
    import json

    artifact = next(
        (a for a in manifest.artifacts if a.kind == SECONDARY_EXTRACTION_KIND), None
    )
    if artifact is None:
        return None, "Extração do provider secundário ausente do manifesto"
    try:
        raw = Path(artifact.path).read_bytes()
    except OSError:
        return None, f"Extração do provider secundário indisponível: {artifact.path}"
    if artifact.sha256 and hashlib.sha256(raw).hexdigest() != artifact.sha256:
        logger.warning(
            "Extração secundária {} não confere com o sha256 registrado",
            artifact.path,
        )
        return None, (
            "Extração do provider secundário alterada: sha256 diverge do "
            f"registrado no manifesto ({artifact.path})"
        )
    unreadable = f"Extração do provider secundário ilegível: {artifact.path}"
    try:
        data = json.loads(raw)
    except ValueError:
        return None, unreadable
    payload = data.get("document") if isinstance(data, dict) else None
    if not isinstance(payload, dict):
        return None, unreadable
    document = payload.get("document", payload)
    sizes: dict[int, tuple[float, float]] = {}
    for page in document.get("pages") or []:
        try:
            sizes[int(page["page_number"])] = (
                float(page.get("width") or 0),
                float(page.get("height") or 0),
            )
        except (KeyError, TypeError, ValueError):
            continue
    pages: dict[int, list[dict[str, Any]]] = {}
    for element in sorted(
        (e for e in document.get("elements") or [] if isinstance(e, dict)),
        key=lambda e: e.get("reading_order") or 0,
    ):
        page = _page_number(element.get("page_number"))
        if page is not None:
            pages.setdefault(page, []).append(element)
    replaced: dict[int, list[dict[str, Any]]] = {}
    for key, rows in (data.get("replaced_primary_pages") or {}).items():
        page = _page_number(key)
        if page is not None and isinstance(rows, list):
            replaced[page] = sorted(
                (row for row in rows if isinstance(row, dict)),
                key=lambda row: row.get("reading_order") or 0,
            )
    return (
        _SecondaryExtraction(str(data.get("provider") or ""), pages, sizes, replaced),
        "",
    )


def _provider_pair_problem(
    manifest: ProcessingManifest, secondary: _SecondaryExtraction
) -> str | None:
    primary = str((manifest.extractor.configuration or {}).get("toolbox_provider") or "")
    if (primary, secondary.provider) == _CALIBRATED_PAIR:
        return None
    return (
        f"Regra calibrada para {'+'.join(_CALIBRATED_PAIR)}; "
        f"par atual: {primary or '?'}+{secondary.provider or '?'}"
    )


def _secondary_or_failure(
    manifest: ProcessingManifest,
) -> tuple[_SecondaryExtraction | None, MethodResult | None]:
    secondary, problem = _load_secondary_extraction(manifest)
    if secondary is None:
        return None, MethodResult(success=False, validated=False, message=problem)
    problem = _provider_pair_problem(manifest, secondary)
    if problem:
        return None, MethodResult(success=False, validated=False, message=problem)
    return secondary, None


def _ordered_box(left: float, top: float, right: float, bottom: float) -> _Box:
    return (min(left, right), min(top, bottom), max(left, right), max(top, bottom))


def _iou(a: _Box, b: _Box) -> float:
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0 or height <= 0:
        return 0.0
    inter = width * height
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _pair_block(
    element: ManifestElement,
    manifest: ProcessingManifest,
    candidates: list[dict[str, Any]],
    secondary: _SecondaryExtraction,
    used: set[int],
) -> int | None:
    """Index in ``candidates`` of the block that matches ``element``.

    Greedy: each element takes its best free candidate in the current reading
    order, while Dr.DocBench uses a global (Hungarian) assignment. The two can
    differ only when blocks compete for the same candidate, which is rare above
    the IoU / text thresholds and does not move the skeleton's 0.5 page gate.
    """
    import difflib

    box = _element_bbox(element, manifest)
    if box is not None:
        box = _ordered_box(*box)
        scored = [
            (_iou(box, other), index)
            for index, candidate in enumerate(candidates)
            if index not in used and (other := secondary.bbox(candidate)) is not None
        ]
        best = max(scored, default=(0.0, None))
        if best[0] >= _MIN_BLOCK_IOU:
            return best[1]
    text = " ".join((element.text or "").split())
    if not text:
        return None
    scored_text = [
        (
            difflib.SequenceMatcher(
                None,
                text,
                " ".join(str(candidate["text"]).split()),
                autojunk=False,
            ).ratio(),
            index,
        )
        for index, candidate in enumerate(candidates)
        if index not in used and candidate.get("text")
    ]
    best_text = max(scored_text, default=(0.0, None))
    return best_text[1] if best_text[0] >= _MIN_BLOCK_TEXT_RATIO else None


def _handle_table_smart_fusion_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Pick each table's source between the two providers (Dr.DocBench rule).

    Docling's table is kept when it has spans (MinerU flattens them) or when it
    is the only one; otherwise MinerU's table is adopted. Tables are paired by
    position or text; a page with a single table on each side pairs them only
    when there is no position to compare. The choice and its reason are recorded
    in ``table_source`` / ``table_source_reason``.
    """
    from docstruct.tables.ast import analyze_table_complexity

    tables = [
        element
        for element in _target_elements(manifest, obligation_id)
        if element.type == "table"
    ]
    if not tables:
        return _missing_obligation(obligation_id)
    secondary, failure = _secondary_or_failure(manifest)
    if failure is not None:
        return failure

    primary_name, secondary_name = _CALIBRATED_PAIR
    primary_tables_by_page = Counter(
        element.page_number
        for element in manifest.elements
        if element.type == "table"
    )
    reasons: Counter = Counter()
    for element in tables:
        primary_ast = (element.metadata or {}).get("table_ast")
        candidates = [
            block
            for block in secondary.pages.get(element.page_number or 0, [])
            if block.get("type") == "table"
        ]
        match = _pair_block(element, manifest, candidates, secondary, set())
        if (
            match is None
            and len(candidates) == 1
            and primary_tables_by_page[element.page_number] == 1
            and (
                _element_bbox(element, manifest) is None
                or secondary.bbox(candidates[0]) is None
            )
        ):
            # One table on each side and no position to compare them by: the
            # same table. With both positions known and no overlap, they are not.
            match = 0
        chosen = candidates[match] if match is not None else None
        chosen_meta = (chosen or {}).get("metadata") or {}

        if primary_ast and analyze_table_complexity(primary_ast).has_spans:
            source, reason = primary_name, "primary-has-spans"
        elif not candidates:
            source, reason = primary_name, "no-secondary-table"
        elif chosen is None:
            source, reason = primary_name, "no-secondary-match"
        elif not (chosen.get("text") or chosen_meta.get("table_ast")):
            source, reason = primary_name, "secondary-table-empty"
        else:
            source, reason = _TABLE_PREFERENCE, f"preference-{_TABLE_PREFERENCE}"

        if source == secondary_name and chosen is not None:
            # Docling's table_* keys (AST, row/column counts, header) describe
            # the table being replaced; the output prefers table_ast over the
            # text, so a stale AST would hide the adopted MinerU text.
            for key in [k for k in element.metadata if k.startswith("table_")]:
                del element.metadata[key]
            if chosen.get("text"):
                element.text = chosen["text"]
            for key, value in chosen_meta.items():
                if key.startswith("table_"):
                    element.metadata[key] = value
        element.metadata["table_source"] = source
        element.metadata["table_source_reason"] = reason
        reasons[reason] += 1

    return MethodResult(
        success=True,
        validated=True,
        message="Fonte de tabela escolhida: "
        + ", ".join(f"{reason}={count}" for reason, count in sorted(reasons.items())),
    )


def _handle_skeleton_order_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Follow the secondary provider's reading order (MinerU skeleton).

    Page elements are paired with the secondary blocks by position (falling
    back to text); paired elements take the skeleton order and unpaired ones
    stay right after the element that preceded them. A page with fewer than
    half its elements paired is left alone.
    """
    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)
    secondary, failure = _secondary_or_failure(manifest)
    if failure is not None:
        return failure

    by_page: dict[int, list[ManifestElement]] = {}
    for element in elements:
        if element.page_number is not None:
            by_page.setdefault(element.page_number, []).append(element)

    reordered: set[int] = set()
    confirmed: set[int] = set()
    for page_number, page_elements in by_page.items():
        current = sorted(page_elements, key=lambda element: element.reading_order)
        skeleton = secondary.pages.get(page_number, [])
        used: set[int] = set()
        keys: dict[int, int] = {}
        for index, element in enumerate(current):
            match = _pair_block(element, manifest, skeleton, secondary, used)
            if match is not None:
                used.add(match)
                keys[index] = match
        if len(current) < 2 or len(keys) < _MIN_SKELETON_MATCH * len(current):
            continue
        ranked: list[tuple[float, int, int]] = []
        last = -1.0
        for index in range(len(current)):
            if index in keys:
                last = float(keys[index])
                ranked.append((last, 0, index))
            else:
                ranked.append((last, 1, index))
        order = [index for _, _, index in sorted(ranked)]
        if _apply_page_order(current, order):
            reordered.add(page_number)
        else:
            confirmed.add(page_number)

    if not reordered and not confirmed:
        return MethodResult(
            success=False,
            validated=False,
            message="Esqueleto do provider secundário não casou com a página",
        )
    _refresh_page_element_ids(manifest, reordered)
    parts = []
    if reordered:
        parts.append("aplicada nas páginas " + ", ".join(map(str, sorted(reordered))))
    if confirmed:
        parts.append("confirmada nas páginas " + ", ".join(map(str, sorted(confirmed))))
    return MethodResult(
        success=True,
        validated=True,
        message="Ordem do esqueleto " + "; ".join(parts),
    )


def _page_markdown(items: Iterable[tuple[str, str | None]]) -> str:
    """Page text with the markers the page router looks for."""
    parts = []
    for kind, text in items:
        text = (text or "").strip()
        if kind == "table":
            parts.append(f"<table>{text}</table>")
        elif kind == "formula":
            parts.append(f"$${text}$$")
        elif text:
            parts.append(text)
    return "\n\n".join(parts)


def _handle_agreement_rule_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Deterministic page router between the providers (``decide_v1``).

    When the router keeps the primary (Docling) page the obligation is
    satisfied without changing the text. When it picks the secondary page the
    decision is recorded but not applied: replacing a whole page would reopen
    the manifest mid-plan, and Dr.DocBench measured this router below the
    block-level fusion the core already runs. The method then fails, so the
    obligation goes to ``human-review`` with the route in ``page_route``.
    """
    from docstruct.fusion.adjudication import decide_v1

    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)
    secondary, failure = _secondary_or_failure(manifest)
    if failure is not None:
        return failure

    primary_name = _CALIBRATED_PAIR[0]
    routes: dict[int, tuple[str, str]] = {}
    for page_number in sorted({e.page_number for e in elements if e.page_number}):
        primary_md = _page_markdown(
            (element.type, element.text)
            for element in sorted(manifest.elements, key=lambda e: e.reading_order)
            if element.page_number == page_number
        )
        secondary_md = _page_markdown(
            (str(block.get("type") or ""), block.get("text"))
            for block in secondary.pages.get(page_number, [])
        )
        routes[page_number] = decide_v1(primary_md, secondary_md)

    for element in elements:
        if element.page_number in routes:
            choice, reason = routes[element.page_number]
            element.metadata["page_route"] = {"choice": choice, "reason": reason}

    rerouted = {page: route for page, route in routes.items() if route[0] != primary_name}
    if not routes:
        return MethodResult(
            success=False,
            validated=False,
            message="Obrigação sem página identificada para o roteador",
        )
    if rerouted:
        return MethodResult(
            success=False,
            validated=False,
            message=(
                "Roteador por página escolhe o provider secundário ("
                + ", ".join(f"p{page}: {reason}" for page, (_, reason) in sorted(rerouted.items()))
                + "); a troca de página não é aplicada automaticamente"
            ),
        )
    return MethodResult(
        success=True,
        validated=True,
        message="Roteador por página mantém o provider primário nas páginas "
        + ", ".join(map(str, sorted(routes))),
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

    from acessilia_sdk.toolbox.clients import ToolboxAdjudicateClient
    from backend.tools.toolbox_client import make_toolbox_client, run_sync

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


def _judge_probability(document: dict[str, Any]) -> float | None:
    """``pB`` of a judge answer, or ``None`` when absent or outside [0, 1]."""
    try:
        p_b = float(document["pB"])
    except (KeyError, TypeError, ValueError):
        return None
    return p_b if 0.0 <= p_b <= 1.0 else None


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
    from docstruct.fusion.judge import DEFAULT_NEW_THR, should_judge

    from backend.tools.toolbox_client import (
        ToolboxAuthenticationError,
        ToolboxContractViolation,
        ToolboxError,
    )

    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)
    secondary, failure = _secondary_or_failure(manifest)
    if failure is not None:
        return failure

    primary_name = _CALIBRATED_PAIR[0]
    source_path = Path(manifest.source.path)
    judgements: dict[int, dict[str, Any]] = {}
    for page_number in sorted({e.page_number for e in elements if e.page_number}):
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
                continue
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
            continue
        if not should_judge(primary_md, secondary_md):
            judgements[page_number] = {
                "content": content, "choice": content, "pB": None, "reason": "agree",
            }
            continue

        try:
            image = _render_page_png(
                source_path,
                page_number,
                _source_artifact_id(manifest),
                manifest.source.media_type,
            )
        except Exception as exc:  # noqa: BLE001 - rendering a broken source
            return MethodResult(
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
            return MethodResult(
                success=False,
                validated=False,
                message=f"Juiz VLM recusou a chamada: {type(exc).__name__}: {exc}",
            )
        except ToolboxError as exc:
            return MethodResult(
                success=False,
                validated=False,
                message=f"Juiz VLM indisponível: {type(exc).__name__}: {exc}",
            )
        document = result.get("document") or {}
        p_b = _judge_probability(document)
        if p_b is None:
            return MethodResult(
                success=False,
                validated=False,
                message=(
                    f"Juiz VLM não devolveu pB válido para a página {page_number}: "
                    f"{document.get('pB')!r}"
                ),
            )
        judgements[page_number] = {
            "content": content,
            "choice": other if p_b > DEFAULT_NEW_THR else content,
            "pB": p_b,
            "pB_ab": document.get("pB_ab"),
            "pA_ba": document.get("pA_ba"),
            "model": document.get("model"),
            "truncated": truncated,
        }

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


def _apply_page_order(current: list[ManifestElement], order: list[int]) -> bool:
    """Reassign the reading-order slots of ``current`` following ``order``.

    ``order[i]`` is the index in ``current`` of the element that goes to the
    i-th slot. Returns whether anything moved.
    """
    if order == list(range(len(current))):
        return False
    slots = sorted(element.reading_order for element in current)
    for slot, index in zip(slots, order):
        current[index].reading_order = slot
    return True


def _refresh_page_element_ids(
    manifest: ProcessingManifest, page_numbers: set[int]
) -> None:
    manifest.elements.sort(key=lambda element: element.reading_order)
    for page in manifest.pages:
        if page.page_number in page_numbers:
            page.element_ids = [
                element.id
                for element in manifest.elements
                if element.page_number == page.page_number
            ]


def _handle_xycut_order_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Apply XY-cut reading order to the evidenced page elements."""
    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)

    fusion_agent = _fusion_agent()
    reordered_pages: set[int] = set()
    by_page: dict[int, list[ManifestElement]] = {}
    for element in elements:
        if element.page_number is not None:
            by_page.setdefault(element.page_number, []).append(element)

    for page_number, page_elements in by_page.items():
        positioned = [
            element for element in page_elements
            if _element_bbox(element, manifest) is not None
        ]
        if len(positioned) < 2:
            continue
        current = sorted(positioned, key=lambda element: element.reading_order)
        boxes = [_element_bbox(element, manifest) for element in current]
        order = fusion_agent.process_refine_reading_order(
            [list(box) for box in boxes if box is not None]
        )
        if _apply_page_order(current, order):
            reordered_pages.add(page_number)

    if not reordered_pages:
        return MethodResult(
            success=False,
            validated=False,
            message="XY-cut não identificou uma mudança de ordem de leitura",
        )

    _refresh_page_element_ids(manifest, reordered_pages)
    return MethodResult(
        success=True,
        validated=True,
        message=(
            "Ordem de leitura XY-cut aplicada nas páginas "
            + ", ".join(map(str, sorted(reordered_pages)))
        ),
    )


def _handle_human_review_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Record the obligation as escalated to a human reviewer.

    `human-review` is the terminal method every obligation lists as its last
    admissible option. It is not an automated method that can succeed on its own,
    so resolving it must be an explicit decision: an obligation reaching this
    handler is escalated and stays visible in the execution report, instead of
    being marked satisfied by a handler that did nothing.
    """
    obligation = next(
        (o for o in manifest.obligations if o.id == obligation_id), None
    )
    if obligation is None:
        return _missing_obligation(obligation_id)

    return MethodResult(
        success=False,
        validated=False,
        message=(
            "Escalonado para revisão humana: nenhum método automático satisfez "
            f"{obligation.kind} ({obligation_id})"
        ),
    )


def _handle_deterministic_heading_repair_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Repair the full sequence, since fixing one heading can expose a later gap."""
    obligation = next(
        (o for o in manifest.obligations if o.id == obligation_id), None
    )
    if obligation is None:
        return _missing_obligation(obligation_id)

    targets = _target_elements(manifest, obligation_id)
    if not targets or any(element.type not in {"title", "heading"} for element in targets):
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhum título encontrado para a obrigação",
        )
    previous = 0
    repaired = 0
    for element in sorted(manifest.elements, key=lambda item: item.reading_order):
        if element.type not in {"title", "heading"}:
            continue
        level = 1 if not previous else max(2, min(element.hierarchy_level, previous + 1, 6))
        if previous and element.type == "title":
            element.metadata["original_type"] = "title"
            element.type = "heading"
        if level != element.hierarchy_level:
            element.metadata["original_heading_level"] = element.hierarchy_level
            element.hierarchy_level = level
            element.metadata["heading_repaired"] = True
            repaired += 1
        previous = level
    manifest.summary.element_types = dict(Counter(element.type for element in manifest.elements))
    return MethodResult(
        success=True,
        validated=True,
        message=f"Hierarquia de títulos verificada; {repaired} título(s) reparado(s)",
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


def _reusable_fusion_payload(manifest: ProcessingManifest) -> dict | None:
    from dataclasses import asdict

    from docstruct.policy import FusionPolicy

    from backend.services.cache import processing_cache_configuration

    ref = manifest.extractor.configuration.get("fusion_reuse") or {}
    try:
        content = Path(ref["path"]).read_bytes()
        if hashlib.sha256(content).hexdigest() != ref["sha256"]:
            return None
        record = json.loads(content)
        if record["source_sha256"] != manifest.source.sha256:
            return None
        if record.get("policy") != asdict(FusionPolicy()):
            return None
        if json.dumps(record["configuration"], sort_keys=True) != json.dumps(processing_cache_configuration(), sort_keys=True):
            return None
        payload = record["payload"]
        return payload if isinstance(payload, dict) else None
    except (OSError, KeyError, TypeError, ValueError):
        return None


def _handle_dual_provider_fusion_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Funde dois providers (docling+mineru) para a obrigação alvo.

    Reutiliza ``backend.pipeline.fusion.extract_fused`` (Fase 4) para
    produzir o payload fundido, persiste o JSON em ``data_dir/artifacts/
    fusion/`` e o retorna em ``MethodResult.artifacts`` — deixando o
    ``ExecutorAgent`` responsável por incorporá-lo ao manifesto e registrar
    a proveniência na tentativa.

    Em modo single (FUSION_MODE=single) o método não é admissível e não
    deve ser selecionado pelo compilador.

    Reutiliza a fusão inicial quando hash, documento e configuração coincidem.
    Evidência ausente, corrompida ou incompatível provoca reextração dual.
    """
    obligation = next(
        (o for o in manifest.obligations if o.id == obligation_id), None
    )
    if obligation is None:
        return MethodResult(
            success=False,
            validated=False,
            message=f"Obrigação não encontrada: {obligation_id}",
        )
    source_path = Path(manifest.source.path)
    # Reuse the document the structure extractor already stored in the Toolbox.
    artifact_id = _source_artifact_id(manifest)
    try:
        payload = _reusable_fusion_payload(manifest)
        if payload is None:
            payload = _run_extract_fused(source_path, artifact_id=artifact_id)
    except Exception as exc:  # noqa: BLE001
        return MethodResult(
            success=False,
            validated=False,
            message=f"Fusão dual-provider falhou: {type(exc).__name__}: {exc}",
        )
    if payload.get("status") != "succeeded":
        return MethodResult(
            success=False,
            validated=False,
            message="Fusão dual-provider não concluiu com sucesso",
        )

    # A ação planejada é dual-provider: se apenas um provider participou,
    # a semântica planejada não foi executada → falha para permitir replanning
    # para um método single-provider.
    provider = str(payload.get("provider") or "")
    if "+" not in provider:
        return MethodResult(
            success=False,
            validated=False,
            message=(
                "Fusão dual-provider executou com um único provider "
                f"({provider or 'desconhecido'}); replanning necessário"
            ),
        )

    try:
        elements = _fused_text_elements(manifest, obligation.target_ids, payload)
    except (TypeError, ValueError) as exc:
        return MethodResult(success=False, validated=False, message=str(exc))

    artifact = _persist_fusion_payload(
        manifest,
        payload,
        obligation_id,
        kind="fusion-payload",
    )

    manifest.elements = elements
    page_ids = {element.page_number or 1 for element in elements}
    existing_pages = {page.page_number: page for page in manifest.pages}
    manifest.pages = [
        PageDescriptor(
            page_number=number,
            width=existing_pages[number].width if number in existing_pages else None,
            height=existing_pages[number].height if number in existing_pages else None,
            element_ids=[element.id for element in elements if (element.page_number or 1) == number],
        )
        for number in sorted(page_ids)
    ]
    manifest.summary.page_count = len(manifest.pages)
    manifest.summary.element_count = len(elements)
    manifest.summary.element_types = dict(Counter(element.type for element in elements))
    return MethodResult(
        success=True,
        validated=True,
        message="Fusão dual-provider concluída com sucesso",
        artifacts=[artifact],
    )


def _fused_text_elements(
    manifest: ProcessingManifest, target_ids: list[str], payload: dict[str, Any]
) -> list[ManifestElement]:
    # The fusion adapter currently emits text-only blocks. It cannot safely
    # replace a structured document or a subset with a whole-document result.
    if any(element.type != "paragraph" for element in manifest.elements) or set(target_ids) != {
        element.id for element in manifest.elements
    }:
        raise ValueError("Text fusion requires all paragraphs of a text-only manifest")
    raw_elements = payload.get("document", {}).get("elements")
    if not isinstance(raw_elements, list) or not raw_elements:
        raise ValueError("Fusion returned no usable document elements")
    originals = sorted(manifest.elements, key=lambda element: element.reading_order)
    by_page: dict[int, list[dict[str, Any]]] = {}
    for raw in raw_elements:
        if not isinstance(raw, dict) or raw.get("type") != "paragraph":
            raise ValueError("Fusion returned unsupported structured content")
        text = raw.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Fusion returned an empty text block")
        page = raw.get("page_number", raw.get("page"))
        if page is None:
            if len(manifest.pages) > 1:
                raise ValueError("Fusion omitted page identity for a multipage document")
            page = manifest.pages[0].page_number if manifest.pages else 1
        if type(page) is not int or page < 1:
            raise ValueError("Fusion returned an invalid page number")
        by_page.setdefault(page, []).append(raw)
    original_pages = {element.page_number or 1 for element in originals}
    if not original_pages.issubset(by_page):
        raise ValueError("Fusion omitted a source page")

    result = []
    for number, rows in sorted(by_page.items()):
        old = [element for element in originals if (element.page_number or 1) == number]
        # Keep every existing ID and reference; ambiguous mappings fail closed.
        if len(rows) < len(old):
            raise ValueError("Fusion cannot safely map fewer blocks to existing element references")
        for index, raw in enumerate(rows):
            if index < len(old):
                element = old[index].model_copy(deep=True)
                element.text = raw["text"]
                element.page_number = number
            else:
                identifier = hashlib.sha256(json.dumps([
                    manifest.manifest_id, number, index, raw["text"],
                ]).encode()).hexdigest()[:24]
                element = ManifestElement(
                    id=f"element-fusion-{identifier}", type="paragraph", raw_label="paragraph",
                    reading_order=len(result) + 1, hierarchy_level=0,
                    page_number=number, text=raw["text"],
                )
            element.metadata["fusion_provider"] = payload["provider"]
            element.reading_order = len(result) + 1
            result.append(element)
    return result


def _handle_single_provider_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Satisfy ``fuse-providers`` with the extraction the manifest already carries.

    There is nothing to re-run: the manifest's elements are the configured
    provider's extraction, with the pages the deterministic router took from
    the secondary provider in dual mode (``fusion.apply_page_routes``). The
    method does not claim a single-provider document; it checks only that the
    manifest was extracted by the configured provider and has content. It used
    to extract the whole document again, uploaded anew and with the Toolbox
    cache off, once per ``fuse-providers`` step, and changed nothing in the
    manifest: a full extraction of cost for no content.
    """
    from backend.config.settings import settings

    obligation = next(
        (item for item in manifest.obligations if item.id == obligation_id), None
    )
    if obligation is None:
        return _missing_obligation(obligation_id)
    if obligation.kind != "fuse-providers":
        return MethodResult(
            success=False,
            validated=False,
            message="single-provider só é válido para fuse-providers",
        )

    provider = str(manifest.extractor.configuration.get("toolbox_provider") or "")
    if not provider:
        return MethodResult(
            success=False,
            validated=False,
            message="The manifest does not record the provider it was extracted by",
        )
    if provider != settings.toolbox_provider:
        return MethodResult(
            success=False,
            validated=False,
            message=(
                f"The manifest was extracted by {provider}, not by the configured "
                f"provider ({settings.toolbox_provider})"
            ),
        )
    if not manifest.elements:
        return MethodResult(
            success=False,
            validated=False,
            message="The manifest extraction has no elements",
        )
    return MethodResult(
        success=True,
        validated=True,
        message=(
            f"The manifest already carries the extraction ({provider}); "
            "nothing to re-extract"
        ),
    )


def _persist_fusion_payload(
    manifest: ProcessingManifest,
    payload: dict[str, Any],
    obligation_id: str,
    *,
    kind: str,
) -> Artifact:
    """Write the payload atomically, addressed by its manifest scope and content."""
    from backend.config.settings import settings

    content = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    scope = hashlib.sha256(json.dumps([
        manifest.manifest_id, manifest.source.document_id, manifest.source.sha256,
        manifest.revision, obligation_id,
    ]).encode()).hexdigest()
    output_path = settings.data_dir / "artifacts" / "fusion" / scope / f"{digest}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output_path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, output_path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return Artifact(
        id=f"artifact-{kind.removesuffix('-payload')}-{scope[:16]}-{digest[:16]}",
        kind=kind,
        path=str(output_path),
        media_type="application/json",
        sha256=digest,
    )


class StructuralExtractionError(RuntimeError):
    """The Toolbox could not extract the document structure (job-level failure)."""


class DocumentTooLargeError(ValueError):
    """The document has more pages than ``MAX_PAGES`` (job-level failure)."""


def _check_page_limit(manifest: ProcessingManifest) -> None:
    """Refuses a document with more pages than ``MAX_PAGES``.

    It runs right after the structural extraction, the first point where the
    page count is always known, and before planning and the vision-model
    calls. Only ``media.inspect`` runs before it, since whether the source is
    a slide deck decides how it is extracted. Nothing is processed partially, and the message, which reaches the
    end user, names the page count and the limit.

    Raises:
        DocumentTooLargeError: When the manifest has more pages than the limit.
    """
    from backend.config.settings import settings

    page_count = len(manifest.pages)
    if page_count > settings.max_pages:
        raise DocumentTooLargeError(
            t(STAGE_DOCUMENT_TOO_MANY_PAGES).format(
                page_count=page_count, max_pages=settings.max_pages
            )
        )


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

    async def executar(
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
        presentation = _is_presentation(media_inspection)

        if status_callback:
            await status_callback(t(STAGE_ANALYZING_STRUCTURAL))
        try:
            manifest = await run_blocking(
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
        _check_page_limit(manifest)
        manifest.extractor.configuration["region_inspection_mode"] = effective_mode
        manifest.extractor.configuration.update(media_configuration)

        if status_callback:
            await status_callback(t(STAGE_ENRICHING_IMAGE_DESCRIPTIONS))
        await _enrich_picture_descriptions(
            manifest,
            source_path,
            mode=effective_mode,
            media_inspection=media_inspection,
            status_callback=status_callback,
        )
        await _mark_inline_math(manifest, source_path)
        await _enrich_formula_latex(
            manifest,
            source_path,
            mode=effective_mode,
            status_callback=status_callback,
        )

        if status_callback:
            await status_callback(t(STAGE_ENRICHING_TABLES_OCR))
        await _enrich_table_structures(
            manifest,
            file_path.resolve(),
            status_callback=status_callback,
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
#: for the operator: the crop could not be rendered, the vision call failed (its
#: error goes to metadata["vision_failure_detail"]), or the answer had no text.
VisionFailureReason = Literal["crop_unavailable", "model_failed", "empty_description"]


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
) -> None:
    from backend.config.settings import settings

    _inject_full_page_picture(manifest, media_inspection)

    pictures = [
        element
        for element in manifest.elements
        if element.type == "picture"
        and not element.metadata.get("vision_description_complete")
    ]
    if not pictures and _is_mostly_visual_manifest(manifest):
        pictures = [
            element
            for element in manifest.elements
            if _is_placeholder_visual_element(element)
            and not element.metadata.get("vision_description_complete")
        ]

    if (
        not pictures
        and _is_mostly_visual_manifest(manifest)
        and len(manifest.pages) == 1
        and manifest.elements
    ):
        pictures = [element for element in manifest.elements
                    if not element.metadata.get("vision_description_complete")
                    and not is_unstructured_page_placeholder(element)][:1]

    if not pictures:
        return

    vision = VisionAgent(mode=mode)
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
            image_bytes, page_number = await run_blocking(
                _extract_picture_bytes,
                source_file,
                element,
                fallback_page_number,
                _source_artifact_id(manifest),
                manifest.source.media_type,
            )
            if not image_bytes:
                _record_vision_failure(element, "crop_unavailable")
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

        if not isinstance(vision_output, VisionOutput):
            _record_vision_failure(element, "model_failed", errors[-1] if errors else None)
            return False

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
            if element.type != "formula":
                previous_type = element.type
                element.metadata["original_type"] = element.type
                element.type = "formula"
                element.raw_label = "formula"
                reconcile_reclassified_element_processing_needs(
                    manifest,
                    element,
                    previous_type=previous_type,
                )
        else:
            # An empty answer keeps text the extractor already had; whether
            # that text is worth keeping is decided below.
            answered = bool(vision_output.description.strip())
            if answered:
                element.text = vision_output.description
            if element.type != "picture":
                previous_type = element.type
                element.metadata["original_type"] = element.type
                element.type = "picture"
                element.raw_label = "picture"
                reconcile_reclassified_element_processing_needs(
                    manifest,
                    element,
                    previous_type=previous_type,
                )
        if element.page_number is None and page_number >= 1:
            element.page_number = page_number
        # The model's own text stands however short ("Logo" is a description);
        # text left over from the extractor after an empty answer must still be
        # meaningful. Otherwise the picture is reported as undescribed, so the
        # operator sees the model refused instead of a silent gap, and stays
        # eligible for a later pass.
        if answered or _has_meaningful_text(element):
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

    if enriched:
        logger.info(t(LOG_PDDL_IMAGES_ENRICHED).format(count=enriched))


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
    clip, origin = _picture_clip(provenance)
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


def _ranked_formula_candidates(candidates: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Candidates with LaTeX, normalized, by decreasing confidence.

    ``math.recognize`` returns one entry per detected expression; a chip should
    hold one, but a provider may return several. A confidence that is not a
    finite number (missing, a bool, NaN, infinity) becomes ``None`` in the
    candidate and ranks as 0, so the order stays total and no such value
    reaches the manifest; ties keep the provider's order.
    """
    ranked: list[tuple[float, dict[str, Any]]] = []
    for candidate in candidates:
        latex = normalize_latex(str(candidate.get("latex") or ""))
        if not latex:
            continue
        confidence = candidate.get("confidence")
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(confidence)
        ):
            confidence = None
        score = 0.0 if confidence is None else float(confidence)
        ranked.append((score, {**candidate, "latex": latex, "confidence": confidence}))
    ranked.sort(key=lambda pair: -pair[0])
    return [candidate for _, candidate in ranked]


#: Element types whose text the exporters render as prose with inline math.
_INLINE_MATH_ELEMENT_TYPES = frozenset({"paragraph", "list_item", "caption", "footnote"})
#: Points a span's centre may lie outside its element's box.
_INLINE_MATH_BOX_TOLERANCE = 2.0


async def _mark_inline_math(manifest: ProcessingManifest, source_path: Path) -> dict[str, int]:
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
    from acessilia_sdk.toolbox.errors import ToolboxError

    from backend.config.settings import settings
    from backend.tools.text_spans import fetch_text_spans

    counts = {"elements": 0, "marked": 0, "unmatched": 0}
    if settings.inline_math_detection != "fonts" or manifest.source.media_type != "application/pdf":
        return counts
    candidates = [
        element
        for element in manifest.elements
        if element.type in _INLINE_MATH_ELEMENT_TYPES
        and (element.text or "").strip()
        and "inline_math_detection" not in element.metadata
        and any(provenance.bbox is not None for provenance in element.provenance)
    ]
    pages = sorted(
        {
            provenance.page_number
            for element in candidates
            for provenance in element.provenance
            if provenance.bbox is not None
        }
    )
    if not pages:
        return counts
    try:
        spans = await fetch_text_spans(
            source_path, pages, artifact_id=_source_artifact_id(manifest)
        )
    except ToolboxError as exc:
        logger.info("Inline math detection skipped: document.text.spans failed ({})", exc)
        manifest.extractor.configuration["inline_math_detection"] = "unavailable"
        return counts

    heights = {page.page_number: page.height for page in manifest.pages}
    overlays = [element for element in manifest.elements if is_detached_overlay(element.text)]
    for element in candidates:
        lines = _element_span_lines(element, spans, heights)
        detection = detect_inline_math(lines)
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
        page = next(p.page_number for p in element.provenance if p.bbox is not None)
        for run in result.marked:
            for slash in run.negations:
                _claim_negation_overlay(overlays, element, slash, page, spans, heights)
    manifest.extractor.configuration["inline_math_detection"] = "fonts"
    if counts["elements"]:
        logger.info("Inline math from the text layer's fonts: {}", counts)
    return counts


def _top_left_box(
    box: Any, page: int, spans: dict[int, dict[str, Any]], heights: dict[int, float | None]
) -> tuple[float, float, float, float] | None:
    """``(left, top, right, bottom)`` of a manifest box, top-left origin, in points."""
    if box.coord_origin == "BOTTOMLEFT":
        height = (spans.get(page) or {}).get("height") or heights.get(page)
        if not height:
            return None
        return box.left, height - box.top, box.right, height - box.bottom
    if box.coord_origin == "TOPLEFT":
        return box.left, box.top, box.right, box.bottom
    return None


def _element_span_lines(
    element: ManifestElement,
    spans: dict[int, dict[str, Any]],
    heights: dict[int, float | None],
) -> list[list[TextSpan]]:
    """The element's text-layer lines, in order: spans whose centre lies in its boxes.

    A rotated page is left out: its spans are in the unrotated space, which the
    element's box may not be.
    """
    lines: list[list[TextSpan]] = []
    for provenance in element.provenance:
        page = spans.get(provenance.page_number)
        if provenance.bbox is None or page is None or page.get("rotation"):
            continue
        box = _top_left_box(provenance.bbox, provenance.page_number, spans, heights)
        if box is None:
            continue
        left, top, right, bottom = box
        top, bottom = min(top, bottom), max(top, bottom)
        margin = _INLINE_MATH_BOX_TOLERANCE
        for line in page.get("lines") or []:
            inside = []
            for span in line.get("spans") or []:
                x0, y0, x1, y1 = span["bbox"]
                x, y = (x0 + x1) / 2, (y0 + y1) / 2
                if left - margin <= x <= right + margin and top - margin <= y <= bottom + margin:
                    inside.append(TextSpan.from_dict(span))
            if inside:
                lines.append(inside)
    return lines


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
        box = _top_left_box(located[1], page, spans, heights)
        if box is None:
            continue
        left, top, right, bottom = box
        top, bottom = min(top, bottom), max(top, bottom)
        margin = _OVERLAY_HOST_TOLERANCE * 2
        if left - margin <= x <= right + margin and top - margin <= y <= bottom + margin:
            overlay.metadata["negation_overlay"] = {"outcome": "inline-math", "host": host.id}
            return


async def _enrich_formula_latex(
    manifest: ProcessingManifest,
    source_file: Path,
    *,
    mode: str,
    status_callback: Callable[[str], Coroutine[Any, Any, None]] | None = None,
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

    formulas = [
        element
        for element in manifest.elements
        if element.type == "formula" and not has_latex_markup(element.text)
    ]
    if not formulas:
        return
    # Without a page to render there is no crop to recognize. DOCX/PPTX
    # formulas stay as the extractor delivered them instead of paying one
    # failed render per formula.
    if manifest.source.media_type not in _RENDERABLE_MEDIA_TYPES:
        return

    if status_callback:
        await status_callback(t(STAGE_ENRICHING_FORMULAS))

    vision = VisionAgent(mode=mode)
    total_pages = len(manifest.pages)
    artifact_id = _source_artifact_id(manifest)
    slots = asyncio.Semaphore(max(1, settings.vision_concurrency))
    progress_lock = asyncio.Lock()
    math_probe = asyncio.Lock()
    math_ready = asyncio.Event()
    math_available = True
    # Resolved like ``ToolboxCapabilityClient``: an empty setting means the
    # registry default, which is the provider the request actually asked.
    recognize_provider = settings.toolbox_math_recognize_provider or provider_default(
        "toolbox_math_recognize_provider"
    )
    empty_answers = 0

    async def call(image_bytes: bytes) -> list[dict[str, Any]]:
        """One recognition call; an outage turns the flag off and means no LaTeX."""
        nonlocal math_available
        try:
            return await run_blocking(
                toolbox_recognize_formula,
                image_bytes,
                raise_on_unavailable=True,
            )
        except MathCapabilityUnavailable as exc:
            math_available = False
            # The full message names the provider and its HTTP status; the
            # class alone ("ToolboxError") hides a failing sidecar.
            logger.warning(t(LOG_PDDL_FORMULA_RECOGNIZE_UNAVAILABLE).format(error=exc))
            return []

    async def recognize(image_bytes: bytes) -> list[dict[str, Any]]:
        """Recognize one crop, unless the document already found the outage.

        The first call is serialized and every other crop waits for its
        answer, so a batch that starts with the capability down pays the
        outage once instead of once per crop; after it succeeds, the remaining
        calls only read the flag and run concurrently.
        """
        if not math_ready.is_set():
            async with math_probe:
                if not math_ready.is_set():
                    try:
                        return await call(image_bytes)
                    finally:
                        math_ready.set()
        if not math_available:
            return []
        return await call(image_bytes)

    async def enrich_one(position: int, element: ManifestElement) -> bool:
        """Recognize one formula and fold the answer into it; True when filled."""
        nonlocal empty_answers
        async with slots:
            if status_callback:
                async with progress_lock:
                    await status_callback(
                        t(STAGE_RECOGNIZING_FORMULA).format(
                            current=position,
                            total=len(formulas),
                            pages=_pages_label([element.page_number], total_pages),
                        )
                    )
            image_bytes, page_number = await run_blocking(
                _formula_recognition_crop,
                source_file,
                element,
                artifact_id=artifact_id,
                media_type=manifest.source.media_type,
            )
            if not image_bytes:
                return False

            original_text = element.text or ""
            text_layer = normalize_latex(original_text)
            # None records a recognition refused for lack of evidence.
            rejected: dict[str, float | None] = {}
            agreement: float | None = None

            def accept(method: str, latex: str) -> str:
                """``latex`` when it agrees with the text layer, else ``""``.

                With text-layer text but no visible symbol on either side
                (``()``), there is no evidence the recognition read the same
                formula, so it is refused like a disagreement.
                """
                nonlocal agreement
                if not latex or not text_layer:
                    return latex
                score = latex_text_agreement(latex, text_layer)
                if score is None or score < settings.formula_text_agreement_min:
                    rejected[method] = None if score is None else round(score, 3)
                    return ""
                agreement = round(score, 3)
                return latex

            # Every candidate gets its turn at the gate before vision is paid:
            # a lower-ranked one that agrees with the text layer is still a
            # recognition of this crop. Refusals are recorded per rank
            # ("math.recognize", "math.recognize#2", ...).
            method = "math.recognize"
            latex = ""
            confidence = None
            accepted_rank = 1
            candidates = _ranked_formula_candidates(await recognize(image_bytes))
            if not candidates and math_available:
                # An outage already warned once and skips this. An empty list
                # is usually an answer without LaTeX, which nothing else
                # records; a rejected crop or a transport error reaches it too,
                # but those were logged by ``toolbox_recognize_formula``. No
                # await separates ``recognize`` from this check, so the flag
                # and the counter cannot race with sibling crops.
                empty_answers += 1
                logger.debug(
                    t(LOG_PDDL_FORMULA_RECOGNIZE_EMPTY).format(
                        element_id=element.id, page=page_number, provider=recognize_provider,
                    )
                )
            for rank, candidate in enumerate(candidates, start=1):
                latex = accept(method if rank == 1 else f"{method}#{rank}", candidate["latex"])
                if latex:
                    confidence = candidate["confidence"]
                    accepted_rank = rank
                    break

            if not latex:
                method = "vision"
                output = await vision.describe_region(
                    image_bytes=image_bytes,
                    classification="formula",
                    page_num=page_number,
                    total_pages=total_pages,
                    mode=mode,
                    full_budget=True,
                )
                if output is not None and output.kind == "formula":
                    latex = accept(method, normalize_latex(output.formula_latex or ""))
                    confidence = output.confidence

        if rejected:
            logger.info(
                t(LOG_PDDL_FORMULA_TEXT_LAYER_DISAGREES).format(
                    element_id=element.id, page=page_number, rejected=rejected,
                )
            )
        if not latex:
            if rejected:
                element.metadata["formula_recognition"] = {
                    "method": "text-layer",
                    "rejected": rejected,
                }
            return False
        recognition: dict[str, Any] = {"method": method, "confidence": confidence}
        if method == "math.recognize" and accepted_rank > 1:
            recognition["rank"] = accepted_rank
        if text_layer:
            # The replaced text exactly as the extractor delivered it.
            element.metadata["formula_text_layer"] = original_text
            recognition["text_agreement"] = agreement
        if rejected:
            recognition["rejected"] = rejected
        element.text = latex
        element.metadata["formula_recognition"] = recognition
        return True

    # The fold above touches only its own element and runs without awaits, so
    # concurrent folds cannot interleave. The TaskGroup cancels the sibling
    # crops when one of them fails and re-raises as an ExceptionGroup, like the
    # picture descriptions; no task keeps mutating the manifest after it failed.
    async with asyncio.TaskGroup() as group:
        tasks = [
            group.create_task(enrich_one(position, element))
            for position, element in enumerate(formulas, start=1)
        ]
    recognized = sum(task.result() for task in tasks)

    if recognized:
        logger.info(t(LOG_PDDL_FORMULAS_RECOGNIZED).format(count=recognized))
    if empty_answers:
        logger.info(
            t(LOG_PDDL_FORMULAS_FELL_BACK_TO_VISION).format(
                count=empty_answers, total=len(formulas), provider=recognize_provider,
            )
        )


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
) -> None:
    from backend.config.settings import settings

    # A table read in the wrong shape (rows collapsed into one, cells doubled)
    # has structure but not the right one; it is read again from its image.
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
    if not table_elements:
        return

    data_agent = DataAgent()
    enriched = 0
    for position, element in enumerate(table_elements, start=1):
        reason = garbled.get(element.id)
        if reason is None and _backfill_table_from_existing_text(element):
            enriched += 1
            continue

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
                _keep_misread_table(element, page_number, reason, "no image of the table", 0)
            continue

        # A misread table gets a few readings: the model may drop columns or
        # rows on one try and read the table whole on the next.
        attempts = _TABLE_REREAD_ATTEMPTS if reason is not None else 1
        table_output = None
        answered = False
        why = "no table was read"
        for attempt in range(1, attempts + 1):
            candidate = await data_agent.process_region(
                image_bytes=image_bytes,
                classification="table",
                page_num=page_number,
                fallback_text=element.text or "",
            )
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
        if table_output is None:
            # A reading refused as worse than the table, or an answer that it
            # is not a table, is the model's answer; only no answer at all is
            # a failure a rerun may not repeat.
            if not answered:
                _record_table_read_failure(element, "model_failed")
            if reason is not None:
                _keep_misread_table(element, page_number, reason, why, attempt)
            continue

        element.metadata.pop("table_read_failure", None)
        rows = table_output.table_rows()
        table_ast = table_output.table_ast()
        if reason is not None:
            element.metadata["table_ast_replaced"] = element.metadata["table_ast"]
            element.metadata["table_review"] = {
                "reason": reason, "outcome": "replaced", "attempts": attempt,
            }
            logger.info(
                t(LOG_PDDL_TABLE_REREAD_ACCEPTED).format(
                    element_id=element.id, page=page_number, reason=reason,
                )
            )

        element.metadata["table_ast"] = table_ast
        element.metadata["table_linearization_hint"] = "data-agent-structured"
        element.metadata["table_row_count"] = len(rows)
        element.metadata["table_column_count"] = _table_ast_column_count(table_ast)
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
        enriched += 1

    if enriched:
        logger.info(t(LOG_PDDL_TABLES_ENRICHED).format(count=enriched))


#: Why a table was left unread, recorded in metadata["table_read_failure"]: the
#: crop could not be rendered, or the data agent returned no answer at all.
TableReadFailure = Literal["crop_unavailable", "model_failed"]


def _record_table_read_failure(element: ManifestElement, reason: TableReadFailure) -> None:
    """Mark ``element`` as a table no reading came back for, and say why."""
    element.metadata["table_read_failure"] = reason


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


def _table_element_has_structured_content(element: ManifestElement) -> bool:
    metadata = element.metadata or {}
    table_ast = metadata.get("table_ast")
    if not isinstance(table_ast, dict):
        return False

    rows = _rows_from_table_ast(table_ast)
    if not rows:
        return False

    width = max((len(row) for row in rows), default=0)
    if len(rows) >= 2 and width >= 2:
        return True

    return not _rows_look_like_placeholder(rows)


def _table_ast_column_count(table_ast: dict[str, Any]) -> int:
    """Return the widest logical section, including cell spans."""
    widths: list[int] = []
    for section_name in ("header", "body", "footer"):
        section = table_ast.get(section_name)
        if isinstance(section, list):
            widths.append(effective_section_width(section))
    return max(widths, default=0)


def _backfill_table_from_existing_text(element: ManifestElement) -> bool:
    text = (element.text or "").strip()
    if not text:
        return False

    rows = _rows_from_visual_table_text(text)
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


def _rows_from_visual_table_text(raw_text: str) -> list[list[str]]:
    text = raw_text.strip()
    if not text:
        return []

    rows = _rows_from_pipe_table(text)
    if rows:
        return rows

    rows = _rows_from_delimited_lines(text, delimiter="\t")
    if rows:
        return rows

    semicolon_rows = _rows_from_delimited_lines(text, delimiter=";")
    comma_rows = _rows_from_delimited_lines(text, delimiter=",")
    if _score_rows(semicolon_rows) >= _score_rows(comma_rows):
        return semicolon_rows
    return comma_rows


def _rows_from_pipe_table(text: str) -> list[list[str]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    rows: list[list[str]] = []
    for line in lines:
        if "|" not in line:
            continue
        if _looks_like_markdown_separator(line):
            continue
        cleaned = line.strip().strip("|")
        cells = [cell.strip() for cell in cleaned.split("|")]
        cells = [cell for cell in cells if cell]
        if len(cells) >= 2:
            rows.append(cells)
    if _score_rows(rows) >= 4:
        return rows
    return []


def _rows_from_delimited_lines(text: str, *, delimiter: str) -> list[list[str]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    rows: list[list[str]] = []
    for line in lines:
        if delimiter not in line:
            continue
        if "|" in line and delimiter != "|":
            continue
        cells = [cell.strip() for cell in line.split(delimiter)]
        cells = [cell for cell in cells if cell]
        if len(cells) >= 2:
            rows.append(cells)
    if _score_rows(rows) >= 4:
        return rows
    return []


def _looks_like_markdown_separator(line: str) -> bool:
    cleaned = line.strip().strip("|").replace(" ", "")
    if not cleaned:
        return False
    parts = cleaned.split("|")
    if not parts:
        return False
    return all(re.fullmatch(r":?-{2,}:?", part or "") for part in parts)


def _score_rows(rows: list[list[str]]) -> int:
    if not rows:
        return 0
    row_count = len(rows)
    width = max((len(row) for row in rows), default=0)
    return row_count * width


def _rows_look_like_placeholder(rows: list[list[str]]) -> bool:
    if len(rows) != 1 or len(rows[0]) != 1:
        return False
    return rows[0][0].strip().lower() == "tabela detectada"


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
    """
    from acessilia_sdk.toolbox import ToolboxCapabilityError, ToolboxIncompatibleEndpoint

    provenance = element.provenance[0] if element.provenance else None
    page_number = provenance.page_number if provenance is not None else (fallback_page_number or 0)
    if page_number < 1:
        return None, 0

    def render(clip=None, origin: ClipOrigin = "TOPLEFT") -> RenderedPage:
        return _toolbox_render(
            source_file, page_number, media_type=media_type, dpi=160, clip=clip,
            clip_origin=origin, artifact_id=artifact_id,
        )

    clip, origin = _picture_clip(provenance)
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


def _picture_clip(
    provenance: Any,
) -> tuple[tuple[float, float, float, float] | None, ClipOrigin]:
    """The box of a picture to render, and its origin; ``None`` means the whole page.

    Pictures are best effort, so a box that cannot be used (absent or with a
    non-finite coordinate) degrades to the whole page instead of failing, and
    the origin may be inferred (``is_bottom_left``). Region inspection, which
    certifies its crop, refuses both instead.
    """
    bbox = getattr(provenance, "bbox", None)
    if bbox is None:
        return None, "TOPLEFT"
    left, top, right, bottom = (
        float(bbox.left), float(bbox.top), float(bbox.right), float(bbox.bottom)
    )
    if not all(math.isfinite(value) for value in (left, top, right, bottom)):
        return None, "TOPLEFT"
    origin: ClipOrigin = (
        "BOTTOMLEFT"
        if is_bottom_left(getattr(bbox, "coord_origin", None), top, bottom)
        else "TOPLEFT"
    )
    return (left, top, right, bottom), origin

def _is_mostly_visual_manifest(manifest: ProcessingManifest) -> bool:
    for element in manifest.elements:
        if element.type in {"heading", "title", "paragraph", "list_item", "table", "code", "formula"}:
            text = (element.text or "").strip()
            if text and not _is_placeholder_text(text) and not _is_ocr_noise(text):
                return False
    return True


def _is_ocr_noise(text: str) -> bool:
    """Retorna True se o texto parece ser ruído de OCR (muito curto, sem
    estrutura de linguagem natural), não devendo ser considerado como
    conteúdo textual significativo para efeitos de detecção de manifesto
    majoritariamente visual."""
    normalized = text.strip()
    if not normalized:
        return True
    # Texto muito curto (≤4 caracteres) é quase sempre OCR noise
    if len(normalized) <= 4:
        return True
    # Texto sem espaços e com ≤8 caracteres também é suspeito
    if " " not in normalized and len(normalized) <= 8:
        return True
    return False


def _is_placeholder_visual_element(element: ManifestElement) -> bool:
    if is_unstructured_page_placeholder(element):
        # Inspected by the planned vision-page-inspection method instead.
        return False
    if element.type not in {"group", "unknown", "paragraph"}:
        return False
    text = (element.text or "").strip()
    raw_label = (element.raw_label or "").strip().lower()
    return (not text) or _is_placeholder_text(text) or _is_ocr_noise(text) or raw_label in {"body", "unspecified", "group"}


def _is_placeholder_text(text: str) -> bool:
    normalized = text.strip().lower()
    return normalized in {"body", "_root_", "root", "unspecified", "group"}


def _has_meaningful_text(element: ManifestElement) -> bool:
    """Retorna True se o elemento contém texto significativo (não é OCR noise
    nem placeholder). Usado para filtrar elementos do tipo 'picture' que já
    vieram com descrição textual válida do extrator."""
    text = (element.text or "").strip()
    if not text:
        return False
    if _is_placeholder_text(text):
        return False
    if _is_ocr_noise(text):
        return False
    return True


#: Obligation kinds that only refine content the extraction already delivered.
#: Leaving one open (every automatic method failed and it was escalated to
#: human review) does not lose content, so the job finishes with a warning
#: instead of failing. Heading levels are also normalized by the canonical
#: builder, which keeps the exported document valid without the repair.
#: `refine-reading-order` is deliberately absent: a wrong reading order is what
#: a screen reader user hits first, so an open one still fails the job.
NON_CRITICAL_OBLIGATION_KINDS = frozenset(
    {
        # The adjudication verdict is recorded but cannot be applied (a page
        # swap would reopen the manifest mid-plan), and the extracted content
        # is complete either way, so a verdict for the secondary provider must
        # not fail the job.
        "adjudicate-page",
        "repair-heading-hierarchy",
        "join-tail-blocks",
        "normalize-text",
        "repair-legacy-unicode",
        "chunk-verse",
        "extract-line-numbers",
        # No handler implements `rescue-omitted` yet, so its only path is
        # human review: as a critical kind it failed every dual-fusion job
        # with an omitted block. The content the primary provider extracted
        # is delivered and the result e-mail names the pages of the omitted
        # block. Remove the kind from here once the handler lands (#236).
        "rescue-omitted-block",
        # The vision model is the only automatic method, and a degenerate
        # answer repeats on every try: in 006.pdf two images out of 40 failed
        # a 42-page document. The picture is exported with the generic alt
        # text and the result e-mail names its page. Unless no picture at all
        # was described: see _blocks_delivery.
        "describe-image",
    }
)


def _formula_has_readable_content(
    obligation: Obligation, manifest: ProcessingManifest
) -> bool:
    """Whether every target formula still carries something readable.

    A formula the Toolbox could not verbalize or normalize is exported as its
    LaTeX: the canonical builder and the renderers fall back to it when
    ``math.verbalize`` is unavailable or rejects the input, so the document
    keeps the content. That is a degradation, not a lost document. A formula
    with neither LaTeX, a normalized LaTeX, MathML nor a verbalization has
    nothing to deliver, so its obligation stays critical.
    """
    targets = _formula_elements_for_obligation(manifest, obligation.id)
    return bool(targets) and all(
        bool(normalize_latex(element.text or ""))
        or bool(str(element.metadata.get("latex_normalized") or "").strip())
        or bool(str(element.metadata.get("mathml") or "").strip())
        or bool(str(element.metadata.get("verbalization") or "").strip())
        for element in targets
    )


def _blocks_delivery(obligation: Obligation, manifest: ProcessingManifest) -> bool:
    """Whether an open obligation fails the job instead of leaving a warning.

    ``describe-image`` is non-critical while some picture was described: a few
    degenerate answers are sampling (2 of 40 in 006.pdf). With none described,
    the model is unreachable or misconfigured (``describe_region`` turns a
    timeout or an auth error into ``None``), and every picture would silently
    get the generic alt text, so the job fails. A document with a single
    picture its one description failed on fails too.

    ``verbalize-formula`` and ``normalize-formula`` are non-critical while the
    target formulas keep their LaTeX: without MathML or spoken text the exported
    document still shows the formula source, and the result e-mail names the
    page. With no readable content at all there is nothing to deliver, so the
    obligation fails the job.
    """
    if obligation.kind == "describe-image":
        return not any(
            other.kind == "describe-image" and other.status == "satisfied"
            for other in manifest.obligations
        )
    if obligation.kind in {"verbalize-formula", "normalize-formula"}:
        return not _formula_has_readable_content(obligation, manifest)
    return obligation.kind not in NON_CRITICAL_OBLIGATION_KINDS


def _is_open_obligation(obligation: Obligation) -> bool:
    """Whether the job selected the obligation and left it unsatisfied.

    An exhausted obligation is left out of later replans, which clears its
    `selected` flag; its `failed` status keeps it open.
    """
    return obligation.status != "satisfied" and (
        obligation.selected or obligation.status == "failed"
    )


def _unsatisfied_selected_obligations(manifest: ProcessingManifest) -> list:
    return [
        obligation for obligation in manifest.obligations
        if _is_open_obligation(obligation)
    ]


def _replannable_obligation_ids(manifest: ProcessingManifest) -> list[str]:
    """Open selected obligations that a new plan can still satisfy.

    Exhausted obligations, and those depending on one, are excluded: the planner
    rejects an obligation without an untried admissible method.
    """
    by_id = {obligation.id: obligation for obligation in manifest.obligations}

    def blocked(obligation_id: str, seen: set[str]) -> bool:
        if obligation_id in seen:
            return False
        seen.add(obligation_id)
        obligation = by_id[obligation_id]
        if obligation.status == "failed":
            return True
        return any(blocked(dependency, seen) for dependency in obligation.dependencies)

    return [
        obligation.id for obligation in manifest.obligations
        if obligation.selected
        and obligation.status != "satisfied"
        and not blocked(obligation.id, set())
    ]


def _unsatisfied_summary(manifest: ProcessingManifest) -> str:
    """The open obligations grouped by kind with their pages.

    "refine-reading-order (pages 1, 7, 11); describe-image (page 18)" instead of
    one id per obligation, each listing every target element.
    """
    pages: dict[str, set[int]] = {}
    unknown: set[str] = set()
    for obligation in _unsatisfied_selected_obligations(manifest):
        numbers = {
            page for page in _obligation_pages(manifest, obligation.id) if page
        }
        pages.setdefault(obligation.kind, set()).update(numbers)
        if not numbers:
            unknown.add(obligation.kind)
    groups = []
    for kind, numbers in pages.items():
        labels = [_pages_label(numbers)] if numbers else []
        if kind in unknown:
            labels.append(t(STAGE_PAGE_UNKNOWN))
        groups.append(f"{kind} ({', '.join(labels)})")
    return t(EXE_COMPLETED_OBLIGATIONS_UNSATISFIED).format(unsatisfied="; ".join(groups))


def _pages_label(
    pages: Iterable[int | None], total_pages: int | None = None
) -> str:
    """Localized location of a unit of work, e.g. "page 3" or "pages 3, 4".

    When the document's page count is known and the work sits on a single page,
    the label also names the total, e.g. "page 3 of 12": progress messages pair
    that with image or step counters ("image 11 of 37 (page 18 of 42)"), and
    without the total users could read 37 as the page count. Single-page
    documents keep the plain "page 1" label because "of 1" adds nothing.
    """
    numbers = sorted({page for page in pages if page})
    if not numbers:
        return t(STAGE_PAGE_UNKNOWN)
    if len(numbers) == 1:
        if total_pages is not None and total_pages > 1:
            return t(STAGE_PAGE_OF).format(page=numbers[0], total_pages=total_pages)
        return t(STAGE_PAGE).format(page=numbers[0])
    return t(STAGE_PAGES).format(pages=", ".join(str(page) for page in numbers))


def _obligation_pages(manifest: ProcessingManifest, obligation_id: str) -> list[int | None]:
    obligation = next(
        (item for item in manifest.obligations if item.id == obligation_id), None
    )
    if obligation is None:
        return []
    page_by_element = {element.id: element.page_number for element in manifest.elements}
    return [page_by_element.get(target) for target in obligation.target_ids]


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


def build_pddl_structured_payload(
    *,
    file_path: Path,
    manifest: ProcessingManifest,
    plan: NominalPlan,
    planner_backend: str,
    execution_report: ExecutionReport | None,
    comparison: PlanningComparison | None,
    toolbox_availability: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pages_payload = _manifest_pages_to_payload(manifest)
    text_output = _render_text_from_pages(pages_payload)
    configuration = manifest.extractor.configuration
    media_inspection_status = configuration.get("media_inspection")
    fusion_status = configuration.get("fusion") or {}
    unsatisfied_obligations = _unsatisfied_obligations(manifest)

    technical_warnings: list[str] = []
    if fusion_status.get("status") == "degraded":
        technical_warnings.append("Fusão dual incompleta: falha do provedor secundário; reexecução necessária.")
    if execution_report is None:
        technical_warnings.append(
            "Executor nao foi executado; somente manifesto e plano foram gerados."
        )
    elif execution_report.status in {
        "failed", "replan-required",
    } or unsatisfied_obligations:
        # A replan that leaves an exhausted refinement out can still report
        # `completed`; the open obligation must reach the document anyway. The
        # ids are in `pddl_unsatisfied_obligations`, so the warning stays short.
        technical_warnings.append(_unsatisfied_summary(manifest))

    if comparison is not None:
        technical_warnings.append(
            f"Comparacao de planners: {comparison.comparison.verdict}."
        )

    visual_failures = _visual_failures(manifest)
    for kind, msgids in (("pictures", MSG_PICTURES_NOT_DESCRIBED), ("tables", MSG_TABLES_NOT_READ)):
        if count := sum((visual_failures or {}).get(kind, {}).values()):
            technical_warnings.append(n(*msgids, count).format(count=count))

    observations = getattr(manifest, "observations", [])
    obligations = getattr(manifest, "obligations", [])
    if any(
        observation.kind == "repair-legacy-unicode-detected"
        for observation in observations
    ) and not any(
        obligation.kind == "repair-legacy-unicode"
        for obligation in obligations
    ):
        # Only the observation exists: LEGACY_UNICODE_REPAIR=detect. The
        # warning names the switch because the job delivers the text as
        # extracted, NFD and dotless-i included.
        technical_warnings.append(
            "Texto com sinais de Unicode legado (NFD, i sem ponto ou acento espaçador); "
            "reparo desabilitado (LEGACY_UNICODE_REPAIR=detect)."
        )

    return {
        "text": text_output,
        "pages": pages_payload,
        "page_count": len(pages_payload),
        "mode": f"pddl-{planner_backend}",
        "source_path": str(file_path),
        "canonical_metadata": {
            "pipeline_engine": "pddl",
            "pddl_validation_only": True,
            "accessibility_verified": False,
            "pddl_manifest_id": manifest.manifest_id,
            "pddl_manifest_revision": manifest.revision,
            "pddl_plan_id": plan.plan_id,
            "pddl_planner": plan.planner,
            "pddl_expected_total_cost": plan.expected_total_cost,
            "pddl_execution_id": execution_report.execution_id
            if execution_report
            else None,
            "pddl_execution_status": execution_report.status
            if execution_report
            else None,
            "pddl_comparison_verdict": comparison.comparison.verdict
            if comparison
            else None,
            "pddl_unsatisfied_obligations": unsatisfied_obligations,
            # The open obligations a delivered document still has, for the
            # result e-mail: the job page and e-mail show no technical warning.
            "pddl_unsatisfied_summary": _unsatisfied_summary(manifest)
            if unsatisfied_obligations
            else None,
            "pddl_toolbox_availability": toolbox_availability,
            "pddl_fusion": fusion_status or None,
            # Pictures and tables left undescribed or unread, by reason; a rerun
            # once the model provider or the Toolbox is back may deliver them.
            "pddl_visual_failures": visual_failures,
            "pddl_media_inspection": {
                "status": media_inspection_status,
                "error": configuration.get("media_inspection_error"),
                # Why a deck was structured slide by slide (or not).
                "document_genre": configuration.get("document_genre"),
                "genre_signals": configuration.get("genre_signals", []),
            }
            if media_inspection_status is not None
            else None,
        },
        "technical_warnings": technical_warnings,
        # A step degraded by a Toolbox or model failure must not be replayed
        # from the cache once the service is back.
        "cacheable": (
            media_inspection_status != "failed"
            and fusion_status.get("status") != "degraded"
            and execution_report is not None
            and execution_report.status in {"completed", "dry-run-completed"}
            and not any(
                item["recovery"] != "human-review" for item in unsatisfied_obligations
            )
            and not records_visual_failures(visual_failures)
        ),
    }


#: Why a picture or table left without a description or a reading may come
#: out differently on a rerun: the model provider or the Toolbox was down. An
#: empty description is the model's answer, as is a refused table reading, and
#: would come back the same, so it neither counts nor keeps a run uncached.
_RETRYABLE_VISUAL_FAILURES = frozenset({"crop_unavailable", "model_failed"})


def _visual_failures(manifest: ProcessingManifest) -> dict[str, dict[str, int]] | None:
    """Pictures left undescribed and tables left unread, counted by reason.

    A picture counts whatever its type: the vision stage also describes the
    placeholders of a mostly visual document, and an element becomes a
    ``picture`` only once the model answers. None when nothing failed.
    """
    elements = getattr(manifest, "elements", [])
    counts = {
        "pictures": Counter(
            reason for element in elements
            if (reason := element.metadata.get("vision_failure_reason")) in _RETRYABLE_VISUAL_FAILURES
        ),
        "tables": Counter(
            reason for element in elements
            if (reason := element.metadata.get("table_read_failure")) in _RETRYABLE_VISUAL_FAILURES
        ),
    }
    failures = {kind: dict(by_reason) for kind, by_reason in counts.items() if by_reason}
    return failures or None


def records_visual_failures(failures: Any) -> bool:
    """Whether ``canonical_metadata.pddl_visual_failures`` records any failure.

    A run that does is not cached, and a cached entry that does is not
    replayed; both sides read the record through this one check.
    """
    return isinstance(failures, dict) and any(
        isinstance(by_reason, dict)
        and any(isinstance(count, int) and count > 0 for count in by_reason.values())
        for by_reason in failures.values()
    )


def _unsatisfied_obligations(manifest: ProcessingManifest) -> list[dict[str, Any]]:
    """Selected obligations the execution left unsatisfied.

    `pddl_execution_status` alone does not say which obligations were exhausted
    or escalated, so each one is reported with its last attempt. An obligation
    whose last attempt is `human-review` is a pending escalation.
    """
    unsatisfied: list[dict[str, Any]] = []
    for obligation in manifest.obligations:
        if not _is_open_obligation(obligation):
            continue
        last = obligation.attempts[-1] if obligation.attempts else None
        unsatisfied.append(
            {
                "id": obligation.id,
                "kind": obligation.kind,
                "status": obligation.status,
                "target_ids": list(obligation.target_ids),
                "last_method": last.method if last else None,
                "last_message": last.message if last else None,
                "escalated": bool(last and last.method == "human-review"),
                "recovery": (
                    "human-review" if last and last.method == "human-review"
                    and obligation.kind in NON_CRITICAL_OBLIGATION_KINDS else "retry"
                ),
            }
        )
    return unsatisfied


def _is_left_out_of_payload(element: ManifestElement) -> bool:
    """A page accepted as blank, or a placeholder not yet inspected, adds nothing.

    Nor does a detached negation slash: it was given back to its relation, or
    could not be, and alone it says nothing to a reader.

    An inspected page with content is a ``picture``, no longer a placeholder.
    A placeholder still present means the inspection did not run (dry-run), so
    the page contributes no block rather than its raw label.
    """
    return (
        bool(element.metadata.get("blank_page"))
        or bool(element.metadata.get("negation_overlay"))
        or is_unstructured_page_placeholder(element)
    )


#: Types a page number can arrive as. A number inside a table, list, heading
#: or formula is content, wherever it sits on the page.
_PAGE_NUMBER_TYPES = frozenset({"paragraph", "page_header", "page_footer", "unknown"})
#: Share of the page height at the top and at the bottom where a lone number
#: is read as a page number (the margin `docstruct.fusion.noise.decor_role`
#: uses for the same decision).
_PAGE_NUMBER_MARGIN = 0.12
#: Longest furniture text read as a decorated page number (``- 5 -``,
#: ``Page 5``), as in `decor_role`.
_PAGE_NUMBER_MAX_LEN = 16


def _is_decorated_page_number(text: str) -> bool:
    """A page number with the decoration or repetition extractors leave on it.

    Accepts ``- 5 -``, ``5.`` and ``Page 5`` (``PAGENUM_RE``, the matcher of
    `decor_role`) and the same number repeated (``281 281``), but only digits
    and the Roman letters `is_page_number` knows, so ``mid`` is not a number.
    """
    text = text.strip()
    match = PAGENUM_RE.match(text) if len(text) <= _PAGE_NUMBER_MAX_LEN else None
    if match and _is_page_number(match.group(1)):
        return True
    tokens = set(text.split())
    return len(tokens) == 1 and _is_page_number(tokens.pop())


def _is_marked_furniture(element: ManifestElement) -> bool:
    """Whether the extractor marked ``element`` as page header/footer.

    Read from the type, the raw label (an element typed ``paragraph`` may keep
    ``page_footer`` there) or Docling's ``content_layer``.
    """
    return (
        _element_role(element) in {"header", "footer", "page_number"}
        or reading_role(str(element.type), str(element.raw_label)) != "body"
        or element.metadata.get("content_layer") == "furniture"
    )


def _is_page_number_in_margin(
    element: ManifestElement, manifest: ProcessingManifest
) -> bool:
    """A bare number in the top or bottom margin, which may be a page number.

    A single uppercase Roman letter (``I``, ``V``, ``X``...) is read as text.
    """
    text = (element.text or "").strip()
    if not _is_page_number(text) or (len(text) == 1 and text.isupper()):
        return False
    bbox = _element_bbox(element, manifest)
    if bbox is None:
        return False
    center = (bbox[1] + bbox[3]) / 2
    return not _PAGE_NUMBER_MARGIN <= center <= 1 - _PAGE_NUMBER_MARGIN


def _page_number_ids(manifest: ProcessingManifest) -> set[str]:
    """Elements that are page numbers rather than body text.

    A screen reader would announce them in the middle of the text. A number
    the extractor marked as furniture is one. Otherwise only its position in
    the top or bottom margin tells it apart from a number of the body, and a
    page has one page number: the margin decides only on a page without a
    marked one and with a single candidate, so chart axis labels or a footnote
    marker next to the page number stay.
    """
    marked: set[str] = set()
    #: page number -> its page number candidates, marked or in the margin.
    candidates: dict[int, list[str]] = {}
    for element in manifest.elements:
        if element.type not in _PAGE_NUMBER_TYPES:
            continue
        page = element.page_number or 1
        if _is_marked_furniture(element):
            if _is_decorated_page_number(element.text or ""):
                marked.add(element.id)
                candidates.setdefault(page, []).append(element.id)
        elif _is_page_number_in_margin(element, manifest):
            candidates.setdefault(page, []).append(element.id)
    for ids in candidates.values():
        if len(ids) == 1:
            marked.update(ids)
    return marked


#: Height share of the page by which a picture may miss a header line and
#: still sit beside it (the line's box is tighter than the logo's).
_LETTERHEAD_TOLERANCE = 0.01
#: Width share of the page a header line may stand away from the picture and
#: still be beside it; a running header across the page is not.
_LETTERHEAD_MAX_GAP = 0.05
#: Tallest picture, as a share of the page height, read as a logo: a figure
#: crossing the header band is content, and keeps its description.
_LETTERHEAD_MAX_HEIGHT = _PAGE_NUMBER_MARGIN


def _is_page_header_line(
    element: ManifestElement, bbox: tuple[float, ...]
) -> bool:
    """A non-empty line the extractor marked as page header.

    Read from the type and raw label, like the page number filter. Docling's
    ``content_layer`` does not tell header from footer, so a ``furniture``
    line counts only in the top margin.
    """
    if not (element.text or "").strip():
        return False
    if (
        _element_role(element) == "header"
        or reading_role(str(element.type), str(element.raw_label)) == "header"
    ):
        return True
    return (
        element.metadata.get("content_layer") == "furniture"
        and (bbox[1] + bbox[3]) / 2 < _PAGE_NUMBER_MARGIN
    )


def _is_beside(picture_box: tuple[float, ...], line_box: tuple[float, ...]) -> bool:
    """Whether a header line overlaps the picture's height and stands next to it."""
    horizontal_gap = max(line_box[0] - picture_box[2], picture_box[0] - line_box[2])
    return (
        line_box[1] <= picture_box[3] + _LETTERHEAD_TOLERANCE
        and picture_box[1] <= line_box[3] + _LETTERHEAD_TOLERANCE
        and horizontal_gap <= _LETTERHEAD_MAX_GAP
    )


def _letterhead_groups(
    manifest: ProcessingManifest, page_numbers: set[str]
) -> dict[str, list[ManifestElement]]:
    """Logos and the page header lines beside them, keyed by the first in reading order.

    An institutional header ("University of X / Department of Y" next to the
    logo) reaches the manifest as page_header lines and an unrelated picture,
    so the reader got the lines apart and a long description of a logo that
    repeats them. A logo-sized picture joins the header lines beside it; two
    pictures form one group only when they share a line, so two institutions'
    headers on a page stay apart. A page header without a picture is left as is.
    """
    #: page number -> its header lines and logo-sized pictures, with their boxes.
    lines: dict[int, list[tuple[ManifestElement, tuple[float, ...]]]] = {}
    pictures: dict[int, list[tuple[ManifestElement, tuple[float, ...]]]] = {}
    for element in manifest.elements:
        if _is_left_out_of_payload(element) or element.id in page_numbers:
            continue
        bbox = _element_bbox(element, manifest)
        if bbox is None:
            continue
        page = element.page_number or 1
        if element.type == "picture":
            if bbox[3] - bbox[1] <= _LETTERHEAD_MAX_HEIGHT:
                pictures.setdefault(page, []).append((element, bbox))
        elif _is_page_header_line(element, bbox):
            lines.setdefault(page, []).append((element, bbox))

    groups: dict[str, list[ManifestElement]] = {}
    for page, page_pictures in pictures.items():
        components: list[dict[str, ManifestElement]] = []
        for picture, picture_box in page_pictures:
            beside = [
                line
                for line, line_box in lines.get(page, [])
                if _is_beside(picture_box, line_box)
            ]
            if not beside:
                continue
            component = {picture.id: picture}
            component.update((line.id, line) for line in beside)
            for other in [item for item in components if item.keys() & component.keys()]:
                component.update(other)
                components.remove(other)
            components.append(component)
        for component in components:
            ordered = sorted(component.values(), key=lambda item: item.reading_order)
            groups[ordered[0].id] = ordered
    return groups


def _letterhead_block(
    members: list[ManifestElement], language: str | None
) -> dict[str, Any]:
    """One paragraph for a logo and its header lines, in place of the first of them.

    The paragraph replaces the picture too: the outputs never showed the
    logo's pixels (Pandoc writes an image block as a paragraph of its alt
    text), only the description this paragraph stands for. The text is in
    the document's language, not the interface's. ``role`` and
    ``letterhead_members`` record the merge for audit; no renderer reads
    them, so the PDF/UA tag stays ``P``.
    """
    block = _element_to_block(members[0])
    lines = [
        (member.text or "").strip().rstrip(".,;")
        for member in members
        if member.type != "picture"
    ]
    token = set_request_locale(locale_for_user(language))
    try:
        template = t(MSG_LETTERHEAD_TEXT)
    finally:
        reset_request_locale(token)
    block["type"] = "paragraph"
    block["text"] = template.format(lines=", ".join(lines))
    block.pop("alt_text", None)
    block["metadata"]["role"] = "header"
    block["metadata"]["letterhead_members"] = [member.id for member in members]
    return block


def _manifest_pages_to_payload(manifest: ProcessingManifest) -> list[dict[str, Any]]:
    elements_by_id = {element.id: element for element in manifest.elements}
    page_numbers = _page_number_ids(manifest)
    letterheads = _letterhead_groups(manifest, page_numbers)
    #: Letterhead members other than the first, which carries the whole group.
    merged = {
        member.id
        for members in letterheads.values()
        for member in members[1:]
    }
    letterhead_blocks = {
        key: _letterhead_block(members, manifest.language)
        for key, members in letterheads.items()
    }
    pages: list[dict[str, Any]] = []

    if manifest.pages:
        sorted_pages = sorted(manifest.pages, key=lambda page: page.page_number)
        for page in sorted_pages:
            block_elements = [
                elements_by_id[element_id]
                for element_id in page.element_ids
                if element_id in elements_by_id
            ]
            if not block_elements:
                # Some extractors can fill in pages without element_ids; in that
                # case we fall back to page_number so no content is lost.
                block_elements = [
                    element
                    for element in manifest.elements
                    if (element.page_number or 1) == page.page_number
                ]
            block_elements = [
                item
                for item in block_elements
                if not _is_left_out_of_payload(item)
                and item.id not in page_numbers
                and item.id not in merged
            ]
            block_elements.sort(key=lambda item: item.reading_order)
            blocks = _elements_to_blocks(block_elements, letterhead_blocks)
            _dedupe_callout_titles(blocks)
            pages.append(
                {
                    "page_number": page.page_number,
                    "text": _render_text_from_blocks(blocks),
                    "blocks": blocks,
                }
            )
        return pages

    grouped: dict[int, list[ManifestElement]] = {}
    for element in manifest.elements:
        if (
            _is_left_out_of_payload(element)
            or element.id in page_numbers
            or element.id in merged
        ):
            continue
        page_number = element.page_number or 1
        grouped.setdefault(page_number, []).append(element)

    for page_number in sorted(grouped):
        page_elements = sorted(
            grouped[page_number],
            key=lambda item: item.reading_order,
        )
        blocks = _elements_to_blocks(page_elements, letterhead_blocks)
        _dedupe_callout_titles(blocks)
        pages.append(
            {
                "page_number": page_number,
                "text": _render_text_from_blocks(blocks),
                "blocks": blocks,
            }
        )

    return pages


def _elements_to_blocks(
    elements: list[ManifestElement], replacements: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Blocks of ``elements`` in order, with the text an undescribed picture held.

    An element in ``replacements`` (the first member of a letterhead) gives
    way to its block, which already stands for the picture's text.
    """
    blocks: list[dict[str, Any]] = []
    for element in elements:
        if element.id in replacements:
            blocks.append(replacements[element.id])
            continue
        blocks.append(_element_to_block(element))
        blocks.extend(_element_to_block(kept) for kept in _text_kept_by_picture(element))
    return blocks


def _text_kept_by_picture(element: ManifestElement) -> list[ManifestElement]:
    """The text a picture took from the slide, as paragraphs, when it went undescribed.

    Slide structuring hands text to a picture: a slide read as one picture
    keeps the text it replaced (``replaced_text``), a text slide's labels are
    folded into the picture they lie on or beside (``figure_labels``). Its
    description was to carry that text; without one, the text goes back to
    the slide after the picture, as it stood before, instead of being lost or
    listed as the picture's alt text (006.pdf v5, slides 16 and 31).

    Only the vision model's description carries that text: an alt the
    extractor gave the picture, which a failed call leaves in place, does not.
    The paragraphs carry the picture's source location; the labels' own boxes
    left with the elements they were folded from.
    """
    if element.type != "picture" or (
        element.metadata.get("vision_description_complete") and (element.text or "").strip()
    ):
        return []
    replaced = element.metadata.get("replaced_text")
    texts = (
        [line for line in replaced.splitlines() if line.strip()]
        if isinstance(replaced, str) and replaced.strip()
        else list(element.metadata.get("figure_labels") or [])
    )
    return [
        ManifestElement(
            id=f"{element.id}-kept-{index:03d}",
            type="paragraph",
            raw_label="paragraph",
            reading_order=element.reading_order,
            hierarchy_level=element.hierarchy_level,
            text=text,
            page_number=element.page_number,
            provenance=list(element.provenance),
            metadata={"kept_from_undescribed_picture": element.id},
        )
        for index, text in enumerate(texts, start=1)
    ]


def _element_to_block(element: ManifestElement) -> dict[str, Any]:
    provenance = element.provenance[0] if element.provenance else None
    metadata: dict[str, Any] = {
        "raw_label": element.raw_label,
        "source_ref": element.source_ref,
        "parent_id": element.parent_id,
        "confidence": element.confidence,
        "manifest_element_id": element.id,
    }
    if element.metadata:
        metadata.update(element.metadata)
    metadata = _normalize_metadata_links(metadata)

    source_location: dict[str, Any] = {}
    if provenance is not None:
        source_location["page_number"] = provenance.page_number
        if provenance.bbox is not None:
            source_location["bbox"] = {
                "left": provenance.bbox.left,
                "top": provenance.bbox.top,
                "right": provenance.bbox.right,
                "bottom": provenance.bbox.bottom,
            }

    text = element.text or ""
    callout_id = metadata.get("callout_id")
    callout_role = str(metadata.get("callout_role", "")).lower()
    callout_type = str(metadata.get("callout_type", "note")).lower()
    callout_title = str(metadata.get("callout_title", "")).strip()
    callout_block_type = "warning" if callout_type in {"warning", "aviso", "importante", "caution"} else "note"
    block: dict[str, Any] = {
        "id": element.id,
        "source_location": source_location,
        "metadata": metadata,
    }

    if callout_id and callout_role != "title":
        block.update(
            {
                "type": callout_block_type,
                "title": callout_title,
                "text": text,
            }
        )
        return block

    if element.type in {"title", "heading"}:
        block.update(
            {
                "type": "heading",
                "level": 1 if element.type == "title" else max(1, element.hierarchy_level),
                "text": text or element.raw_label,
            }
        )
    elif element.type == "list_item":
        block.update(
            {
                "type": "list",
                "ordered": False,
                "items": [text] if text else [],
            }
        )
    elif element.type == "table":
        table_ast = _table_ast_from_metadata(metadata)
        rows = _rows_from_table_ast(table_ast) if table_ast else None
        if not rows:
            rows = [[text]] if text else [["Tabela detectada"]]
            if table_ast is None:
                table_ast = _table_ast_from_rows(rows)
        block.update(
            {
                "type": "table",
                "rows": rows,
                "table_ast": table_ast,
            }
        )
    elif element.type == "picture":
        block.update(
            {
                "type": "image",
                "alt_text": text or t(MSG_UNDESCRIBED_PICTURE_ALT),
            }
        )
    elif element.type == "code":
        block.update({"type": "code", "text": normalize_code_text(text)})
    elif element.type == "formula":
        if text:
            block.update({"type": "math", "text": text})
        else:
            block.update({"type": "paragraph", "text": "Formula detectada."})
    else:
        block.update({"type": "paragraph", "text": text or element.raw_label})

    return block


def _normalize_metadata_links(metadata: dict[str, Any]) -> dict[str, Any]:
    def normalize_value(value: Any) -> Any:
        if isinstance(value, str) and value.startswith("#/"):
            return value[1:]
        if isinstance(value, list):
            return [normalize_value(item) for item in value]
        if isinstance(value, dict):
            return {key: normalize_value(item) for key, item in value.items()}
        return value

    return {key: normalize_value(value) for key, value in metadata.items()}


def _render_text_from_blocks(blocks: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for block in blocks:
        block_type = block.get("type")
        if block_type == "heading":
            level = int(block.get("level", 1))
            prefix = "#" * max(1, min(level, 6))
            lines.append(f"{prefix} {block.get('text', '').strip()}")
        elif block_type == "list":
            for item in block.get("items", []):
                lines.append(f"- {str(item).strip()}")
        elif block_type == "table":
            rows = block.get("rows")
            if not rows and isinstance(block.get("table_ast"), dict):
                rows = _rows_from_table_ast(block["table_ast"])
            for row in rows or []:
                if isinstance(row, list):
                    lines.append(" | ".join(str(cell).strip() for cell in row))
        elif block_type == "image":
            lines.append(block.get("alt_text", "Imagem"))
        else:
            text = block.get("text", "")
            if isinstance(text, str) and text.strip():
                lines.append(text.strip())
    return "\n".join(lines).strip()


def _render_text_from_pages(pages: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for page in pages:
        page_number = page.get("page_number", "?")
        text = str(page.get("text", "")).strip()
        if text:
            chunks.append(f"=== Pagina {page_number} ===\n{text}")
    return "\n\n".join(chunks)


def _table_ast_from_metadata(metadata: dict[str, Any]) -> dict[str, Any] | None:
    raw = metadata.get("table_ast")
    if not isinstance(raw, dict):
        return None

    table_ast: dict[str, Any] = {}
    caption = raw.get("caption")
    if isinstance(caption, str) and caption.strip():
        table_ast["caption"] = caption.strip()

    for section_name in ("header", "body", "footer"):
        section = raw.get(section_name)
        if not isinstance(section, list):
            continue
        normalized_rows: list[dict[str, Any]] = []
        for row in section:
            if not isinstance(row, dict):
                continue
            cells = row.get("cells")
            if not isinstance(cells, list):
                continue
            normalized_cells: list[dict[str, Any]] = []
            for cell in cells:
                if not isinstance(cell, dict) or "text" not in cell:
                    continue
                text = str(cell.get("text", "")).strip()
                normalized_cell: dict[str, Any] = {"text": text}
                if isinstance(cell.get("header"), bool):
                    normalized_cell["header"] = cell["header"]
                scope = cell.get("scope")
                if isinstance(scope, str) and scope in {
                    "none",
                    "row",
                    "col",
                    "rowgroup",
                    "colgroup",
                }:
                    normalized_cell["scope"] = scope
                for span_key in ("rowspan", "colspan"):
                    span = cell.get(span_key)
                    if isinstance(span, int) and span >= 1:
                        normalized_cell[span_key] = span
                normalized_cells.append(normalized_cell)
            if normalized_cells:
                normalized_rows.append({"cells": normalized_cells})
        if normalized_rows:
            table_ast[section_name] = normalized_rows

    metadata_obj = raw.get("metadata")
    if isinstance(metadata_obj, dict):
        table_ast["metadata"] = metadata_obj

    return table_ast if table_ast.get("body") else None


def _table_ast_from_rows(rows: list[list[str]]) -> dict[str, Any]:
    body: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, list):
            continue
        cells = []
        for cell in row:
            text = str(cell).strip()
            cells.append({"text": text})
        if cells:
            body.append({"cells": cells})
    return {"body": body}


# Backward compatibility with the PMV naming.
PmvAccessibilityOrchestrator = PddlAccessibilityOrchestrator
build_pmv_structured_payload = build_pddl_structured_payload
