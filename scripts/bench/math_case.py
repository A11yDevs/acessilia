"""Scorecard of a whole-document math case (acessilia-dataset ``math-reference``).

    python -m scripts.bench.math_case score --canonical doc.json --txt doc.txt [--pdf-ua doc.pdf_ua.pdf]
    python -m scripts.bench.math_case run   [--pdf input.pdf] [--out var/bench/math-reference/<run>]

``score`` reads a job's canonical document and plain-text output; ``run``
processes the reference PDF through the core first (it needs a running
Toolbox and model provider) and then scores it. The ground truth is
``input/math-reference/{ground_truth.csv,expectations.json}`` of the dataset
clone at ``$ACESSILIA_TEST_DATASET_DIR`` (default ``tests/dataset``).

The scorecard measures what a reader of the accessible output gets:

- display formulas, matched to the ground truth on the same page: CDM, the
  recall of structural tokens (``\\frac``, ``^``, ``_``, ``\\lim``...), which
  flattened text-layer formulas lose and bag-of-token CDM barely penalizes,
  and whether each one has MathML and a spoken form;
- inline expressions and table cells delivered as math (``$...$``);
- text, structure and speech checks from ``expectations.json``.

Like the rest of the harness, the numbers track deltas between runs; they are
not an official evaluation.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from docstruct.evaluation.metrics import cdm_score
from docstruct.evaluation.metrics.cdm import _tokens
from docstruct.text.latex import bare_latex

REPO = Path(__file__).resolve().parents[2]
CASE_DIR = Path("input") / "math-reference"
CASE_PDF = "velocidade-instantanea.pdf"

#: CDM a predicted span needs to count as the expected inline expression or
#: table cell. Inline expressions are short, so anything lower is usually a
#: different expression sharing a few letters.
MATCH_CDM = 80.0

#: Tokens that carry 2-D or symbolic structure. Text-layer extraction keeps
#: the letters and digits of a formula but drops these, so their recall is
#: what separates real LaTeX from a flattened formula.
STRUCTURE_TOKENS = frozenset({
    "^", "_", "\\frac", "\\dfrac", "\\tfrac", "\\lim", "\\to", "\\mathbb", "\\neq", "\\ne",
    "\\geq", "\\ge", "\\leq", "\\le", "\\in", "\\cup", "\\infty", "\\cdot", "\\cdots",
    "\\tag", "\\mathrm", "\\text", "\\quad", "\\lbrace", "\\rbrace",
})

#: Set braces as commands. The CDM tokenizer turns every brace, escaped ones
#: included, into a token boundary, so ``\{``/``\}`` would never reach the
#: recall; their command spellings survive it.
_SET_BRACES = (("\\{", "\\lbrace "), ("\\}", "\\rbrace "))

#: A math span in a text: ``$$...$$``, ``\[...\]``, ``$...$`` or ``\(...\)``.
#: Display delimiters count too, because a cell or a paragraph that carries
#: a whole formula as display math still delivers it as math.
_MATH_SPAN = re.compile(
    r"\$\$(.+?)\$\$|\\\[(.+?)\\\]|(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)|\\\((.+?)\\\)", re.S
)


@dataclass
class Check:
    id: str
    passed: bool
    detail: str = ""


@dataclass
class Scorecard:
    display: list[dict[str, Any]] = field(default_factory=list)
    inline: list[dict[str, Any]] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    text: list[Check] = field(default_factory=list)
    structure: list[Check] = field(default_factory=list)
    speech: list[Check] = field(default_factory=list)
    #: Outputs the text checks ran on. With the PDF/UA the text checks double
    #: and the structure checks gain the auto-numbering one, so two scorecards
    #: compare only when they scored the same outputs.
    outputs: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        def mean(values: list[float]) -> float | None:
            return round(sum(values) / len(values), 1) if values else None

        def share(flags: list[bool]) -> float | None:
            return round(100.0 * sum(flags) / len(flags), 1) if flags else None

        def passed(checks: list[Check]) -> str:
            return f"{sum(c.passed for c in checks)}/{len(checks)}"

        return {
            "outputs": list(self.outputs),
            "display_formulas": len(self.display),
            "display_found": share([d["matched"] is not None for d in self.display]),
            "display_cdm": mean([d["cdm"] for d in self.display]),
            "display_structure_recall": mean(
                [d["structure_recall"] for d in self.display if d["structure_recall"] is not None]
            ),
            "display_with_mathml": share([d["mathml"] for d in self.display]),
            "display_with_speech": share([d["speech"] for d in self.display]),
            "display_methods": dict(Counter(d["method"] for d in self.display if d["method"])),
            "inline_as_math": share([i["as_math"] for i in self.inline]),
            "table_math_cells": share([t["passed"] for t in self.tables]),
            "text_checks": passed(self.text),
            "structure_checks": passed(self.structure),
            "speech_checks": passed(self.speech),
        }

    def to_dict(self) -> dict[str, Any]:
        def checks(items: list[Check]) -> list[dict[str, Any]]:
            return [c.__dict__ for c in items]

        return {
            "summary": self.summary(),
            "display": self.display,
            "inline": self.inline,
            "tables": self.tables,
            "text": checks(self.text),
            "structure": checks(self.structure),
            "speech": checks(self.speech),
        }

    def to_markdown(self) -> str:
        s = self.summary()
        rows = [
            ("Outputs scored", ", ".join(s["outputs"]) or "—"),
            ("Display formulas found", _pct(s["display_found"])),
            ("Display CDM (mean)", _num(s["display_cdm"])),
            ("Display structure-token recall (mean)", _num(s["display_structure_recall"])),
            ("Display with MathML", _pct(s["display_with_mathml"])),
            ("Display with spoken form", _pct(s["display_with_speech"])),
            ("Display LaTeX source", ", ".join(f"{k}: {v}" for k, v in sorted(s["display_methods"].items())) or "—"),
            ("Inline expressions as math", _pct(s["inline_as_math"])),
            ("Table headers/cells correct", _pct(s["table_math_cells"])),
            ("Text checks", s["text_checks"]),
            ("Structure checks", s["structure_checks"]),
            ("Speech checks", s["speech_checks"]),
        ]
        lines = ["| Metric | Value |", "|---|---|", *(f"| {k} | {v} |" for k, v in rows)]
        failed = [c for c in (*self.text, *self.structure, *self.speech) if not c.passed]
        if failed:
            lines += ["", "Failed checks:", ""]
            lines += [f"- `{c.id}`" + (f": {c.detail}" if c.detail else "") for c in failed]
        return "\n".join(lines) + "\n"


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}%"


def _num(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}"


# ── Ground truth ────────────────────────────────────────────────────


def dataset_dir() -> Path:
    return Path(os.environ.get("ACESSILIA_TEST_DATASET_DIR") or REPO / "tests" / "dataset")


def load_case(root: Path) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """The formula rows and the expectations of the case under ``root``."""
    case = root / CASE_DIR
    if not (case / "ground_truth.csv").exists():
        raise FileNotFoundError(
            f"{case / 'ground_truth.csv'} not found: clone A11yDevs/acessilia-dataset "
            "into tests/dataset or set ACESSILIA_TEST_DATASET_DIR"
        )
    with open(case / "ground_truth.csv", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    expectations = json.loads((case / "expectations.json").read_text(encoding="utf-8"))
    return rows, expectations


# ── Canonical document ──────────────────────────────────────────────


def iter_blocks(document: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Every block of the canonical document, in reading order."""

    def walk_blocks(blocks: list[Any]) -> Iterator[dict[str, Any]]:
        for block in blocks:
            if not isinstance(block, dict):
                continue
            yield block
            yield from walk_blocks(block.get("children") or [])
            yield from walk_blocks([i for i in block.get("items") or [] if isinstance(i, dict)])

    def walk_sections(sections: list[Any]) -> Iterator[dict[str, Any]]:
        for section in sections:
            if not isinstance(section, dict):
                continue
            yield from walk_blocks(section.get("blocks") or [])
            yield from walk_sections(section.get("children") or [])

    yield from walk_sections(document.get("sections") or [])


