"""The whole pipeline against the core before each #640 migration (#849).

Each case (``tests/differential/cases``) runs through the backend's path,
``execute`` then ``build_canonical_document``, with a deterministic Toolbox
(``tests/differential/fake_toolbox.py``) and a hermetic environment. Its
normalized canonical document is compared with the one each reference
recorded on the core before a migration (``tests/differential/references``,
``scripts/record_differential_references.py``):

- ``core-0.3.11``: before M2 (tables);
- ``core-0.3.13``: before M1 (picture descriptions);
- ``core-0.3.14``: before M3 (formula LaTeX);
- ``core-0.3.18``: before M4a (formula regions);
- ``core-0.3.19``: before M4b (prose inline math).

A step-level differential test shows a step is equivalent once planned; this
one shows the pipeline is, so a regression between steps (the formula LaTeX
gap of M1, #846) fails here. A difference a later release made on purpose is
declared in the reference's ``intended.json``, with the value it allows and
the release that made it; any other one fails, and so does a declared one
that no longer happens. The scope is the cases' (see the README): eight
synthetic documents, one or several pages, one or two providers, and a
Toolbox that answers, or fails where a case says so.
"""

from __future__ import annotations

import json

import pytest

from tests.differential.compare import explain
from tests.differential.runner import CASES, REFERENCES, identity, run_case

CASE_NAMES = sorted(path.parent.name for path in CASES.glob("*/case.json"))
LABELS = sorted(path.name for path in REFERENCES.iterdir() if path.is_dir() and not path.name.startswith("."))


@pytest.fixture(scope="module")
def runs() -> dict[str, dict]:
    """Each case run once on this tree, shared by every reference."""
    return {name: run_case(CASES / name / "case.json") for name in CASE_NAMES}


def _reference(label: str, case: str) -> dict:
    return json.loads((REFERENCES / label / f"{case}.json").read_text(encoding="utf-8"))


def _declared(label: str) -> dict[str, list[dict]]:
    """``intended.json``: per case name (``*``: any case), the differences a
    later release made on purpose (``compare.explain``)."""
    path = REFERENCES / label / "intended.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


@pytest.mark.parametrize("label", LABELS)
def test_each_reference_was_recorded_with_this_harness_and_every_case(label) -> None:
    """A reference depends on the harness and the cases too: one recorded
    with others must be recorded again, not compared."""
    source = json.loads((REFERENCES / label / "SOURCE.json").read_text(encoding="utf-8"))
    recorded = sorted(path.stem for path in (REFERENCES / label).glob("*.json")
                      if path.stem not in {"SOURCE", "intended"})

    assert {key: source.get(key) for key in identity()} == identity(), (
        f"{label} was recorded with another harness, cases or source PDF: "
        "record it again (scripts/record_differential_references.py)"
    )
    assert recorded == CASE_NAMES, f"{label}: record it again for the cases {CASE_NAMES}"


@pytest.mark.parametrize("case", CASE_NAMES)
def test_the_fake_toolbox_answers_every_call(runs, case) -> None:
    assert runs[case]["unhandled"] == []


@pytest.mark.parametrize("case", CASE_NAMES)
def test_every_failure_a_case_declares_happens(runs, case) -> None:
    """A degraded case keeps degrading: a failure the core no longer meets
    (it stopped calling the capability, or the element) would leave the
    case testing nothing."""
    failures = json.loads((CASES / case / "case.json").read_text(encoding="utf-8")).get("failures") or {}
    declared = {*failures.get("capabilities", []), *(f"vlm:{element}" for element in failures.get("vision", []))}
    assert set(runs[case]["refused"]) == declared


@pytest.mark.parametrize("case", CASE_NAMES)
def test_a_dual_provider_case_extracts_twice(runs, case) -> None:
    """#888 review: a case with a secondary document must keep testing two
    providers; one that ran single would still pass the comparison."""
    dual = "secondary_document" in json.loads((CASES / case / "case.json").read_text(encoding="utf-8"))
    assert runs[case]["calls"].get("document.structure.extract") == (2 if dual else 1)


def test_a_degraded_result_is_not_cached(runs) -> None:
    """#882: a result with work left open is not cached as a success."""
    assert runs["degraded"]["cacheable"] is False
    assert all(runs[case]["cacheable"] for case in CASE_NAMES if case != "degraded")


def _blocks(canonical: dict) -> list[dict]:
    return [block for section in canonical["sections"] for block in section.get("blocks", [])]


def test_the_table_adopted_from_the_secondary_is_marked_again(runs) -> None:
    """#888 review: M4b's evidence, not only its extra revision. The
    secondary's table replaces the primary's, and its math cell, flagged
    stale, is marked from the text layer's fonts."""
    [table] = [block for block in _blocks(runs["dual-provider"]["canonical"]) if block["type"] == "table"]
    rows = [[cell["text"] for cell in row["cells"]] for row in table["metadata"]["table_ast"]["body"]]

    assert table["metadata"]["table_source"] == "mineru"
    assert rows[-3:] == [["Mass", "3 kg"], ["Speed", "4 m/s"], ["Start", "$s_0\\in\\mathbb{R}$"]]


def test_the_primary_only_paragraph_of_a_routed_page_is_rescued(runs) -> None:
    """#887: page 3 is routed to the secondary, which lacks the sentence only
    the primary kept. ``rescue-omitted`` puts it back, in its place, with
    its inline math, which the canonical build converts."""
    page = [block for block in _blocks(runs["dual-provider"]["canonical"])
            if block.get("source_location", {}).get("page_number") == 3]
    texts = [block.get("text") or "" for block in page]

    assert texts.index("See the cart at $v_0$.") == 1
    rescued = page[1]
    assert [entry["latex"] for entry in rescued["metadata"]["inline_math"]] == ["v_0"]


@pytest.mark.parametrize("label", LABELS)
@pytest.mark.parametrize("case", CASE_NAMES)
def test_the_canonical_output_matches_the_core_before_each_migration(runs, case, label) -> None:
    reference = _reference(label, case)["canonical"]
    own = _declared(label).get(case, [])

    unexplained, unused = explain(reference, runs[case]["canonical"], [*_declared(label).get("*", []), *own])

    assert not unexplained, (
        f"{case} departs from {label} where no release declared it "
        f"(declare it in {label}/intended.json, or fix the regression): {unexplained}"
    )
    stale = [entry for entry in unused if entry in own]
    assert not stale, f"{label}/intended.json declares differences {case} no longer has: {stale}"


@pytest.mark.parametrize("label", LABELS)
def test_a_difference_declared_for_every_case_still_happens(runs, label) -> None:
    """An entry under ``*`` must still explain some case; one that explains
    none describes a difference that is gone."""
    common = _declared(label).get("*", [])
    used = []
    for case in CASE_NAMES:
        _, unused = explain(_reference(label, case)["canonical"], runs[case]["canonical"], common)
        used.extend(entry for entry in common if entry not in unused)
    stale = [entry for entry in common if entry not in used]
    assert not stale, f"{label}/intended.json declares differences no case has: {stale}"

