"""Scorecard of a whole-document math case (acessilia-dataset ``math-reference``).

    python -m scripts.bench.math_case score --canonical doc.json --txt doc.txt [--pdf-ua doc.pdf_ua.pdf]
    python -m scripts.bench.math_case run   [--pdf input.pdf] [--out var/bench/math-reference/<run>]

``score`` reads a job's canonical document and plain-text output; ``run``
processes the reference PDF through the core first (it needs a running
Toolbox and model provider) and then scores it. Ground truth comes from task
selectors in ``references/manifest.csv`` (Dataset input ``036``) at
``$ACESSILIA_TEST_DATASET_DIR`` (default ``tests/dataset``). Legacy local
``input/math-reference/`` copies remain readable during migration.

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
import hashlib
import json
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from docstruct.evaluation.metrics import cdm_score
from docstruct.evaluation.metrics.cdm import _tokens
from docstruct.text.latex import bare_latex
from scripts.bench.dataset_reference import (
    DatasetReferenceError,
    EvaluationSelection,
    assert_pinned_dataset,
    content_digest,
    dataset_dir as resolve_dataset_dir,
    git_revision,
    load_references,
)

REPO = Path(__file__).resolve().parents[2]
CASE_DIR = Path("input") / "math-reference"
CASE_PDF = "velocidade-instantanea.pdf"
MATH_TASKS = (
    "math_formula_transcription",
    "math_text_quality",
    "math_document_structure",
    "math_formula_speech",
)
PROTOCOL_VERSION = "math-reference-v2"

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
    speech_presence_checks: list[Check] = field(default_factory=list)
    #: Outputs the text checks ran on. With the PDF/UA the text checks double
    #: and the structure checks gain the auto-numbering one, so two scorecards
    #: compare only when they scored the same outputs.
    outputs: list[str] = field(default_factory=list)
    dataset: dict[str, Any] = field(default_factory=dict)
    selection: dict[str, Any] = field(default_factory=lambda: EvaluationSelection().to_dict())
    criteria_ids: list[str] = field(default_factory=list)
    not_evaluated: list[dict[str, str]] = field(default_factory=list)
    evaluation_status: str = "completed"

    def summary(self) -> dict[str, Any]:
        def mean(values: list[float]) -> float | None:
            return round(sum(values) / len(values), 1) if values else None

        def share(flags: list[bool]) -> float | None:
            return round(100.0 * sum(flags) / len(flags), 1) if flags else None

        def passed(checks: list[Check]) -> str:
            return f"{sum(c.passed for c in checks)}/{len(checks)}" if checks else "not evaluated"

        coverage = {}
        for task, info in self.dataset.get("tasks", {}).items():
            records = info.get("references") or [info]
            coverage[task] = []
            for record in records:
                eligible = record.get("eligible_count")
                annotated = record.get("annotated_count", 0)
                coverage[task].append({
                    "availability": record.get("availability", "unknown"),
                    "reference_type": record.get("reference_type"),
                    "format": record.get("format"),
                    "annotated": annotated,
                    "eligible": eligible,
                    "unit": record.get("coverage_unit"),
                    "scope": record.get("coverage_scope"),
                    "percent": round(100 * annotated / eligible, 1) if eligible else None,
                })

        return {
            "outputs": list(self.outputs),
            "dataset": self.dataset,
            "reference_coverage": coverage,
            "selection": self.selection,
            "criteria_ids": list(self.criteria_ids),
            "not_evaluated": list(self.not_evaluated),
            "evaluation_status": self.evaluation_status,
            "protocol_version": PROTOCOL_VERSION,
            "display_formulas": len(self.display),
            "display_found": share([d["matched"] is not None for d in self.display]),
            "display_cdm": mean([d["cdm"] for d in self.display]),
            "display_structure_recall": mean(
                [d["structure_recall"] for d in self.display if d["structure_recall"] is not None]
            ),
            "display_with_mathml": share([d["mathml"] for d in self.display]),
            "display_with_speech": share([c.passed for c in self.speech_presence_checks]),
            "speech_presence": {
                "passed": sum(c.passed for c in self.speech_presence_checks),
                "total": len(self.speech_presence_checks),
                "criterion_ids": [c.id for c in self.speech_presence_checks],
                "unit": "display formulas with a non-empty spoken form",
                "status": "evaluated" if self.speech_presence_checks else "not_evaluated",
            },
            "display_methods": dict(Counter(d["method"] for d in self.display if d["method"])),
            "inline_as_math": share([i["as_math"] for i in self.inline]),
            "table_math_cells": share([t["passed"] for t in self.tables]),
            "text_checks": passed(self.text),
            "structure_checks": passed(self.structure),
            "speech_checks": passed(self.speech),
            "speech_lexical_checks": {
                "passed": sum(c.passed for c in self.speech),
                "total": len(self.speech),
                "unit": "selected formulas with at least one accepted lexical marker",
                "eligible_formulas_in_selection": len(self.speech_presence_checks),
                "manifest_eligible_formulas": self.dataset.get("tasks", {}).get(
                    "math_formula_speech", {}
                ).get("eligible_count"),
                "status": "evaluated" if self.speech else "not_evaluated",
            },
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
            "speech_presence_checks": checks(self.speech_presence_checks),
            "dataset": self.dataset,
            "selection": self.selection,
            "criteria_ids": list(self.criteria_ids),
            "not_evaluated": list(self.not_evaluated),
            "evaluation_status": self.evaluation_status,
            "protocol_version": PROTOCOL_VERSION,
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
            ("Speech presence on display formulas", (
                f"{s['speech_presence']['passed']}/{s['speech_presence']['total']}"
                if s["speech_presence"]["status"] == "evaluated" else "not evaluated in this selection"
            )),
            ("Display LaTeX source", ", ".join(f"{k}: {v}" for k, v in sorted(s["display_methods"].items())) or "—"),
            ("Inline expressions as math", _pct(s["inline_as_math"])),
            ("Table headers/cells correct", _pct(s["table_math_cells"])),
            ("Text checks", s["text_checks"]),
            ("Structure checks", s["structure_checks"]),
            ("Speech lexical checks (selected subset)", (
                s["speech_checks"] if s["speech_lexical_checks"]["status"] == "evaluated"
                else "not evaluated in this selection"
            )),
            ("Reference status", ", ".join(
                f"{task}: {info['availability']}"
                for task, info in sorted(self.dataset.get("tasks", {}).items())
            ) or "legacy/unversioned"),
            ("Dataset revision / references digest",
             f"{self.dataset.get('revision') or 'unavailable'} / {self.dataset.get('references_digest') or 'unavailable'}"),
            *[(f"Coverage: {task}" + (f" [{info['reference_type']}]" if info["reference_type"] else ""), (
                f"{info['annotated']}/{info['eligible']} {info['unit']} ({info['percent']:.1f}%)"
                if info["eligible"] else f"{info['annotated']} {info['unit']} ({info['availability']}; eligible total unknown)"
            )) for task, records in sorted(s["reference_coverage"].items()) for info in records],
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
    return resolve_dataset_dir()


def _merge_expectations(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge_expectations(target[key], value)
        else:
            target[key] = value


def resolve_case(root: Path, *, require_pinned: bool = False) -> tuple[
    list[dict[str, str]], dict[str, Any], dict[str, Any]
]:
    """Resolve a case against the manifest contract or a legacy local copy."""
    root = Path(root)
    references = load_references(root, "036")
    if references is None:
        if require_pinned:
            raise DatasetReferenceError(
                f"pinned Dataset references manifest is missing at {root / 'references' / 'manifest.csv'}"
            )
        case = root / CASE_DIR
        if not (case / "ground_truth.csv").is_file():
            raise DatasetReferenceError(
                f"required math reference is unavailable at {case / 'ground_truth.csv'}: clone A11yDevs/acessilia-dataset "
                "into tests/dataset or set ACESSILIA_TEST_DATASET_DIR"
            )
        with (case / "ground_truth.csv").open(encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        expectations_path = case / "expectations.json"
        try:
            expectations = json.loads(expectations_path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise DatasetReferenceError(f"required math reference is unavailable: {expectations_path}") from error
        return rows, expectations, {
            "repository": "A11yDevs/acessilia-dataset",
            "revision": None,
            "references_digest": content_digest([case / "ground_truth.csv", expectations_path]),
            "references_schema_version": "legacy",
            "input_id": "036",
            "tasks": {task: {"availability": "legacy_unverified"} for task in MATH_TASKS},
        }

    pinned_identity = assert_pinned_dataset(root) if require_pinned else None
    expected_types = {
        "math_formula_transcription": "ground_truth",
        "math_text_quality": "expectations",
        "math_document_structure": "expectations",
        "math_formula_speech": "expectations",
    }
    rows: list[dict[str, str]] = []
    expectations: dict[str, Any] = {}
    for task in MATH_TASKS:
        task_rows = references.task_rows(task)
        if not task_rows:
            raise DatasetReferenceError(f"Dataset 036 is missing required task {task!r}")
        loaded_rows, loaded_expectations = references.read_task(task, expected_types[task])
        if task == "math_formula_transcription":
            rows.extend(loaded_rows)
        _merge_expectations(expectations, loaded_expectations)
    ids = [row.get("id", "") for row in rows]
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        raise DatasetReferenceError(f"Dataset 036 has duplicate criterion IDs: {duplicates}")
    known_ids = set(ids)
    linked_ids = {
        item.get("formula")
        for item in (
            expectations.get("speech", {}).get("formulas", [])
            + expectations.get("structure", {}).get("equation_numbers", [])
        )
    }
    missing_links = sorted(linked_ids - known_ids)
    if missing_links:
        raise DatasetReferenceError(f"Dataset 036 expectations reference unknown formula IDs: {missing_links}")
    for row in rows:
        try:
            if not row["id"] or int(row["page"]) < 1:
                raise ValueError("empty ID or non-positive page")
        except (KeyError, ValueError) as error:
            raise DatasetReferenceError(f"invalid math ground-truth row {row!r}: {error}") from error
    metadata = references.metadata()
    if pinned_identity is not None:
        metadata["revision"] = pinned_identity["revision"]
        metadata["expected_revision"] = pinned_identity["expected_revision"]
    return rows, expectations, metadata


def load_case(root: Path) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """The formula rows and the expectations of the case under ``root``."""
    rows, expectations, _metadata = resolve_case(root)
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
    """List runs, including explicitly numbered continuations after content.

    Extraction can split a list around an item's formula, paragraph or table,
    and give the next run a different parent. Across prose or tables, only an
    explicit matching next number and style establish continuation. A heading
    or page boundary always ends a run. Explicit restarts and changes of source
    parent without matching continuation numbering start separate runs.
    Legacy blocks without parent metadata retain adjacency-based grouping.
    """
    runs: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    interrupted = False
    expected_start = 1
    numbering = "decimal"
    previous_parent = None
    for block in blocks:
        kind = block.get("type")
        if _page(block) != page or kind == "heading":
            current = None
            interrupted = False
            continue
        if kind == "list":
            ordered = bool(block.get("ordered"))
            style = block.get("numbering", "decimal")
            start = block.get("start", 1)
            parent = (block.get("metadata") or {}).get("parent_id")
            explicit_continuation = (
                current is not None and current["ordered"] and ordered
                and style == numbering and "start" in block and start == expected_start
            )
            new_run = current is None or (
                interrupted and not explicit_continuation
            ) or (
                current["ordered"] != ordered or style != numbering
            ) or (
                "start" in block and start != expected_start
            ) or (
                parent != previous_parent and not explicit_continuation
            )
            if new_run:
                current = {"ordered": ordered, "items": []}
                runs.append(current)
            items = [str(i) for i in block.get("items") or [] if isinstance(i, str)]
            current["items"].extend(items)
            if new_run or "start" in block:
                expected_start = start
            expected_start += len(items)
            previous_parent = parent
            numbering = style
            interrupted = False
        elif kind in {"paragraph", "table"}:
            interrupted = True
        elif kind != "math":
            current = None
            interrupted = False
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


def _filter_expectations(
    expectations: dict[str, Any],
    selection: EvaluationSelection,
    rows: list[dict[str, str]],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Select expectation dependencies along with formula rows."""
    if selection.is_full_case:
        return expectations, []
    selected_ids = set(selection.object_ids)
    selected_pages = set(selection.pages)
    missing_pages = selected_pages - {int(row["page"]) for row in rows}
    if missing_pages:
        raise DatasetReferenceError(f"selected page(s) are absent from the reference: {sorted(missing_pages)}")
    missing_ids = selected_ids - {row.get("id", "") for row in rows}
    if missing_ids:
        raise DatasetReferenceError(f"selected object id(s) are absent from the reference: {sorted(missing_ids)}")
    if selected_ids and not selected_pages:
        selected_pages = {int(row["page"]) for row in rows if row["id"] in selected_ids}
    excluded: list[dict[str, str]] = []
    result: dict[str, Any] = {}

    def keep_page(item: dict[str, Any]) -> bool:
        return not selected_pages or item.get("page") in selected_pages

    text = expectations.get("text", {})
    if "math_text_quality" in selection.tasks or not selection.tasks:
        result["text"] = {"must_match": [], "must_not_match": []}
        for category in ("must_match", "must_not_match"):
            for spec in text.get(category, []):
                if selected_pages or selected_ids:
                    if "page" not in spec or spec.get("page") not in selected_pages:
                        excluded.append({"id": f"text:{spec['id']}", "reason": "document-wide text rule has no selected page/object scope"})
                        continue
                result["text"][category].append(spec)
    else:
        for category in ("must_match", "must_not_match"):
            excluded.extend({"id": f"text:{spec['id']}", "reason": "task not selected"} for spec in text.get(category, []))

    structure = expectations.get("structure", {})
    if "math_document_structure" in selection.tasks or not selection.tasks:
        selected_structure: dict[str, Any] = {}
        for key in ("headings", "ordered_lists", "tables"):
            items = structure.get(key, [])
            selected_structure[key] = []
            for item in items:
                criterion_id = {
                    "headings": f"heading:{item.get('text', '')}",
                    "ordered_lists": f"ordered-list:p{item.get('page', '')}",
                    "tables": f"table:p{item.get('page', '')}",
                }[key]
                related_ids = set(item.get("math_headers", [])) | set(item.get("math_cells", []))
                page_ok = keep_page(item)
                object_ok = not selected_ids or bool(related_ids & selected_ids)
                if page_ok and object_ok:
                    selected_structure[key].append(item)
                else:
                    excluded.append({"id": criterion_id, "reason": "outside selected page/object scope"})
        for key in ("equation_numbers",):
            selected_structure[key] = []
            for item in structure.get(key, []):
                formula_id = item.get("formula", "")
                formula_row = next((row for row in rows if row["id"] == formula_id), None)
                page_ok = not selected_pages or (formula_row is not None and int(formula_row["page"]) in selected_pages)
                object_ok = not selected_ids or formula_id in selected_ids
                if page_ok and object_ok:
                    selected_structure[key].append(item)
                else:
                    excluded.append({"id": f"equation-number:{formula_id}", "reason": "outside selected page/object scope"})
        page_numbers = structure.get("page_numbers") or {}
        if page_numbers.get("is_furniture"):
            pages = [p for p in page_numbers.get("pages", []) if not selected_pages or p in selected_pages]
            if pages and not selected_ids:
                selected_structure["page_numbers"] = {**page_numbers, "pages": pages}
            else:
                excluded.append({"id": "page-numbers:not-in-body", "reason": "outside selected page/object scope"})
        if "auto_numbered_headings" in structure:
            excluded.append({"id": "headings:not-auto-numbered", "reason": "document-wide structure rule has no selected page/object scope"})
        for key in ("images", "callouts", "page_header"):
            for idx, _item in enumerate(structure.get(key, [] if key != "page_header" else [structure.get(key)])):
                if _item:
                    excluded.append({"id": f"{key}:{idx + 1}", "reason": "criterion unsupported by this evaluator"})
        result["structure"] = selected_structure
    else:
        for key in ("headings", "ordered_lists", "tables", "equation_numbers"):
            excluded.extend({"id": f"{key}:{i + 1}", "reason": "task not selected"} for i, _ in enumerate(structure.get(key, [])))

    speech = expectations.get("speech", {})
    if "math_formula_speech" in selection.tasks or not selection.tasks:
        selected_formulas = []
        for spec in speech.get("formulas", []):
            formula_id = spec["formula"]
            formula_row = next((row for row in rows if row["id"] == formula_id), None)
            page_ok = not selected_pages or (formula_row is not None and int(formula_row["page"]) in selected_pages)
            object_ok = not selected_ids or formula_id in selected_ids
            if page_ok and object_ok:
                selected_formulas.append(spec)
            else:
                excluded.append({"id": f"speech:{formula_id}", "reason": "outside selected page/object scope"})
        result["speech"] = {**speech, "formulas": selected_formulas}
    else:
        excluded.extend({"id": f"speech:{item['formula']}", "reason": "task not selected"} for item in speech.get("formulas", []))
    return result, excluded


