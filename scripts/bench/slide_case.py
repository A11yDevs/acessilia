"""Scorecard of a slide-deck case (acessilia-dataset ``presentation-reference``).

    python -m scripts.bench.slide_case score   --pdf-ua out.pdf_ua.pdf  [--out var/bench/slides/<run>]
    python -m scripts.bench.slide_case score   --txt out.txt
    python -m scripts.bench.slide_case compare base.pdf_ua.pdf candidate.pdf_ua.pdf

Ground truth comes from task selectors in ``references/manifest.csv``
(Dataset input ``006``) at ``$ACESSILIA_TEST_DATASET_DIR`` (default
``tests/dataset``). Legacy local ``input/presentation-reference/`` copies
remain readable during migration. The case describes ``006.pdf``, a 42-slide
chemistry deck.

The output is read as a reader gets it: plain text (TXT, or the PDF/UA through
``pdftotext -layout``) split into one section per ``Slide N de 42`` heading. A
table row of a PDF/UA may also be found in its content-stream order
(``pdftotext -raw``): there a cell that wraps onto two lines stays whole,
where the layout interleaves its second line with the next cell. Every
ground-truth object is checked inside its slide's section:

- ``text``: the passage is there;
- ``image`` / ``chemical-structure``: the description holds the expected
  terms (``;`` between terms, ``|`` between alternatives);
- ``table-header`` / ``table-row``: the row's cells are there, in order and
  next to each other, so a table collapsed into one row or read as loose
  cells fails;
- ``formula``: most words and numbers of the formula are there.

and each section against ``expectations.json``'s ``must_not_match`` patterns
(an undescribed picture, a list of folded labels, raw LaTeX...). Comparing two
outputs gives the slides that got worse, which is what a regression is here.
Like the rest of the harness, the numbers track deltas between runs.
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
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from scripts.bench.dataset_reference import (
    DatasetReferenceError,
    EvaluationSelection,
    assert_pinned_dataset,
    content_digest,
    dataset_dir,
    git_revision,
    load_references,
)

CASE_DIR = Path("input") / "presentation-reference"
SLIDE_TASKS = (
    "presentation_slide_content",
    "presentation_output_safety",
    "presentation_structure",
    "presentation_degraded_run_behavior",
)
PROTOCOL_VERSION = "presentation-reference-v3"

#: A slide heading as the exporters write it, in pt-BR or English. A page
#: break also starts a line: ``pdftotext -raw`` may end the previous page with
#: its footer number and no newline ("1\f1.3 Slide 3 de 42").
SLIDE_HEADING = re.compile(
    r"(?:^|(?<=\f))\s*(?:\d+(?:\.\d+)*\s+)?Slide (\d+) (?:de|of) (\d+)\b", re.MULTILINE
)

#: Share of an image's terms its description must hold to count as described.
TERM_RECALL_PASS = 0.6

#: Share of a formula's words and numbers the slide must hold.
FORMULA_RECALL_PASS = 0.8

#: Most normalized characters between two consecutive cells of a row: a row
#: read whole keeps its cells next to each other, a table collapsed into one
#: row per column puts a whole column between them (006.pdf slide 5).
ROW_GAP = 24

#: Violations that mean a picture on the slide went undescribed. A slide that
#: has one only passes a picture whose terms are all there: its labels alone
#: hold most of them.
FALLBACK_VIOLATIONS = frozenset({"undescribed-picture", "label-list-alt"})

#: Detail of a table row the layout missed and the stream order found whole:
#: the scorecard keeps it apart from a row the layout reads right.
STREAM_ORDER_DETAIL = "row found whole only in stream order"


# ── Normalization ───────────────────────────────────────────────────


_DASHES = str.maketrans({"—": "-", "–": "-", "−": "-", "‐": "-"})


def normalize(text: str) -> str:
    """Text reduced for matching: NFKC (²→2, ₂→2, µ→μ), dashes, case, no spaces.

    Line-end hyphenation is joined first, and every space goes, because a PDF
    text layer breaks lines wherever the page did.
    """
    text = unicodedata.normalize("NFKC", text or "").translate(_DASHES)
    text = re.sub(r"-\s*\n\s*", "", text)
    return re.sub(r"\s+", "", text.casefold())


def _latex_words(latex: str) -> list[str]:
    """Words and numbers of a LaTeX formula, commands and braces left out."""
    plain = re.sub(r"\\(?:text|mathrm|operatorname)\s*\{([^}]*)\}", r" \1 ", latex)
    plain = re.sub(r"\\[A-Za-z]+", " ", plain)
    return [normalize(word) for word in re.findall(r"[^\W_]+(?:[,.][^\W_]+)*", plain) if word]


# ── Case ────────────────────────────────────────────────────────────


def _merge_expectations(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge_expectations(target[key], value)
        else:
            target[key] = value


def resolve_case(root: Path, *, require_pinned: bool = False) -> tuple[
    list[dict[str, str]], dict[str, Any], dict[str, Any]
]:
    """Resolve presentation references through the new or legacy layout."""
    root = Path(root)
    references = load_references(root, "006")
    if references is None:
        if require_pinned:
            raise DatasetReferenceError(
                f"pinned Dataset references manifest is missing at {root / 'references' / 'manifest.csv'}"
            )
        case = root / CASE_DIR
        if not (case / "ground_truth.csv").is_file():
            raise DatasetReferenceError(
                f"required presentation reference is unavailable at {case / 'ground_truth.csv'}: clone A11yDevs/acessilia-dataset "
                "into tests/dataset or set ACESSILIA_TEST_DATASET_DIR"
            )
        with (case / "ground_truth.csv").open(encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        expectations_path = case / "expectations.json"
        try:
            expectations = json.loads(expectations_path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise DatasetReferenceError(f"required presentation reference is unavailable: {expectations_path}") from error
        return rows, expectations, {
            "repository": "A11yDevs/acessilia-dataset",
            "revision": None,
            "references_digest": content_digest([case / "ground_truth.csv", expectations_path]),
            "references_schema_version": "legacy",
            "input_id": "006",
            "tasks": {task: {"availability": "legacy_unverified"} for task in SLIDE_TASKS},
        }

    pinned_identity = assert_pinned_dataset(root) if require_pinned else None
    reference_specs = (
        ("presentation_slide_content", "ground_truth", "content"),
        ("presentation_output_safety", "expectations", "expectations"),
        ("presentation_structure", "expectations", "expectations"),
        ("presentation_structure", "ground_truth", "structure_rows"),
        ("presentation_degraded_run_behavior", "expectations", "expectations"),
    )
    rows: list[dict[str, str]] = []
    content_rows: list[dict[str, str]] = []
    structure_rows: list[dict[str, str]] = []
    expectations: dict[str, Any] = {}
    for task, reference_type, destination in reference_specs:
        if not references.task_rows(task):
            raise DatasetReferenceError(f"Dataset 006 is missing required task {task!r}")
        loaded_rows, loaded_expectations = references.read_task(task, reference_type)
        if destination == "content":
            content_rows.extend(loaded_rows)
        elif destination == "structure_rows":
            structure_rows.extend(loaded_rows)
        else:
            _merge_expectations(expectations, loaded_expectations)

    content_ids = [row.get("id", "") for row in content_rows]
    structure_ids = [row.get("id", "") for row in structure_rows]
    if any(not item for item in (*content_ids, *structure_ids)):
        raise DatasetReferenceError("Dataset 006 has a presentation reference row with an empty criterion ID")
    if len(content_ids) != len(set(content_ids)):
        raise DatasetReferenceError("Dataset 006 presentation content selector has duplicate criterion IDs")
    if len(structure_ids) != len(set(structure_ids)):
        raise DatasetReferenceError("Dataset 006 presentation structure selector has duplicate criterion IDs")
    structure_id_set = set(structure_ids)
    content_by_id = {row["id"]: row for row in content_rows}
    for row in structure_rows:
        if row.get("kind") != "table":
            raise DatasetReferenceError(
                f"Dataset 006 presentation structure selector includes non-table criterion {row['id']!r}"
            )
        existing = content_by_id.get(row["id"])
        if existing is not None and existing != row:
            raise DatasetReferenceError(
                f"Dataset 006 has conflicting shared criterion {row['id']!r}"
            )
    rows.extend(content_rows)
    rows.extend(row for row in structure_rows if row["id"] not in content_by_id)
    ids = [row.get("id", "") for row in rows]
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        raise DatasetReferenceError(f"Dataset 006 has duplicate criterion IDs: {duplicates}")
    for row in rows:
        try:
            if not row["id"] or int(row["page"]) < 1:
                raise ValueError("empty ID or non-positive page")
        except (KeyError, ValueError) as error:
            raise DatasetReferenceError(f"invalid presentation ground-truth row {row!r}: {error}") from error
    metadata = references.metadata()
    if pinned_identity is not None:
        metadata["revision"] = pinned_identity["revision"]
        metadata["expected_revision"] = pinned_identity["expected_revision"]
    metadata["task_criterion_ids"] = {
        "presentation_slide_content": sorted(set(content_ids) - structure_id_set),
        "presentation_structure": sorted(structure_id_set),
    }
    return rows, expectations, metadata


def load_case(root: Path) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """The object rows and the expectations of the case under ``root``."""
    rows, expectations, _metadata = resolve_case(root)
    return rows, expectations


def split_slides(text: str) -> dict[int, str]:
    """The text of each slide, from its heading to the next one.

    Anything before the first heading (the deck title) goes to slide 1.
    """
    matches = list(SLIDE_HEADING.finditer(text))
    sections: dict[int, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        start = 0 if index == 0 else match.start()
        sections[int(match.group(1))] = sections.get(int(match.group(1)), "") + text[start:end]
    return sections


# ── Scoring ─────────────────────────────────────────────────────────


@dataclass
class ObjectResult:
    id: str
    page: int
    kind: str
    passed: bool
    score: float
    detail: str = ""


@dataclass
class CheckResult:
    id: str
    page: int | None
    passed: bool
    detail: str = ""


@dataclass
class Scorecard:
    output: str
    slides_found: int
    slide_count: int
    objects: list[ObjectResult] = field(default_factory=list)
    violations: dict[int, list[str]] = field(default_factory=dict)
    safety_checks: list[CheckResult] = field(default_factory=list)
    structure_checks: list[CheckResult] = field(default_factory=list)
    dataset: dict[str, Any] = field(default_factory=dict)
    selection: dict[str, Any] = field(default_factory=lambda: EvaluationSelection().to_dict())
    criteria_ids: list[str] = field(default_factory=list)
    not_evaluated: list[dict[str, str]] = field(default_factory=list)
    output_mode: str = "txt"
    protocol_version: str = PROTOCOL_VERSION

    def slide_scores(self) -> dict[int, dict[str, Any]]:
        """Per slide: objects passed, their share, and the patterns it broke."""
        out: dict[int, dict[str, Any]] = {}
        for page in range(1, self.slide_count + 1):
            objects = [o for o in self.objects if o.page == page]
            passed = sum(o.passed for o in objects)
            out[page] = {
                "passed": passed,
                "total": len(objects),
                "score": round(100 * passed / len(objects), 1) if objects else None,
                "status": "evaluated" if objects else "not_evaluated",
                "stream_order": sum(o.detail == STREAM_ORDER_DETAIL for o in objects),
                "violations": self.violations.get(page, []),
            }
        return out

    def summary(self) -> dict[str, Any]:
        by_kind: dict[str, list[ObjectResult]] = {}
        for o in self.objects:
            by_kind.setdefault(o.kind, []).append(o)
        return {
            "output": self.output,
            "dataset": self.dataset,
            "selection": self.selection,
            "criteria_ids": list(self.criteria_ids),
            "not_evaluated": list(self.not_evaluated),
            "structure_checks": {
                "passed": sum(check.passed for check in self.structure_checks),
                "total": len(self.structure_checks),
                "status": "evaluated" if self.structure_checks else "not_evaluated",
            },
            "safety_checks": {
                "passed": sum(check.passed for check in self.safety_checks),
                "total": len(self.safety_checks),
                "status": "evaluated" if self.safety_checks else "not_evaluated",
            },
            "protocol_version": self.protocol_version,
            "output_mode": self.output_mode,
            "slides_found": f"{self.slides_found}/{self.slide_count}",
            "objects_passed": (
                f"{sum(o.passed for o in self.objects)}/{len(self.objects)}"
                if self.objects else "not evaluated (no supported object criteria in this selection)"
            ),
            "by_kind": {
                kind: f"{sum(o.passed for o in items)}/{len(items)}"
                for kind, items in sorted(by_kind.items())
            },
            "stream_order": sum(o.detail == STREAM_ORDER_DETAIL for o in self.objects),
            "violations": sum(len(v) for v in self.violations.values()),
            "reference_status": {
                task: info.get("availability")
                for task, info in self.dataset.get("tasks", {}).items()
            },
            "reference_coverage": {
                task: [
                    {
                        "reference_type": record.get("reference_type"),
                        "format": record.get("format"),
                        "availability": record.get("availability"),
                        "annotated": record.get("annotated_count"),
                        "eligible": record.get("eligible_count"),
                        "unit": record.get("coverage_unit"),
                        "scope": record.get("coverage_scope"),
                    }
                    for record in (info.get("references") or [info])
                ]
                for task, info in self.dataset.get("tasks", {}).items()
            },
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary(),
            "slides": self.slide_scores(),
            "objects": [o.__dict__ for o in self.objects],
            "structure_checks": [check.__dict__ for check in self.structure_checks],
            "safety_checks": [check.__dict__ for check in self.safety_checks],
            "dataset": self.dataset,
            "selection": self.selection,
            "criteria_ids": list(self.criteria_ids),
            "not_evaluated": list(self.not_evaluated),
            "protocol_version": self.protocol_version,
            "output_mode": self.output_mode,
        }

    def to_markdown(self) -> str:
        s = self.summary()
        lines = [
            f"Output: {s['output']}", "",
            "| Metric | Value |", "|---|---|",
            f"| Slides found | {s['slides_found']} |",
            f"| Objects passed | {s['objects_passed']} |",
            f"| Structure checks | {s['structure_checks']['passed']}/{s['structure_checks']['total']} ({s['structure_checks']['status']}) |",
            f"| Output-safety checks | {s['safety_checks']['passed']}/{s['safety_checks']['total']} ({s['safety_checks']['status']}) |",
            *(f"| {kind} | {value} |" for kind, value in s["by_kind"].items()),
            f"| Rows found only in stream order | {s['stream_order']} |",
            f"| Pattern violations | {s['violations']} |",
            f"| Dataset revision / references digest | {self.dataset.get('revision') or 'unavailable'} / {self.dataset.get('references_digest') or 'unavailable'} |",
            *(f"| Coverage: {task} [{info['reference_type'] or 'reference'}] | "
              f"{info['annotated']}/{info['eligible'] or '?'} {info['unit']} ({info['scope']}) |"
              for task, records in sorted(s["reference_coverage"].items()) for info in records),
            "", "| Slide | Passed | Score | Stream order | Violations |", "|---|---|---|---|---|",
        ]
        for page, slide in self.slide_scores().items():
            score = "—" if slide["score"] is None else f"{slide['score']:.0f}%"
            passed = f"{slide['passed']}/{slide['total']}" if slide["total"] else "not evaluated"
            lines.append(
                f"| {page} | {passed} | {score} | "
                f"{slide['stream_order'] or ''} | {', '.join(slide['violations']) or ''} |"
            )
        return "\n".join(lines) + "\n"


def _terms_recall(expected: str, section: str) -> tuple[float, list[str]]:
    terms = [term for term in expected.split(";") if term.strip()]
    missing = [
        term for term in terms
        if not any(normalize(alt) and normalize(alt) in section for alt in term.split("|"))
    ]
    return (1 - len(missing) / len(terms) if terms else 1.0), missing


def _row_found(cells: list[str], section: str, gap: int = ROW_GAP) -> bool:
    """Whether the non-empty ``cells`` occur in order, at most ``gap`` apart."""
    wanted = [normalize(cell) for cell in cells if normalize(cell)]
    if not wanted:
        return True
    start = 0
    while True:
        first = section.find(wanted[0], start)
        if first < 0:
            return False
        position, ok = first + len(wanted[0]), True
        for cell in wanted[1:]:
            found = section.find(cell, position)
            if found < 0 or found - position > gap:
                ok = False
                break
            position = found + len(cell)
        if ok:
            return True
        start = first + 1


def score_object(
    row: dict[str, str], section: str, *, fallback: bool = False, row_gap: int = ROW_GAP
) -> ObjectResult:
    """One ground-truth object against its slide's normalized section.

    ``fallback`` says the slide shows an undescribed picture; its pictures then
    pass only with every term. ``row_gap`` bounds the characters between two
    cells of a table row.
    """
    kind, expected = row["kind"], row["expected"]
    base = {"id": row["id"], "page": int(row["page"]), "kind": kind}
    if kind == "text":
        found = normalize(expected) in section
        return ObjectResult(**base, passed=found, score=float(found), detail="" if found else "missing")
    if kind in {"image", "chemical-structure"}:
        recall, missing = _terms_recall(expected, section)
        needed = 1.0 if fallback else TERM_RECALL_PASS
        return ObjectResult(
            **base, passed=recall >= needed, score=round(recall, 3),
            detail=f"missing: {'; '.join(missing)}" if missing else "",
        )
    if kind in {"table-header", "table-row"}:
        found = _row_found(expected.split(" | "), section, row_gap)
        return ObjectResult(**base, passed=found, score=float(found), detail="" if found else "row not found whole")
    if kind == "formula":
        words = _latex_words(expected)
        hits = [word for word in words if word in section]
        recall = len(hits) / len(words) if words else 1.0
        return ObjectResult(**base, passed=recall >= FORMULA_RECALL_PASS, score=round(recall, 3))
    if kind == "table":
        return ObjectResult(**base, passed=True, score=1.0, detail="scored by its rows")
    raise ValueError(f"unknown ground-truth kind {kind!r} ({row['id']})")


def score_text(
    rows: list[dict[str, str]],
    expectations: dict[str, Any],
    text: str,
    output: str,
    *,
    stream_text: str | None = None,
    selection: EvaluationSelection | None = None,
    dataset_metadata: dict[str, Any] | None = None,
) -> Scorecard:
    """Score ``text``; a table row it misses may still be found in ``stream_text``.

    ``stream_text`` is the same output in content-stream order (a PDF/UA through
    ``pdftotext -raw``). The layout keeps each row on its line, but a header
    cell that wraps ("Atomic Mass of the Isotope / (u)", 006.pdf slide 15)
    has its second line interleaved with the next cell; the stream order keeps
    it whole. There the cells must be next to each other: a collapsed table
    lists every name before any symbol, but its last name and the first symbol
    and power can still fall within ``ROW_GAP`` (006.pdf slide 5, "hecto deca
    / ... h da 10^24").
    """
    selection = selection or EvaluationSelection()
    selected_tasks = set(selection.tasks)
    if selected_tasks - set(SLIDE_TASKS):
        raise ValueError(f"unknown presentation evaluation task(s): {sorted(selected_tasks - set(SLIDE_TASKS))}")
    all_ids = {row["id"] for row in rows}
    missing_ids = set(selection.object_ids) - all_ids
    if missing_ids:
        raise DatasetReferenceError(f"selected object id(s) are absent from the reference: {sorted(missing_ids)}")
    selected_pages = set(selection.pages)
    missing_pages = selected_pages - {int(row["page"]) for row in rows}
    if missing_pages:
        raise DatasetReferenceError(f"selected page(s) are absent from the reference: {sorted(missing_pages)}")
    if selection.object_ids and not selected_pages:
        selected_pages = {int(row["page"]) for row in rows if row["id"] in selection.object_ids}
    content_task = not selected_tasks or "presentation_slide_content" in selected_tasks
    safety_task = not selected_tasks or "presentation_output_safety" in selected_tasks
    structure_task = not selected_tasks or "presentation_structure" in selected_tasks
    task_criterion_ids = (dataset_metadata or {}).get("task_criterion_ids")
    has_task_criterion_ids = isinstance(task_criterion_ids, dict)
    selected_task_row_ids: set[str] = set()
    if has_task_criterion_ids:
        scoped_tasks = selected_tasks or set(task_criterion_ids)
        for task in scoped_tasks:
            selected_task_row_ids.update(task_criterion_ids.get(task, []))
        wrong_task_ids = set(selection.object_ids) - selected_task_row_ids if selected_tasks else set()
        if wrong_task_ids:
            raise DatasetReferenceError(
                f"selected object ID(s) are outside the selected task scope: {sorted(wrong_task_ids)}"
            )

    def object_selected(row: dict[str, str]) -> bool:
        if not selection.object_ids:
            return True
        if row["id"] in selection.object_ids:
            return True
        return row["kind"] == "table" and any(
            object_id.startswith(row["id"] + "-") for object_id in selection.object_ids
        )

    selected_rows = [
        row for row in rows
        if (not selected_pages or int(row["page"]) in selected_pages)
        and object_selected(row)
        and (
            row["id"] in selected_task_row_ids
            if has_task_criterion_ids
            else (content_task or (structure_task and row["kind"] == "table"))
        )
    ]
    declared_slide_count = int(expectations.get("structure", {}).get("slide_count", 0))
    reference_pages = {int(row["page"]) for row in rows}
    slide_count = declared_slide_count or max(reference_pages, default=0)
    sections = split_slides(text)
    normalized = {page: normalize(body) for page, body in sections.items()}
    # The headings are matched before normalizing, so a slide whose heading
    # the stream order breaks across lines ("Slide 15" / "de 42") is left out
    # here, and its rows get no second chance: the layout result stands.
    streamed = (
        {page: normalize(body) for page, body in split_slides(stream_text).items()}
        if stream_text is not None
        else {}
    )
    output_suffix = Path(output).suffix.casefold()
    output_mode = "pdf_ua" if output_suffix == ".pdf" else "txt" if output_suffix == ".txt" else "unspecified"
    identity = dict(dataset_metadata or {})
    if not identity.get("references_digest"):
        reference_content = json.dumps([rows, expectations], sort_keys=True).encode("utf-8")
        identity["references_digest"] = hashlib.sha256(reference_content).hexdigest()
    card = Scorecard(
        output=output,
        slides_found=len(sections),
        slide_count=slide_count,
        dataset=identity,
        selection=selection.to_dict(),
        output_mode=output_mode,
    )
    if content_task:
        for row in rows:
            if row["kind"] != "table" and row not in selected_rows:
                card.not_evaluated.append({"id": row["id"], "reason": "outside selected page/object scope"})
    else:
        card.not_evaluated.extend(
            {"id": row["id"], "reason": "content task not selected; row not scored"}
            for row in rows if row["kind"] != "table"
        )
    if structure_task:
        for row in rows:
            if row["kind"] == "table" and row not in selected_rows:
                card.not_evaluated.append({"id": row["id"], "reason": "outside selected page/object scope"})
            elif row["kind"] == "table" and row in selected_rows:
                card.not_evaluated.append({
                    "id": row["id"],
                    "reason": "unsupported criterion: table shape needs structured output, but this evaluator reads text only",
                })
    else:
        card.not_evaluated.extend(
            {"id": row["id"], "reason": "structure task not selected"}
            for row in rows if row["kind"] == "table"
        )
        card.not_evaluated.append({"id": "presentation_structure", "reason": "task not selected"})

    if declared_slide_count:
        reference_pages = set(range(1, declared_slide_count + 1))
    criteria_scope_pages = sorted(selected_pages or reference_pages)
    rules = expectations.get("text", {}).get("must_not_match", [])
    score_safety = safety_task and not selection.object_ids
    if safety_task and not score_safety:
        card.not_evaluated.extend(
            {"id": f"safety:{rule['id']}", "reason": "document-safety rule is not linked to an individual object"}
            for rule in rules
        )
    if not safety_task:
        card.not_evaluated.extend(
            {"id": f"safety:{rule['id']}", "reason": "task not selected"}
            for rule in rules
        )
    image_pages = {
        int(row["page"]) for row in selected_rows if row["kind"] in {"image", "chemical-structure"}
    }
    fallback_pages: set[int] = set()
    for rule in rules:
        detects_fallback = rule["id"] in FALLBACK_VIOLATIONS
        pages = criteria_scope_pages if score_safety else (image_pages if detects_fallback else ())
        if not pages:
            continue
        try:
            pattern = re.compile(rule["pattern"], re.MULTILINE)
        except re.error as error:
            raise DatasetReferenceError(f"invalid expectation pattern {rule['id']!r}: {error}") from error
        for page in pages:
            body = sections.get(page)
            hit = pattern.search(body) if body is not None else None
            if hit and detects_fallback:
                fallback_pages.add(page)
            if not score_safety:
                continue
            criterion_id = f"safety:{rule['id']}:p{page}"
            card.criteria_ids.append(criterion_id)
            passed = body is not None and hit is None
            card.safety_checks.append(CheckResult(
                criterion_id, page, passed,
                "selected slide missing" if body is None else f"found {hit.group(0)!r}" if hit else "",
            ))
            if hit:
                card.violations.setdefault(page, []).append(rule["id"])
    for row in selected_rows:
        if row["kind"] == "table":
            # The annotation describes a shape, while this evaluator only has
            # text. Preserve it as explicitly not evaluated above.
            continue
        if row["kind"] not in {"text", "image", "chemical-structure", "table-header", "table-row", "formula"}:
            card.not_evaluated.append({"id": row["id"], "reason": f"unsupported criterion kind {row['kind']!r}"})
            continue
        page = int(row["page"])
        fallback = page in fallback_pages
        result = score_object(row, normalized.get(page, ""), fallback=fallback)
        if not result.passed and row["kind"] in {"table-header", "table-row"} and page in streamed:
            result = score_object(row, streamed[page], fallback=fallback, row_gap=0)
            if result.passed:
                result.detail = STREAM_ORDER_DETAIL
        card.objects.append(result)
        card.criteria_ids.append(row["id"])

    if structure_task:
        structure = expectations.get("structure", {})
        if not selection.pages and not selection.object_ids:
            if "slide_count" in structure:
                expected = int(structure["slide_count"])
                card.structure_checks.append(CheckResult(
                    "structure:slide-count", None, len(sections) == expected,
                    "" if len(sections) == expected else f"found {len(sections)} slides, expected {expected}",
                ))
            deck_title = structure.get("deck_title") or {}
            if deck_title.get("text"):
                found = normalize(deck_title["text"]) in normalize(text)
                card.structure_checks.append(CheckResult(
                    "structure:deck-title", None, found, "" if found else "deck title not found",
                ))
        else:
            if "slide_count" in structure:
                card.not_evaluated.append({"id": "structure:slide-count", "reason": "global slide count is outside the selected scope"})
            if structure.get("deck_title"):
                card.not_evaluated.append({"id": "structure:deck-title", "reason": "document-wide title has no selected page/object scope"})
        for spec in structure.get("slide_titles", []):
            page = int(spec["page"])
            if selected_pages and page not in selected_pages:
                card.not_evaluated.append({"id": f"structure:slide-title:p{page}", "reason": "outside selected page scope"})
                continue
            section = sections.get(page, "")
            found = normalize(spec["title"]) in normalize(section)
            card.structure_checks.append(CheckResult(
                f"structure:slide-title:p{page}", page, found,
                "" if found else f"expected slide title not found: {spec['title']}",
            ))
        slide_heading = structure.get("slide_heading")
        if slide_heading:
            for page in criteria_scope_pages:
                section = sections.get(page, "")
                found = re.search(slide_heading["pattern"], section, re.MULTILINE) is not None
                card.structure_checks.append(CheckResult(
                    f"structure:slide-heading:p{page}", page, found,
                    "" if found else "slide heading missing",
                ))
    else:
        card.not_evaluated.append({"id": "presentation_structure", "reason": "task not selected"})
    card.criteria_ids.extend(check.id for check in card.structure_checks)
    # Include selected source criteria even when this text-only evaluator
    # classifies them as unsupported. The ID list must still describe scope.
    card.criteria_ids.extend(
        row["id"] for row in selected_rows
        if not selection.object_ids or row["id"] in selection.object_ids
    )
    if dataset_metadata:
        for task, info in dataset_metadata.get("tasks", {}).items():
            if info.get("availability") == "unannotated":
                card.not_evaluated.append({"id": task, "reason": "task is marked unannotated in the reference manifest"})
    if "presentation_degraded_run_behavior" in (dataset_metadata or {}).get("tasks", {}):
        card.not_evaluated.append({
            "id": "presentation_degraded_run_behavior",
            "reason": "orchestration behavior is not evaluated by this text scorecard",
        })
    card.criteria_ids = sorted(set(card.criteria_ids))
    return card


def pdf_layout_text(path: Path, mode: Literal["-layout", "-raw"] = "-layout") -> str:
    """Text of a PDF/UA through ``pdftotext``, by default with its layout kept.

    ``-layout`` keeps each table row on its line. ``-raw`` gives the
    content-stream order instead, for ``score_text``'s ``stream_text``.
    """
    if shutil.which("pdftotext") is None:
        raise RuntimeError("pdftotext (poppler-utils) is required to score a PDF/UA output")
    return subprocess.run(
        ["pdftotext", mode, "-enc", "UTF-8", str(path), "-"],
        check=True, capture_output=True, text=True,
    ).stdout


def read_output(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return pdf_layout_text(path)
    if path.suffix.lower() != ".txt":
        raise DatasetReferenceError(
            f"unsupported output artifact format {path.suffix or '<no extension>'}; expected .txt or .pdf"
        )
    return path.read_text(encoding="utf-8")


def _file_sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _pdftotext_version() -> str | None:
    if shutil.which("pdftotext") is None:
        return None
    result = subprocess.run(["pdftotext", "-v"], capture_output=True, text=True, check=False)
    version = (result.stderr or result.stdout).splitlines()
    return version[0] if version else None


def score_output(rows: list[dict[str, str]], expectations: dict[str, Any], path: Path) -> Scorecard:
    """Score a PDF/UA (with its stream order for table rows) or a TXT output."""
    stream = pdf_layout_text(path, "-raw") if path.suffix.lower() == ".pdf" else None
    return score_text(rows, expectations, read_output(path), path.name, stream_text=stream)


def _comparison_mismatches(base: Scorecard, candidate: Scorecard, cross_format_method: str | None) -> list[str]:
    mismatches = []
    if not base.dataset.get("references_digest") or not candidate.dataset.get("references_digest"):
        mismatches.append("missing reference digest")
    canonical_selection = lambda value: {
        **value,
        "tasks": sorted(value.get("tasks", [])),
        "pages": sorted(value.get("pages", [])),
        "object_ids": sorted(value.get("object_ids", [])),
    }
    if canonical_selection(base.selection) != canonical_selection(candidate.selection):
        mismatches.append("selection")
    if sorted(base.criteria_ids) != sorted(candidate.criteria_ids):
        mismatches.append("criterion IDs")
    for field in ("repository", "revision", "references_digest", "references_schema_version", "input_id"):
        if base.dataset.get(field) != candidate.dataset.get(field):
            mismatches.append(f"Dataset {field}")
    if base.dataset.get("tasks") != candidate.dataset.get("tasks"):
        mismatches.append("reference coverage")
    if base.protocol_version != candidate.protocol_version:
        mismatches.append("protocol")
    if base.output_mode != candidate.output_mode and not cross_format_method:
        mismatches.append("output format (pass an explicit cross-format extraction method to compare)")
    if cross_format_method and base.output_mode == candidate.output_mode:
        mismatches.append("cross-format method was supplied for matching output formats")
    return mismatches


def compare(
    base: Scorecard,
    candidate: Scorecard,
    *,
    cross_format_method: str | None = None,
) -> str:
    """A per-slide table of what changed, regressions first."""
    mismatches = _comparison_mismatches(base, candidate, cross_format_method)
    base_checks = {
        check.id: check for check in (*base.objects, *base.safety_checks, *base.structure_checks)
    }
    candidate_checks = {
        check.id: check
        for check in (*candidate.objects, *candidate.safety_checks, *candidate.structure_checks)
    }
    if base_checks.keys() != candidate_checks.keys():
        mismatches.append("evaluated criterion IDs")
    if mismatches:
        return (
            "COMPARABILITY: INCOMPARABLE\n"
            f"Mismatched evaluation identity: {', '.join(mismatches)}\n"
            "No regression verdict was produced.\n"
        )
    if not base_checks:
        return (
            "COMPARABILITY: INSUFFICIENT EVIDENCE\n"
            "Neither output has an evaluated criterion in the selected scope.\n"
            "No regression verdict was produced.\n"
        )
    a, b = base.slide_scores(), candidate.slide_scores()
    worse_checks = sorted(
        criterion_id for criterion_id, before in base_checks.items()
        if before.passed and not candidate_checks[criterion_id].passed
    )
    improved_checks = sorted(
        criterion_id for criterion_id, before in base_checks.items()
        if not before.passed and candidate_checks[criterion_id].passed
    )
    check_regression_pages = {
        candidate_checks[criterion_id].page
        for criterion_id in worse_checks
        if candidate_checks[criterion_id].page is not None
    }
    lines = [
        f"Base: {base.output}", f"Candidate: {candidate.output}", "",
        f"Reference: {base.dataset.get('revision') or 'legacy/unversioned'} ({base.dataset.get('references_digest') or 'no digest'})",
        f"Scope/protocol/output: {base.selection} / {base.protocol_version} / {base.output_mode}",
        *( [f"Cross-format extraction: {cross_format_method}"] if cross_format_method else [] ),
        f"Objects passed: {base.summary()['objects_passed']} → {candidate.summary()['objects_passed']}",
        f"Rows found only in stream order: {base.summary()['stream_order']} → {candidate.summary()['stream_order']}", "",
        "| Slide | Base | Candidate | Δ | Stream order | New violations |", "|---|---|---|---|---|---|",
    ]
    rows = []
    for page in a:
        delta = b[page]["passed"] - a[page]["passed"]
        new = sorted(set(b[page]["violations"]) - set(a[page]["violations"]))
        if delta or new or page in check_regression_pages or a[page]["stream_order"] != b[page]["stream_order"]:
            rows.append((delta, page, new))
    for delta, page, new in sorted(rows):
        mark = "↓" if delta < 0 or new or page in check_regression_pages else "↑" if delta else "·"
        stream = (
            f"{a[page]['stream_order']} → {b[page]['stream_order']}"
            if a[page]["stream_order"] != b[page]["stream_order"] else ""
        )
        lines.append(
            f"| {page} {mark} | {a[page]['passed']}/{a[page]['total']} | "
            f"{b[page]['passed']}/{b[page]['total']} | {delta:+d} | {stream} | {', '.join(new)} |"
        )
    worse = {page for delta, page, new in rows if delta < 0 or new} | check_regression_pages
    global_worse = sorted(
        criterion_id for criterion_id in worse_checks
        if candidate_checks[criterion_id].page is None
    )
    lines += [
        "",
        f"Checks worse: {', '.join(worse_checks) or 'none'}",
        f"Checks improved: {', '.join(improved_checks) or 'none'}",
        f"Document-level checks worse: {', '.join(global_worse) or 'none'}",
        f"Slides worse: {', '.join(map(str, sorted(worse))) or 'none'}",
    ]
    return "\n".join(lines) + "\n"


# ── Commands ────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.bench.slide_case", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dataset", type=Path, help="acessilia-dataset clone (default: $ACESSILIA_TEST_DATASET_DIR or tests/dataset)")
    parser.add_argument("--require-pinned-dataset", action="store_true", help="require the Dataset revision/digest in scripts/bench/dataset.lock.json")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("score", help="score one output")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--pdf-ua", type=Path, help="PDF/UA output (needs pdftotext)")
    group.add_argument("--txt", type=Path, help="plain-text output")
    p.add_argument("--out", type=Path, help="also write scorecard.json and scorecard.md here")
    p.add_argument("--task", action="append", choices=SLIDE_TASKS, help="evaluate only this task (repeatable)")
    p.add_argument("--page", action="append", type=int, help="evaluate only this slide (repeatable)")
    p.add_argument("--object-id", action="append", help="evaluate only this reference object (repeatable)")
    p = sub.add_parser("compare", help="slides that got worse from base to candidate")
    p.add_argument("base", type=Path, help="PDF/UA or TXT output")
    p.add_argument("candidate", type=Path, help="PDF/UA or TXT output")
    p.add_argument("--task", action="append", choices=SLIDE_TASKS, help="evaluate only this task (repeatable)")
    p.add_argument("--page", action="append", type=int, help="evaluate only this slide (repeatable)")
    p.add_argument("--object-id", action="append", help="evaluate only this reference object (repeatable)")
    p.add_argument("--cross-format-method", choices=("pdftotext-layout-raw-v1",), help="declare the text extraction protocol when comparing TXT and PDF/UA")
    args = parser.parse_args(argv)

    root = args.dataset or dataset_dir()
    selection = EvaluationSelection(
        tasks=tuple(args.task or ()),
        pages=tuple(args.page or ()),
        object_ids=tuple(args.object_id or ()),
    )
    try:
        rows, expectations, dataset_metadata = resolve_case(root, require_pinned=args.require_pinned_dataset)
        if args.command == "compare":
            cards = [
                score_text(
                    rows, expectations, read_output(path), path.name,
                    stream_text=pdf_layout_text(path, "-raw") if path.suffix.lower() == ".pdf" else None,
                    selection=selection,
                    dataset_metadata=dataset_metadata,
                )
                for path in (args.base, args.candidate)
            ]
            report = compare(*cards, cross_format_method=args.cross_format_method)
            print(report, end="")
            return 2 if report.startswith("COMPARABILITY:") else 0
        path = args.pdf_ua or args.txt
        card = score_text(
            rows, expectations, read_output(path), path.name,
            stream_text=pdf_layout_text(path, "-raw") if path.suffix.lower() == ".pdf" else None,
            selection=selection,
            dataset_metadata=dataset_metadata,
        )
        print(card.to_markdown(), end="")
        if args.out is not None:
            args.out.mkdir(parents=True, exist_ok=True)
            existing_artifacts = {item.name for item in args.out.iterdir() if item.is_file()}
            (args.out / "scorecard.json").write_text(
                json.dumps(card.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            (args.out / "scorecard.md").write_text(card.to_markdown(), encoding="utf-8")
            (args.out / "run-metadata.json").write_text(json.dumps({
                "status": "completed",
                "protocol_version": PROTOCOL_VERSION,
                "core_revision": git_revision(Path(__file__).resolve().parents[2]),
                "dataset": dataset_metadata,
                "selection": card.selection,
                "criteria_ids": card.criteria_ids,
                "configuration": {
                    "dataset_root": str(root.resolve()),
                    "require_pinned_dataset": args.require_pinned_dataset,
                    "output_path": str(path.resolve()),
                    "output_sha256": _file_sha256(path),
                    "output_mode": card.output_mode,
                },
                "runtime": {
                    "python": platform.python_version(),
                    "pdftotext": _pdftotext_version() if path.suffix.lower() == ".pdf" else None,
                },
                "artifacts": sorted(existing_artifacts | {
                    "scorecard.json", "scorecard.md", "run-metadata.json",
                }),
                "artifact_storage": {
                    "directory": str(args.out.resolve()),
                    "retention": "operator-managed; artifacts remain until explicitly removed",
                    "observability_export": False,
                },
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 0
    except Exception as error:
        message = str(error).casefold()
        if isinstance(error, FileNotFoundError):
            status = "missing_artifact"
        elif isinstance(error, DatasetReferenceError):
            status = (
                "invalid_artifact_format" if "output artifact format" in message
                else "invalid_reference_format_or_version" if "invalid" in message or "schema" in message
                else "reference_unavailable"
            )
        elif isinstance(error, (subprocess.CalledProcessError, json.JSONDecodeError)):
            status = "invalid_artifact_format"
        else:
            status = "execution_failure"
        print(f"{status}: {type(error).__name__}: {error}", file=sys.stderr)
        if getattr(args, "out", None) is not None:
            args.out.mkdir(parents=True, exist_ok=True)
            (args.out / "scorecard.json").unlink(missing_ok=True)
            (args.out / "scorecard.md").unlink(missing_ok=True)
            (args.out / "run-metadata.json").write_text(json.dumps({
                "status": status,
                "stage": "reference_resolution_or_artifact_read",
                "error_type": type(error).__name__,
                "error": str(error),
                "dataset_root": str(root),
                "selection": selection.to_dict(),
                "protocol_version": PROTOCOL_VERSION,
                "artifact_storage": {
                    "directory": str(args.out.resolve()),
                    "retention": "operator-managed; artifacts remain until explicitly removed",
                    "observability_export": False,
                },
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 1


if __name__ == "__main__":
    sys.exit(main())