def _page(block: dict[str, Any]) -> int | None:
    page = (block.get("source_location") or {}).get("page_number")
    return page if isinstance(page, int) else None


def _block_texts(block: dict[str, Any]) -> list[str]:
    texts = [block.get("text") or ""]
    texts += [i for i in block.get("items") or [] if isinstance(i, str)]
    return [t for t in texts if t]


def _table_cells(block: dict[str, Any]) -> list[str]:
    ast = block.get("table_ast")
    if isinstance(ast, dict):
        return [
            str(cell.get("text") or "")
            for part in ("header", "body", "footer")
            for row in ast.get(part) or []
            for cell in row.get("cells") or []
        ]
    return [str(cell) for row in block.get("rows") or [] for cell in row]


def _table_shape(block: dict[str, Any]) -> tuple[int, int]:
    ast = block.get("table_ast")
    if isinstance(ast, dict):
        rows = [row for part in ("header", "body", "footer") for row in ast.get(part) or []]
        widths = [sum(int(c.get("colspan") or 1) for c in row.get("cells") or []) for row in rows]
    else:
        rows = block.get("rows") or []
        widths = [len(row) for row in rows]
    return len(rows), max(widths, default=0)


def _inline_spans(text: str) -> list[str]:
    return [bare_latex(next(g for g in groups if g)) for groups in _MATH_SPAN.findall(text)]