def score_case(
    rows: list[dict[str, str]],
    expectations: dict[str, Any],
    document: dict[str, Any],
    txt: str,
    pdf_text: str | None = None,
    *,
    selection: EvaluationSelection | None = None,
    dataset_metadata: dict[str, Any] | None = None,
) -> Scorecard:
    selection = selection or EvaluationSelection()
    selected_tasks = set(selection.tasks)
    if selected_tasks:
        unknown_tasks = selected_tasks - set(MATH_TASKS)
        if unknown_tasks:
            raise ValueError(f"unknown math evaluation task(s): {sorted(unknown_tasks)}")
    selected_ids = set(selection.object_ids)
    selected_pages = set(selection.pages)
    selected_rows = [
        row for row in rows
        if (not selected_pages or int(row["page"]) in selected_pages)
        and (not selected_ids or row["id"] in selected_ids)
    ]
    filtered_expectations, excluded = _filter_expectations(expectations, selection, rows)
    excluded.extend(
        {"id": row["id"], "reason": "outside selected page/object scope"}
        for row in rows if row not in selected_rows
    )
    blocks = list(iter_blocks(document))
    by_kind: dict[str, list[dict[str, str]]] = {}
    supported_kinds = {"display", "inline", "table-header", "table-cell"}
    unsupported = [row for row in selected_rows if row["kind"] not in supported_kinds]
    for row in selected_rows:
        by_kind.setdefault(row["kind"], []).append(row)

    run_formula = not selected_tasks or "math_formula_transcription" in selected_tasks
    run_text = not selected_tasks or "math_text_quality" in selected_tasks
    run_structure = not selected_tasks or "math_document_structure" in selected_tasks
    run_speech = not selected_tasks or "math_formula_speech" in selected_tasks
    if not run_formula:
        excluded.extend({
            "id": row["id"],
            "reason": (
                "formula transcription task not selected; row is used only as a dependency"
                if run_structure or run_speech else "formula transcription task not selected"
            ),
        } for row in selected_rows)
    if run_structure:
        for key in ("images", "callouts"):
            for index, _criterion in enumerate(filtered_expectations.get("structure", {}).get(key, [])):
                excluded.append({
                    "id": f"{key}:{index + 1}",
                    "reason": "unsupported criterion: the math scorecard has no matching image/callout evaluator",
                })
        if filtered_expectations.get("structure", {}).get("page_header"):
            excluded.append({
                "id": "page-header",
                "reason": "unsupported criterion: page-header text is not independently evaluated",
            })

    card = Scorecard(
        dataset=dataset_metadata or {},
        selection=selection.to_dict(),
        not_evaluated=excluded + [
            {"id": row["id"], "reason": f"unsupported criterion kind {row['kind']!r}"}
            for row in unsupported
        ],
    )
    dependency_display_rows = by_kind.get("display", []) if (run_formula or run_structure or run_speech) else []
    matched_display = _match_display(dependency_display_rows, blocks)
    if run_formula or run_speech:
        card.speech_presence_checks = [
            Check(
                f"speech-presence:{item['id']}",
                bool(item["speech"]),
                "" if item["speech"] else "no spoken form",
            )
            for item in matched_display
        ]
    if run_formula:
        card.display = matched_display
        card.inline = _score_inline(by_kind.get("inline", []), blocks)
        card.tables = _score_tables(by_kind.get("table-header", []) + by_kind.get("table-cell", []), blocks)
    targets = {"txt": txt}
    if pdf_text is not None:
        targets["pdf_ua"] = pdf_text
    card.outputs = list(targets)
    if run_text:
        card.text = _text_checks(filtered_expectations.get("text", {}), targets)
    if run_structure:
        card.structure = _structure_checks(
            filtered_expectations.get("structure", {}), document, blocks, matched_display, pdf_text
        )
    if run_speech:
        card.speech = _speech_checks(filtered_expectations.get("speech", {}), matched_display)
    card.criteria_ids = [
        *[item["id"] for item in card.display],
        *[check.id for check in card.speech_presence_checks],
        *[item["id"] for item in card.inline],
        *[item["id"] for item in card.tables],
        *[check.id for check in (*card.text, *card.structure, *card.speech)],
    ]
    if dataset_metadata:
        for task, info in dataset_metadata.get("tasks", {}).items():
            if info.get("availability") == "unannotated":
                card.not_evaluated.append({"id": task, "reason": "task is marked unannotated in the reference manifest"})
    return card


