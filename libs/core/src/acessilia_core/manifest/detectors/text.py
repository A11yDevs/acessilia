"""Pure text, formula and legacy-Unicode detectors for manifest needs."""

from __future__ import annotations

from collections import Counter

from docstruct.tables.ast import raw_rows_from_table_ast as _rows_from_table_ast
from docstruct.text.latex import normalize_latex
from docstruct.text.norm_fix import norm_fix
from docstruct.text.unicode_repair import detect_legacy_unicode

from acessilia_core.manifest.detectors.types import NeedCandidate
from acessilia_core.manifest.models import ManifestElement

TEXT_NORMALIZATION_ELEMENT_TYPES = frozenset(
    {"paragraph", "heading", "title", "list_item", "caption"}
)

#: Element types whose text the Unicode repair may rewrite. Tables carry their
#: content in the cell AST and are read through ``unicode_repair_text``.
UNICODE_REPAIR_ELEMENT_TYPES = frozenset(
    {
        "paragraph",
        "heading",
        "title",
        "list_item",
        "caption",
        "footnote",
        "page_header",
        "page_footer",
        "table",
    }
)


def unicode_repair_text(element: ManifestElement) -> str:
    """Text the Unicode detection/repair sees for ``element``.

    Page headers/footers are ordinary prose. A table has no ``element.text``:
    its content lives in the cell AST (plus an optional caption).
    """
    if element.type == "table":
        table_ast = element.metadata.get("table_ast")
        if not isinstance(table_ast, dict):
            return ""
        parts = [
            value
            for row in _rows_from_table_ast(table_ast)
            for value in row
            if value
        ]
        caption = table_ast.get("caption")
        if isinstance(caption, str) and caption.strip():
            parts.append(caption)
        return " ".join(parts)
    return element.text or ""


def detect_text_and_formula_normalizations(
    elements: list[ManifestElement],
) -> list[NeedCandidate]:
    """Emit formula-LaTeX and prose-text normalization needs in element order."""
    candidates: list[NeedCandidate] = []
    for element in elements:
        text = element.text or ""
        if not text:
            continue
        if element.type == "formula":
            normalized = normalize_latex(text)
            if normalized != text:
                candidates.append(
                    NeedCandidate(
                        "normalize-formula",
                        [element],
                        {"before": text, "after": normalized},
                    )
                )
        elif element.type in TEXT_NORMALIZATION_ELEMENT_TYPES:
            normalized = norm_fix(text)
            if normalized != text:
                candidates.append(
                    NeedCandidate(
                        "normalize-text",
                        [element],
                        {"before": text, "after": normalized},
                    )
                )
    return candidates


def detect_legacy_unicode_needs(
    elements: list[ManifestElement],
    *,
    legacy_unicode_repair: str = "off",
) -> list[NeedCandidate]:
    """Emit a document-level legacy-Unicode need when configured and signalled."""
    mode = _normalize_unicode_mode(legacy_unicode_repair)
    if mode == "off":
        return []

    legacy_targets: list[ManifestElement] = []
    legacy_evidence: Counter[str] = Counter()
    for element in elements:
        detection = _detect_element_unicode(element, mode=mode)
        if detection is None:
            continue
        legacy_targets.append(element)
        _accumulate_unicode_evidence(legacy_evidence, detection)

    if not legacy_targets:
        return []
    return [
        NeedCandidate(
            "repair-legacy-unicode",
            legacy_targets,
            dict(legacy_evidence),
            emit_obligation=mode == "repair",
        )
    ]


def _normalize_unicode_mode(mode: str) -> str:
    normalized = str(mode or "off").strip().lower()
    return normalized if normalized in {"off", "detect", "repair"} else "off"


def _detect_element_unicode(element: ManifestElement, *, mode: str):
    if element.type not in UNICODE_REPAIR_ELEMENT_TYPES:
        return None
    text = unicode_repair_text(element)
    if not text:
        return None
    detection = detect_legacy_unicode(text)
    if not detection.has_signal:
        return None
    repairable = bool(
        detection.combining_runs
        or detection.dotless
        or detection.spacing_diacritics
    )
    # Phase B rewrites NFC, dotless-i and spacing diacritics; the handler
    # limits standalone accents to documents with enough word-internal
    # evidence. Replacement characters stay report-only.
    if mode == "repair" and not repairable:
        return None
    return detection


def _accumulate_unicode_evidence(evidence: Counter[str], detection) -> None:
    evidence["elements"] += 1
    evidence["combining_runs"] += detection.combining_runs
    evidence["combining_marks"] += detection.combining_marks
    evidence["dotless"] += detection.dotless
    evidence["spacing_diacritics"] += detection.spacing_diacritics
    evidence["spacing_word_internal"] += detection.spacing_word_internal
    evidence["replacement_characters"] += detection.replacement_characters