# ── Scoring ─────────────────────────────────────────────────────────


def structure_recall(predicted: str, expected: str) -> float | None:
    """Share of the expected structural tokens the prediction keeps (0-100)."""

    def structural(latex: str) -> Counter[str]:
        for brace, command in _SET_BRACES:
            latex = latex.replace(brace, command)
        return Counter(t for t in _tokens(latex) if t in STRUCTURE_TOKENS)

    wanted = structural(expected)
    if not wanted:
        return None
    got = structural(predicted)
    return round(100.0 * sum((wanted & got).values()) / sum(wanted.values()), 1)


def _plain(latex: str) -> str:
    """A LaTeX table value as the plain text a cell would show."""
    text = latex.replace("{,}", ",").replace("\\neq", "≠").replace("\\ne", "≠")
    text = re.sub(r"[{}\s]", "", text)
    return text.replace("-", "−")


def _plain_cell(text: str) -> str:
    return re.sub(r"\s", "", text).replace("-", "−")


def _match_display(rows: list[dict[str, str]], blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Greedy best-CDM pairing of ground-truth display formulas with math blocks.

    A formula is matched on its own page when the block carries one, so an
    extractor that splits or merges formulas loses only those, not the
    alignment of every formula after them.
    """
    candidates = [b for b in blocks if b.get("type") == "math"]
    pairs: list[tuple[float, int, int]] = []
    for gi, row in enumerate(rows):
        for bi, block in enumerate(candidates):
            page = _page(block)
            if page is not None and page != int(row["page"]):
                continue
            score = cdm_score(bare_latex(block.get("text") or ""), row["expected_latex"]) or 0.0
            pairs.append((score, gi, bi))
    used_gt: dict[int, int] = {}
    used_blocks: set[int] = set()
    for score, gi, bi in sorted(pairs, key=lambda p: -p[0]):
        if score <= 0 or gi in used_gt or bi in used_blocks:
            continue
        used_gt[gi] = bi
        used_blocks.add(bi)

    results = []
    for gi, row in enumerate(rows):
        block = candidates[used_gt[gi]] if gi in used_gt else None
        predicted = bare_latex(block.get("text") or "") if block else ""
        metadata = (block or {}).get("metadata") or {}
        recognition = metadata.get("formula_recognition") or {}
        results.append({
            "id": row["id"],
            "page": int(row["page"]),
            "matched": block.get("id") if block else None,
            "predicted": predicted,
            "cdm": round(cdm_score(predicted, row["expected_latex"]) or 0.0, 1),
            "structure_recall": structure_recall(predicted, row["expected_latex"]),
            "mathml": bool(metadata.get("mathml")),
            "speech": bool((block or {}).get("alt_text")),
            "alt_text": (block or {}).get("alt_text") or "",
            "method": (recognition.get("method") or "extractor") if block else None,
            "equation_number": metadata.get("equation_number"),
        })
    return results


def _score_inline(rows: list[dict[str, str]], blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Whether each inline expression reaches the output as a math span on its page."""
    spans: dict[int | None, list[str]] = {}
    for block in blocks:
        if block.get("type") in {"paragraph", "list", "note", "warning", "quote", "details"}:
            for text in _block_texts(block):
                spans.setdefault(_page(block), []).extend(_inline_spans(text))
    results = []
    for row in rows:
        pool = spans.get(int(row["page"]), []) + spans.get(None, [])
        best = max((cdm_score(s, row["expected_latex"]) or 0.0 for s in pool), default=0.0)
        results.append({"id": row["id"], "page": int(row["page"]), "as_math": best >= MATCH_CDM})
    return results


def _score_tables(rows: list[dict[str, str]], blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Whether each table header/cell is in a table on its page, as math or as equal text."""
    results = []
    for row in rows:
        cells = [
            cell
            for block in blocks
            if block.get("type") == "table" and _page(block) in (int(row["page"]), None)
            for cell in _table_cells(block)
        ]
        expected = row["expected_latex"]
        as_math = any(
            (cdm_score(s, expected) or 0.0) >= MATCH_CDM for cell in cells for s in _inline_spans(cell)
        )
        as_text = any(_plain(expected) in _plain_cell(cell) for cell in cells)
        results.append({
            "id": row["id"], "page": int(row["page"]), "as_math": as_math, "as_text": as_text,
            "passed": as_math or as_text,
        })
    return results


def _text_checks(expectations: dict[str, Any], targets: dict[str, str]) -> list[Check]:
    checks = []
    for target, text in targets.items():
        for spec in expectations.get("must_match", []):
            found = re.search(spec["pattern"], text) is not None
            checks.append(Check(f"{target}:{spec['id']}", found, "" if found else "missing"))
        for spec in expectations.get("must_not_match", []):
            hit = re.search(spec["pattern"], text)
            checks.append(Check(
                f"{target}:{spec['id']}", hit is None, f"found {hit.group(0)!r}" if hit else ""
            ))
    return checks


def _structure_checks(
    expectations: dict[str, Any],
    document: dict[str, Any],
    blocks: list[dict[str, Any]],
    display: list[dict[str, Any]],
    pdf_text: str | None,
) -> list[Check]:
    checks = []

    # (text, level, page); the page is None when the document does not say.
    headings: list[tuple[str, int, int | None]] = []

    def collect(sections: list[Any]) -> None:
        for section in sections:
            if isinstance(section, dict):
                headings.append((
                    str(section.get("title") or "").strip(),
                    int(section.get("level") or 1),
                    _page(section),
                ))
                collect(section.get("children") or [])

    collect(document.get("sections") or [])
    headings += [
        (str(b.get("text") or "").strip(), int(b.get("level") or 1), _page(b))
        for b in blocks if b.get("type") == "heading"
    ]
    for spec in expectations.get("headings", []):
        found = [
            (level, page) for text, level, page in headings
            if text == spec["text"] and (page is None or spec.get("page") in (None, page))
        ]
        ok = any(level == spec["level"] for level, _ in found)
        checks.append(Check(
            f"heading:{spec['text']}", ok,
            "" if ok else (f"found at level {[lv for lv, _ in found]}" if found else "not a heading"),
        ))

    if expectations.get("auto_numbered_headings") is False and pdf_text is not None:
        numbered = [
            text for text, _, _ in headings
            if text and re.search(rf"(?m)^\s*\d+(\.\d+)*\s+{re.escape(text)}\s*$", pdf_text)
        ]
        checks.append(Check(
            "headings:not-auto-numbered", not numbered,
            f"numbered: {numbered}" if numbered else "",
        ))

    # A lone digit line in the text also comes from flattened fractions and
    # table values, so page numbers are checked on the blocks: a page number
    # left in the body is a block of page N whose whole text is N.
    furniture = expectations.get("page_numbers") or {}
    if furniture.get("is_furniture"):
        leaked = sorted({
            page for b in blocks
            if (page := _page(b)) in furniture.get("pages", [])
            and b.get("type") not in {"math", "table"}
            and str(b.get("text") or "").strip() == str(page)
        })
        checks.append(Check(
            "page-numbers:not-in-body", not leaked,
            f"pages {leaked}" if leaked else "",
        ))

    for spec in expectations.get("ordered_lists", []):
        runs = _list_runs(blocks, spec["page"])
        hit = [run for run in runs if run["items"] and run["items"][0].strip().startswith(spec["first_item_starts"])]
        run = hit[0] if hit else None
        ok = run is not None and run["ordered"] and len(run["items"]) == spec["items"]
        detail = "" if ok else (
            "list not found" if run is None
            else f"{len(run['items'])} items, ordered={run['ordered']}"
        )
        checks.append(Check(f"ordered-list:p{spec['page']}", ok, detail))

    for spec in expectations.get("tables", []):
        shapes = [_table_shape(b) for b in blocks if b.get("type") == "table" and _page(b) == spec["page"]]
        ok = (spec["rows"], spec["columns"]) in shapes
        checks.append(Check(
            f"table:p{spec['page']}", ok,
            "" if ok else (f"shapes {shapes}" if shapes else "no table on the page"),
        ))

    by_id = {d["id"]: d for d in display}
    for spec in expectations.get("equation_numbers", []):
        entry = by_id.get(spec["formula"])
        number = str(entry.get("equation_number") or "") if entry else ""
        tagged = bool(entry) and re.search(
            rf"\\tag\s*\{{\s*{re.escape(spec['number'])}\s*\}}", entry["predicted"]
        ) is not None
        ok = number == spec["number"] or tagged
        checks.append(Check(
            f"equation-number:{spec['formula']}", ok,
            "" if ok else ("formula not found" if not entry or entry["matched"] is None else "number lost"),
        ))
    return checks


def _list_runs(blocks: list[dict[str, Any]], page: int) -> list[dict[str, Any]]:
    """Consecutive list blocks of a page merged into one list.

    The core emits one ``list`` block per list item, so a list is a run of
    adjacent list blocks. A ``math`` block between two of them does not end
    the run: a display formula inside an item (item 1 of the page 4 list
    holds one) comes out as its own block between the items. Any other block
    ends it.
    """
    runs: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for block in blocks:
        if block.get("type") == "list" and _page(block) == page:
            if current is None:
                current = {"ordered": True, "items": []}
                runs.append(current)
            current["ordered"] = current["ordered"] and bool(block.get("ordered"))
            current["items"] += [str(i) for i in block.get("items") or [] if isinstance(i, str)]
        elif block.get("type") != "math":
            current = None
    return runs


def _speech_checks(expectations: dict[str, Any], display: list[dict[str, Any]]) -> list[Check]:
    by_id = {d["id"]: d for d in display}
    checks = []
    for spec in expectations.get("formulas", []):
        alt = (by_id.get(spec["formula"]) or {}).get("alt_text", "").casefold()
        ok = any(word.casefold() in alt for word in spec["any_of"])
        checks.append(Check(
            f"speech:{spec['formula']}", ok, "" if ok else ("no spoken form" if not alt else alt[:80]),
        ))
    return checks


def score_case(
    rows: list[dict[str, str]],
    expectations: dict[str, Any],
    document: dict[str, Any],
    txt: str,
    pdf_text: str | None = None,
) -> Scorecard:
    blocks = list(iter_blocks(document))
    by_kind: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_kind.setdefault(row["kind"], []).append(row)

    card = Scorecard()
    card.display = _match_display(by_kind.get("display", []), blocks)
    card.inline = _score_inline(by_kind.get("inline", []), blocks)
    card.tables = _score_tables(by_kind.get("table-header", []) + by_kind.get("table-cell", []), blocks)
    targets = {"txt": txt}
    if pdf_text is not None:
        targets["pdf_ua"] = pdf_text
    card.outputs = list(targets)
    card.text = _text_checks(expectations.get("text", {}), targets)
    card.structure = _structure_checks(
        expectations.get("structure", {}), document, blocks, card.display, pdf_text
    )
    card.speech = _speech_checks(expectations.get("speech", {}), card.display)
    return card


def pdf_text(path: Path) -> str:
    """Text of a PDF in reading order, as ``pdftotext`` (poppler) extracts it."""
    if shutil.which("pdftotext") is None:
        raise RuntimeError("pdftotext (poppler-utils) is required to score a PDF/UA output")
    return subprocess.run(
        ["pdftotext", "-enc", "UTF-8", str(path), "-"],
        check=True, capture_output=True, text=True,
    ).stdout


# ── Commands ────────────────────────────────────────────────────────


async def _process(pdf: Path, out: Path, *, pdf_ua: bool) -> tuple[Path, Path, Path | None]:
    """Run the core on ``pdf`` and write the canonical document, TXT and PDF/UA."""
    from backend.export.exporters.pdf_exporter import export_pdf_ua
    from backend.export.exporters.txt_exporter import export_txt
    from backend.service import process

    canonical = await process(pdf)
    out.mkdir(parents=True, exist_ok=True)
    canonical_path = out / "canonical.json"
    canonical_path.write_text(json.dumps(canonical, ensure_ascii=False, indent=2), encoding="utf-8")
    txt_path = out / f"{pdf.stem}.txt"
    export_txt(canonical, txt_path, pdf.name)
    pdf_ua_path = None
    if pdf_ua:
        pdf_ua_path = out / f"{pdf.stem}.pdf_ua.pdf"
        export_pdf_ua(canonical, pdf_ua_path, pdf.name)
    return canonical_path, txt_path, pdf_ua_path


def _write(card: Scorecard, out: Path | None) -> None:
    print(card.to_markdown(), end="")
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        (out / "scorecard.json").write_text(
            json.dumps(card.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (out / "scorecard.md").write_text(card.to_markdown(), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.bench.math_case", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dataset", type=Path, help="acessilia-dataset clone (default: $ACESSILIA_TEST_DATASET_DIR or tests/dataset)")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("score", help="score a job's outputs")
    p.add_argument("--canonical", type=Path, required=True, help="canonical document JSON")
    p.add_argument("--txt", type=Path, required=True, help="plain-text output")
    p.add_argument("--pdf-ua", type=Path, help="PDF/UA output (needs pdftotext)")
    p.add_argument("--out", type=Path, help="also write scorecard.json and scorecard.md here")
    p = sub.add_parser("run", help="process the reference PDF, then score it")
    p.add_argument("--pdf", type=Path, help="input PDF (default: the dataset's copy)")
    p.add_argument("--out", type=Path, default=REPO / "var" / "bench" / "math-reference" / "latest")
    p.add_argument("--no-pdf-ua", action="store_true", help="skip the PDF/UA export")
    args = parser.parse_args(argv)

    root = args.dataset or dataset_dir()
    rows, expectations = load_case(root)

    if args.command == "run":
        import asyncio

        pdf = args.pdf or root / CASE_DIR / CASE_PDF
        canonical_path, txt_path, pdf_ua_path = asyncio.run(
            _process(pdf, args.out, pdf_ua=not args.no_pdf_ua)
        )
    else:
        canonical_path, txt_path, pdf_ua_path = args.canonical, args.txt, args.pdf_ua

    document = json.loads(canonical_path.read_text(encoding="utf-8"))
    card = score_case(
        rows, expectations, document,
        txt_path.read_text(encoding="utf-8"),
        pdf_text(pdf_ua_path) if pdf_ua_path else None,
    )
    _write(card, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