def pdf_text(path: Path) -> str:
    """Text of a PDF in reading order, as ``pdftotext`` (poppler) extracts it."""
    if shutil.which("pdftotext") is None:
        raise RuntimeError("pdftotext (poppler-utils) is required to score a PDF/UA output")
    return subprocess.run(
        ["pdftotext", "-enc", "UTF-8", str(path), "-"],
        check=True, capture_output=True, text=True,
    ).stdout


def _file_sha256(path: Path | None) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path is not None and path.is_file() else None


def _pdftotext_version() -> str | None:
    if shutil.which("pdftotext") is None:
        return None
    result = subprocess.run(["pdftotext", "-v"], capture_output=True, text=True, check=False)
    version = (result.stderr or result.stdout).splitlines()
    return version[0] if version else None


def _safe_inference_configuration() -> dict[str, Any]:
    """Record provider/model selectors without URLs, tokens, or credentials."""
    from backend.config.settings import settings

    model = (
        settings.ollama_model if settings.ai_client == "ollama"
        else settings.openrouter_model if settings.ai_client == "openrouter"
        else None
    )
    return {
        "ai_client": settings.ai_client,
        "model": model,
        "toolbox_math_recognize_provider": settings.toolbox_math_recognize_provider,
        "toolbox_math_provider": settings.toolbox_math_provider,
    }


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


