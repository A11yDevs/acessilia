"""Scorecard of a slide-deck case (acessilia-dataset ``presentation-reference``).

    python -m scripts.bench.slide_case score   --pdf-ua out.pdf_ua.pdf  [--out var/bench/slides/<run>]
    python -m scripts.bench.slide_case score   --txt out.txt
    python -m scripts.bench.slide_case compare base.pdf_ua.pdf candidate.pdf_ua.pdf

The ground truth is ``input/presentation-reference/{ground_truth.csv,
expectations.json}`` of the dataset clone at ``$ACESSILIA_TEST_DATASET_DIR``
(default ``tests/dataset``); it describes ``006.pdf``, a 42-slide chemistry
deck.

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
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scripts.bench.math_case import dataset_dir

CASE_DIR = Path("input") / "presentation-reference"

#: A slide heading as the exporters write it, in pt-BR or English.
SLIDE_HEADING = re.compile(r"^\s*(?:\d+(?:\.\d+)*\s+)?Slide (\d+) (?:de|of) (\d+)\b", re.MULTILINE)

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


def load_case(root: Path) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """The object rows and the expectations of the case under ``root``."""
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
class Scorecard:
    output: str
    slides_found: int
    slide_count: int
    objects: list[ObjectResult] = field(default_factory=list)
    violations: dict[int, list[str]] = field(default_factory=dict)

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
                "violations": self.violations.get(page, []),
            }
        return out

    def summary(self) -> dict[str, Any]:
        by_kind: dict[str, list[ObjectResult]] = {}
        for o in self.objects:
            by_kind.setdefault(o.kind, []).append(o)
        return {
            "output": self.output,
            "slides_found": f"{self.slides_found}/{self.slide_count}",
            "objects_passed": f"{sum(o.passed for o in self.objects)}/{len(self.objects)}",
            "by_kind": {
                kind: f"{sum(o.passed for o in items)}/{len(items)}"
                for kind, items in sorted(by_kind.items())
            },
            "violations": sum(len(v) for v in self.violations.values()),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary(),
            "slides": self.slide_scores(),
            "objects": [o.__dict__ for o in self.objects],
        }

    def to_markdown(self) -> str:
        s = self.summary()
        lines = [
            f"Output: {s['output']}", "",
            "| Metric | Value |", "|---|---|",
            f"| Slides found | {s['slides_found']} |",
            f"| Objects passed | {s['objects_passed']} |",
            *(f"| {kind} | {value} |" for kind, value in s["by_kind"].items()),
            f"| Pattern violations | {s['violations']} |",
            "", "| Slide | Passed | Score | Violations |", "|---|---|---|---|",
        ]
        for page, slide in self.slide_scores().items():
            score = "—" if slide["score"] is None else f"{slide['score']:.0f}%"
            lines.append(
                f"| {page} | {slide['passed']}/{slide['total']} | {score} | "
                f"{', '.join(slide['violations']) or ''} |"
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
    slide_count = int(expectations.get("structure", {}).get("slide_count", 0)) or max(
        int(row["page"]) for row in rows
    )
    sections = split_slides(text)
    normalized = {page: normalize(body) for page, body in sections.items()}
    streamed = (
        {page: normalize(body) for page, body in split_slides(stream_text).items()}
        if stream_text is not None
        else {}
    )
    card = Scorecard(output=output, slides_found=len(sections), slide_count=slide_count)
    for rule in expectations.get("text", {}).get("must_not_match", []):
        pattern = re.compile(rule["pattern"], re.MULTILINE)
        for page, body in sections.items():
            if pattern.search(body):
                card.violations.setdefault(page, []).append(rule["id"])
    for row in rows:
        if row["kind"] == "table":
            continue
        page = int(row["page"])
        fallback = bool(FALLBACK_VIOLATIONS & set(card.violations.get(page, [])))
        result = score_object(row, normalized.get(page, ""), fallback=fallback)
        if not result.passed and row["kind"] in {"table-header", "table-row"} and page in streamed:
            result = score_object(row, streamed[page], fallback=fallback, row_gap=0)
        card.objects.append(result)
    return card


def pdf_layout_text(path: Path, mode: str = "-layout") -> str:
    """Text of a PDF/UA with its layout kept (``pdftotext -layout``).

    Without ``-layout`` poppler reads a table column by column, so no row
    could ever be found whole; with it each row stays on its line. ``-raw``
    gives the content-stream order instead, for ``score_text``'s
    ``stream_text``.
    """
    if shutil.which("pdftotext") is None:
        raise RuntimeError("pdftotext (poppler-utils) is required to score a PDF/UA output")
    return subprocess.run(
        ["pdftotext", mode, "-enc", "UTF-8", str(path), "-"],
        check=True, capture_output=True, text=True,
    ).stdout


def read_output(path: Path) -> str:
    return pdf_layout_text(path) if path.suffix.lower() == ".pdf" else path.read_text(encoding="utf-8")


def score_output(rows: list[dict[str, str]], expectations: dict[str, Any], path: Path) -> Scorecard:
    """Score a PDF/UA (with its stream order for table rows) or a TXT output."""
    stream = pdf_layout_text(path, "-raw") if path.suffix.lower() == ".pdf" else None
    return score_text(rows, expectations, read_output(path), path.name, stream_text=stream)


def compare(base: Scorecard, candidate: Scorecard) -> str:
    """A per-slide table of what changed, regressions first."""
    a, b = base.slide_scores(), candidate.slide_scores()
    lines = [
        f"Base: {base.output}", f"Candidate: {candidate.output}", "",
        f"Objects passed: {base.summary()['objects_passed']} → {candidate.summary()['objects_passed']}", "",
        "| Slide | Base | Candidate | Δ | New violations |", "|---|---|---|---|---|",
    ]
    rows = []
    for page in a:
        delta = b[page]["passed"] - a[page]["passed"]
        new = sorted(set(b[page]["violations"]) - set(a[page]["violations"]))
        if delta or new:
            rows.append((delta, page, new))
    for delta, page, new in sorted(rows):
        mark = "↓" if delta < 0 or new else "↑"
        lines.append(
            f"| {page} {mark} | {a[page]['passed']}/{a[page]['total']} | "
            f"{b[page]['passed']}/{b[page]['total']} | {delta:+d} | {', '.join(new)} |"
        )
    worse = [page for delta, page, new in rows if delta < 0 or new]
    lines += ["", f"Slides worse: {', '.join(map(str, sorted(worse))) or 'none'}"]
    return "\n".join(lines) + "\n"


# ── Commands ────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.bench.slide_case", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dataset", type=Path, help="acessilia-dataset clone (default: $ACESSILIA_TEST_DATASET_DIR or tests/dataset)")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("score", help="score one output")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--pdf-ua", type=Path, help="PDF/UA output (needs pdftotext)")
    group.add_argument("--txt", type=Path, help="plain-text output")
    p.add_argument("--out", type=Path, help="also write scorecard.json and scorecard.md here")
    p = sub.add_parser("compare", help="slides that got worse from base to candidate")
    p.add_argument("base", type=Path, help="PDF/UA or TXT output")
    p.add_argument("candidate", type=Path, help="PDF/UA or TXT output")
    args = parser.parse_args(argv)

    rows, expectations = load_case(args.dataset or dataset_dir())
    if args.command == "compare":
        cards = [score_output(rows, expectations, path) for path in (args.base, args.candidate)]
        print(compare(*cards), end="")
        return 0
    path = args.pdf_ua or args.txt
    card = score_output(rows, expectations, path)
    print(card.to_markdown(), end="")
    if args.out is not None:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "scorecard.json").write_text(
            json.dumps(card.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (args.out / "scorecard.md").write_text(card.to_markdown(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
