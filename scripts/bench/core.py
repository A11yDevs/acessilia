"""Toolbox structure payload → canonical document and persisted blocks.

Port of the conversion in ``scripts/drbench/run_pipeline.py`` (tag
drbench-2026-snapshot). The payload is ``structured-document@1``: a flat
``elements`` list in reading order. Builds canonical documents with
``docstruct.canonical`` and enriches formulas directly through the SDK's
``acessilia_sdk.operations.formula`` operation (ADR-0017, #614), without
importing ``acessilia_core`` or ``backend``.
"""

from __future__ import annotations

import html
from typing import Any
from uuid import uuid4

from acessilia_sdk.toolbox.errors import ToolboxError, ToolboxInvalidInput
from docstruct.canonical import (
    MathEnricher,
    build_canonical_document,
    sanitize_canonical_document,
)
from docstruct.text.latex import bare_latex
from scripts.bench import toolbox

_PLACEHOLDER_TITLE = "Benchmark page"
_HEADING_TYPES = ("heading", "title", "section_header")
_HEADER_SCOPES = {"row", "col", "rowgroup", "colgroup"}


class _SdkMathEnricher(MathEnricher):
    """Enrich math blocks directly via ``acessilia_sdk.operations.formula``.

    Calls ``convert_formula`` and ``verbalize_formula`` through
    :mod:`scripts.bench.toolbox`. Normalization uses ``bare_latex`` (matching
    ``acessilia_core.formula_tools.normalize_latex``: delimiters and whitespace
    only). Display-formula speech intentionally keeps the raw ``math.verbalize``
    output without the core's ``label_spoken_formula`` presentation prefix
    (ADR-0017: presentation labeling stays in the core). A rejected expression
    (``ToolboxInvalidInput``) degrades to empty text; the first outage of a
    capability stops further calls to it for the rest of the document and
    records a technical warning.
    """

    def __init__(self, *, language: str = "pt-BR") -> None:
        self.language = language
        self.unavailable: dict[str, str] = {}
        self.rejected: dict[str, int] = {}

    def normalize(self, latex: str) -> str:
        # Matches acessilia_core.formula_tools.normalize_latex (bare_latex alias).
        return bare_latex(latex)

    def to_mathml(self, latex: str) -> str:
        return self._call("math.convert", toolbox.convert_latex, latex)

    def verbalize(self, latex: str) -> str:
        return self._call("math.verbalize", self._verbalize, latex).strip()

    def verbalize_inline(self, latex: str) -> str:
        return self._call("math.verbalize", self._verbalize, latex).strip()

    def _verbalize(self, latex: str) -> str:
        return toolbox.verbalize_latex(latex, language=self.language)

    def _call(self, capability: str, fn: Any, latex: str) -> str:
        if not latex or capability in self.unavailable:
            return ""
        try:
            result = fn(latex)
        except ToolboxInvalidInput:
            self.rejected[capability] = self.rejected.get(capability, 0) + 1
            return ""
        except ToolboxError as exc:
            self.unavailable[capability] = type(exc).__name__
            return ""
        if not result:
            self.rejected[capability] = self.rejected.get(capability, 0) + 1
        return result

    def warnings(self) -> list[str]:
        out = [
            f"{capability} unavailable ({reason}): formulas kept without enrichment"
            for capability, reason in self.unavailable.items()
        ]
        out += [
            f"{capability} rejected the LaTeX of {count} formula(s)"
            for capability, count in self.rejected.items()
        ]
        return out


def payload_to_canonical(
    result: dict[str, Any], *, math_enricher: MathEnricher | None = None
) -> dict[str, Any]:
    """Map manifest elements to canonical blocks and build the document.

    Block types come from the provider's layout model, not from the heuristic
    line parser (which mis-types prose with inline math as ``math``).
    """
    if "sections" in result and result.get("schema_version"):
        return sanitize_canonical_document(result)
    doc = result.get("document", result)
    blocks = elements_to_canonical_blocks(doc.get("elements") or [])
    payload = {"text": "", "pages": [{"blocks": blocks}]} if blocks else {
        "text": doc.get("text") or "",
        "pages": result.get("pages", []),
    }
    enricher = _SdkMathEnricher() if math_enricher is None else math_enricher
    document = build_canonical_document(
        payload,
        title=_PLACEHOLDER_TITLE,
        language=result.get("language") or "en",
        verbosity="detailed",
        math_enricher=enricher,
        id_factory=lambda: f"doc-{uuid4().hex[:12]}",
    )
    if isinstance(enricher, _SdkMathEnricher):
        if warnings := enricher.warnings():
            document.setdefault("technical_warnings", []).extend(warnings)
    if document.get("title") == _PLACEHOLDER_TITLE:
        # No heading on the page: do not emit a synthetic "# ..." line.
        document["title"] = ""
    return sanitize_canonical_document(document)


