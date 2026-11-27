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

from tests.differential.compare import explain, validate_declaration
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
    if not path.is_file():
        return {}
    try:
        declared = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{path}: {error}") from None
    if not isinstance(declared, dict):
        raise ValueError(f"{path}: expected an object of declaration groups")
    for case, entries in declared.items():
        context = f"{path}: group {case!r}"
        if case != "*" and case not in CASE_NAMES:
            raise ValueError(f"{context}: unknown case")
        if not isinstance(entries, list):
            raise ValueError(f"{context}: expected a list of declarations")
        for index, entry in enumerate(entries):
            try:
                validate_declaration(entry)
                if "reason" not in entry:
                    raise ValueError("stored declarations require a non-blank reason")
            except ValueError as error:
                raise ValueError(f"{context}, entry {index}: {error}") from None
    return declared


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


def _routed_page(tmp_path, sentence: str, secondary_math: bool) -> dict:
    """``dual-provider``'s page 3 alone, routed to the secondary; the primary
    alone keeps ``sentence``. Run here, compared with no reference: the
    reproduction of #887 as it was found, and its inline-math variant."""
    from tests.differential import build_cases

    spec = build_cases.CASES["dual-provider"]
    primary = [element.model_copy(deep=True) for element in spec["elements"] if element.page_number == 3]
    secondary = [element.model_copy(deep=True) for element in spec["secondary"] if element.page_number == 3]
    if not secondary_math:
        secondary = [element for element in secondary if element.id != "v4"]
    for element in [*primary, *secondary]:
        element.page_number = 1
        element.provenance[0].page_number = 1
    primary[1] = primary[1].model_copy(update={"text": sentence})
    case = build_cases.build("routed", {
        "description": "", "environment": {"FUSION_MODE": "dual"}, "elements": primary,
        "secondary": secondary, "vision": spec["vision"], "latex": spec["latex"],
    })
    target = tmp_path / "routed" / "case.json"
    target.parent.mkdir()
    target.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
    return run_case(target)


@pytest.mark.parametrize(
    ("sentence", "secondary_math", "conversions"),
    [("See the cart.", False, 1), ("See the cart at $v_0$.", True, 2)],
    ids=["as-found", "with-inline-math"],
)
def test_a_routed_page_rescues_its_primary_only_sentence_once(tmp_path, sentence, secondary_math, conversions) -> None:
    """#887 as it was found (``secondary_structure_superset``) and with
    inline math (``both_formula->mineru``): the sentence comes back once, in
    its place, and nothing critical is left open. With inline math, the
    rescued block is variable evidence the planned conversion did not see,
    so the conversion is dropped and done again (#891 review): the formula
    is converted twice, against once when the sentence has none."""
    outcome = _routed_page(tmp_path, sentence, secondary_math)
    texts = [block.get("text") or "" for block in _blocks(outcome["canonical"])]

    assert outcome["unhandled"] == []
    assert texts.count(sentence) == 1 and texts.index(sentence) == 1
    assert outcome["canonical"]["metadata"]["pddl_unsatisfied_obligations"] == []
    assert outcome["converted"]["a = \\frac{v}{t}"] == conversions


@pytest.mark.parametrize("label", LABELS)
@pytest.mark.parametrize("case", CASE_NAMES)
def test_the_canonical_output_matches_the_core_before_each_migration(runs, case, label) -> None:
    reference = _reference(label, case)["canonical"]
    declared = _declared(label)
    own = declared.get(case, [])

    unexplained, unused = explain(reference, runs[case]["canonical"], [*declared.get("*", []), *own])

    assert not unexplained, (
        f"{case} departs from {label} where no release declared it "
        f"(declare it in {label}/intended.json, or fix the regression): {unexplained}"
    )
    own_ids = {id(entry) for entry in own}
    stale = [entry for entry in unused if id(entry) in own_ids]
    assert not stale, f"{label}/intended.json declares differences {case} no longer has: {stale}"


@pytest.mark.parametrize("label", LABELS)
def test_a_difference_declared_for_every_case_still_happens(runs, label) -> None:
    """An entry under ``*`` must still explain some case; one that explains
    none describes a difference that is gone."""
    common = _declared(label).get("*", [])
    used_indices: set[int] = set()
    for case in CASE_NAMES:
        _, unused = explain(_reference(label, case)["canonical"], runs[case]["canonical"], common)
        unused_ids = {id(entry) for entry in unused}
        used_indices.update(index for index, entry in enumerate(common) if id(entry) not in unused_ids)
    stale = [entry for index, entry in enumerate(common) if index not in used_indices]
    assert not stale, f"{label}/intended.json declares differences no case has: {stale}"