def _write(card: Scorecard, out: Path | None, *, run_config: dict[str, Any] | None = None) -> None:
    print(card.to_markdown(), end="")
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        existing_artifacts = {path.name for path in out.iterdir() if path.is_file()}
        (out / "scorecard.json").write_text(
            json.dumps(card.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (out / "scorecard.md").write_text(card.to_markdown(), encoding="utf-8")
        (out / "run-metadata.json").write_text(json.dumps({
            "status": card.evaluation_status,
            "protocol_version": PROTOCOL_VERSION,
            "core_revision": git_revision(REPO),
            "dataset": card.dataset,
            "selection": card.selection,
            "criteria_ids": card.criteria_ids,
            "configuration": run_config or {},
            "runtime": {
                "python": platform.python_version(),
                "pdftotext": _pdftotext_version() if "pdf_ua" in card.outputs else None,
            },
            "artifacts": sorted(existing_artifacts | {
                "scorecard.json", "scorecard.md", "run-metadata.json",
            }),
            "artifact_storage": {
                "directory": str(out.resolve()),
                "retention": "operator-managed; artifacts remain until explicitly removed",
                "observability_export": False,
            },
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _failure_status(error: Exception) -> str:
    message = str(error).casefold()
    if isinstance(error, DatasetReferenceError):
        if "schema" in message or "version" in message:
            return "invalid_reference_format_or_version"
        if "missing" in message or "no rows" in message or "no " in message or "unavailable" in message:
            return "reference_unavailable"
        return "invalid_reference"
    if isinstance(error, FileNotFoundError):
        return "missing_artifact"
    if isinstance(error, (json.JSONDecodeError, subprocess.CalledProcessError)):
        return "invalid_artifact_format"
    return "execution_failure"


def _write_failure(
    out: Path | None,
    *,
    error: Exception,
    stage: str,
    dataset_root: Path,
    selection: EvaluationSelection,
) -> None:
    status = _failure_status(error)
    message = f"{status} during {stage}: {type(error).__name__}: {error}"
    print(message, file=sys.stderr)
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        (out / "scorecard.json").unlink(missing_ok=True)
        (out / "scorecard.md").unlink(missing_ok=True)
        record = {
            "status": status,
            "stage": stage,
            "error_type": type(error).__name__,
            "error": str(error),
            "dataset_root": str(dataset_root),
            "selection": selection.to_dict(),
            "protocol_version": PROTOCOL_VERSION,
            "core_revision": git_revision(REPO),
            "artifact_storage": {
                "directory": str(out.resolve()),
                "retention": "operator-managed; artifacts remain until explicitly removed",
                "observability_export": False,
            },
        }
        (out / "run-metadata.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.bench.math_case", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dataset", type=Path, help="acessilia-dataset clone (default: $ACESSILIA_TEST_DATASET_DIR or tests/dataset)")
    parser.add_argument("--require-pinned-dataset", action="store_true", help="require the Dataset revision/digest in scripts/bench/dataset.lock.json")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("score", help="score a job's outputs")
    p.add_argument("--canonical", type=Path, required=True, help="canonical document JSON")
    p.add_argument("--txt", type=Path, required=True, help="plain-text output")
    p.add_argument("--pdf-ua", type=Path, help="PDF/UA output (needs pdftotext)")
    p.add_argument("--out", type=Path, help="also write scorecard.json and scorecard.md here")
    p.add_argument("--task", action="append", choices=MATH_TASKS, help="evaluate only this task (repeatable)")
    p.add_argument("--page", action="append", type=int, help="evaluate only this page (repeatable)")
    p.add_argument("--object-id", action="append", help="evaluate only this reference object (repeatable)")
    p = sub.add_parser("run", help="process the reference PDF, then score it")
    p.add_argument("--pdf", type=Path, help="input PDF (default: the dataset's copy)")
    p.add_argument("--out", type=Path, help="per-run artifact directory; defaults to a UTC timestamp under var/bench/math-reference/")
    p.add_argument("--no-pdf-ua", action="store_true", help="skip the PDF/UA export")
    p.add_argument("--task", action="append", choices=MATH_TASKS, help="evaluate only this task (repeatable)")
    p.add_argument("--page", action="append", type=int, help="evaluate only this page (repeatable)")
    p.add_argument("--object-id", action="append", help="evaluate only this reference object (repeatable)")
    args = parser.parse_args(argv)

    root = args.dataset or dataset_dir()
    selection = EvaluationSelection(
        tasks=tuple(args.task or ()),
        pages=tuple(args.page or ()),
        object_ids=tuple(args.object_id or ()),
    )
    out = args.out
    if args.command == "run" and out is None:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = REPO / "var" / "bench" / "math-reference" / run_id
    stage = "reference_resolution"
    try:
        rows, expectations, dataset_metadata = resolve_case(root, require_pinned=args.require_pinned_dataset)
        if selection.object_ids:
            known = {row["id"] for row in rows}
            missing = set(selection.object_ids) - known
            if missing:
                raise DatasetReferenceError(f"selected object id(s) are absent from the reference: {sorted(missing)}")
        if args.command == "run":
            import asyncio

            stage = "execution"
            pdf = args.pdf or root / CASE_DIR / CASE_PDF
            canonical_path, txt_path, pdf_ua_path = asyncio.run(
                _process(pdf, out, pdf_ua=not args.no_pdf_ua)
            )
        else:
            canonical_path, txt_path, pdf_ua_path = args.canonical, args.txt, args.pdf_ua

        stage = "artifact_read"
        document = json.loads(canonical_path.read_text(encoding="utf-8"))
        card = score_case(
            rows, expectations, document,
            txt_path.read_text(encoding="utf-8"),
            pdf_text(pdf_ua_path) if pdf_ua_path else None,
            selection=selection,
            dataset_metadata=dataset_metadata,
        )
        _write(card, out, run_config={
            "dataset_root": str(root),
            "require_pinned_dataset": args.require_pinned_dataset,
            "input_pdf": str((args.pdf or root / CASE_DIR / CASE_PDF).resolve()) if args.command == "run" else None,
            "input_pdf_sha256": _file_sha256(args.pdf or root / CASE_DIR / CASE_PDF) if args.command == "run" else None,
            "output_mode": ["txt"] + (["pdf_ua"] if pdf_ua_path else []),
            "inference": _safe_inference_configuration() if args.command == "run" else None,
        })
        return 0
    except Exception as error:  # persist an explicit execution/contract failure for each run
        _write_failure(out, error=error, stage=stage, dataset_root=root, selection=selection)
        return 1


if __name__ == "__main__":
    sys.exit(main())