def elements_to_canonical_blocks(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """heading/title → heading; formula → math; table → table (raw ``html``);
    code → code; picture → dropped; any other element with text → paragraph."""
    blocks: list[dict[str, Any]] = []
    for e in _in_reading_order(elements):
        etype = str(e.get("type", "")).lower()
        text = (e.get("text") or "").strip()
        if etype == "table":
            table_html = element_markdown(e)
            if table_html and _looks_like_html_table(table_html):
                blocks.append({"type": "table", "html": table_html})
            elif text:
                blocks.append({"type": "paragraph", "text": text})
            continue
        if not text or etype == "picture":
            continue
        if etype == "formula":
            latex = bare_latex(text)
            if latex:
                blocks.append({"type": "math", "text": latex})
        elif etype in _HEADING_TYPES:
            level = int(e.get("hierarchy_level") or 1)
            blocks.append({"type": "heading", "level": max(1, min(level, 6)), "text": text})
        elif etype == "code":
            blocks.append({"type": "code", "text": text})
        else:
            inline = _whole_inline_math(text) if etype in ("paragraph", "text") else None
            blocks.append({"type": "math", "text": inline} if inline else {"type": "paragraph", "text": text})
    return blocks


def element_markdown(e: dict[str, Any]) -> str | None:
    """One manifest element as benchmark markdown (None = skip)."""
    text = (e.get("text") or "").strip()
    etype = str(e.get("type", "")).lower()
    if etype == "table":
        if text and _looks_like_html_table(text):
            return text
        ast = (e.get("metadata") or {}).get("table_ast")
        return (table_ast_to_html(ast) if isinstance(ast, dict) else None) or text or None
    if not text:
        return None
    if etype == "formula":
        latex = bare_latex(text)
        return f"$${latex}$$" if latex else None
    if etype in _HEADING_TYPES:
        level = int(e.get("hierarchy_level") or 1)
        return f"{'#' * max(1, min(level, 6))} {text}"
    if etype in ("paragraph", "text"):
        inline = _whole_inline_math(text)
        if inline:
            return f"$${inline}$$"
    return text


def table_ast_to_html(table_ast: dict[str, Any]) -> str | None:
    """A toolbox ``table_ast`` (header/body/footer rows of cells) as flat HTML."""
    rows = [_row_html(r, header=True) for r in table_ast.get("header") or []]
    rows += [_row_html(r, header=False) for r in table_ast.get("body") or []]
    rows += [_row_html(r, header=False) for r in table_ast.get("footer") or []]
    rows = [r for r in rows if r]
    return f"<table>{''.join(rows)}</table>" if rows else None


def provider_blocks(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Reading-ordered blocks with bbox and page size, for block-level fusion."""
    doc = result.get("document", result)
    sizes: dict[int, tuple[Any, Any]] = {}
    pages = doc.get("pages") or result.get("pages") or []
    if isinstance(pages, dict):
        pages = list(pages.values())
    for p in pages:
        if not isinstance(p, dict):
            continue
        no = p.get("page_number", p.get("page_no"))
        size = p.get("size") or p
        if no is not None:
            sizes[int(no)] = (size.get("width"), size.get("height"))

    blocks = []
    for e in _in_reading_order(doc.get("elements") or []):
        prov = (e.get("provenance") or [{}])[0]
        bbox = prov.get("bbox") or {}
        page_no = prov.get("page_number") or e.get("page_number")
        w, h = sizes.get(int(page_no), (None, None)) if page_no is not None else (None, None)
        blocks.append({
            "id": e.get("id"),
            "type": str(e.get("type", "unknown")).lower(),
            "raw_label": e.get("raw_label"),
            "reading_order": e.get("reading_order"),
            "level": e.get("hierarchy_level"),
            "text": e.get("text"),
            "markdown": element_markdown(e),
            "bbox": [bbox.get("left"), bbox.get("top"), bbox.get("right"), bbox.get("bottom")]
            if bbox else None,
            "coord_origin": bbox.get("coord_origin") if bbox else None,
            "page": page_no,
            "page_size": [w, h],
            "metadata": e.get("metadata") or {},
        })
    return blocks


def _in_reading_order(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(elements, key=lambda e: e.get("reading_order") or 0)


def _looks_like_html_table(text: str) -> bool:
    lower = text.lower()
    return "<table" in lower and "</table>" in lower


def _whole_inline_math(text: str) -> str | None:
    """The LaTeX body when ``text`` is a single ``$...$`` span and nothing else.

    MinerU emits a text block holding only an ``inline_equation`` when a
    display formula sits inside a paragraph box; benchmark GT marks those as
    isolated equations.
    """
    s = text.strip()
    if len(s) < 3 or not (s.startswith("$") and s.endswith("$")) or s.startswith("$$"):
        return None
    body = s[1:-1]
    if "$" in body or not body.strip():
        return None
    return body.strip()


def _row_html(row: dict[str, Any], *, header: bool) -> str:
    row_cells = row.get("cells") or []
    unmarked_header_row = header and not any(
        isinstance(c, dict) and ("header" in c or "scope" in c) for c in row_cells
    )
    cells = []
    for c in row_cells:
        if not isinstance(c, dict):
            continue
        scope = str(c.get("scope", "")).strip().lower()
        is_header = unmarked_header_row or bool(c.get("header")) or scope in _HEADER_SCOPES
        tag = "th" if is_header else "td"
        attrs = "".join(
            f' {k}="{int(c[k])}"' for k in ("rowspan", "colspan")
            if isinstance(c.get(k), int) and c[k] > 1
        )
        if is_header:
            cell_scope = scope if scope in _HEADER_SCOPES else ("col" if header else "row")
            attrs = f' scope="{cell_scope}"' + attrs
        cells.append(f"<{tag}{attrs}>{html.escape(str(c.get('text', '')))}</{tag}>")
    return f"<tr>{''.join(cells)}</tr>" if cells else ""
