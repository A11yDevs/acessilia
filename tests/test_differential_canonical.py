"""The whole pipeline against the core before each #640 migration (#849).

Each case (``tests/differential/cases``) runs through the backend's path,
``execute`` then ``build_canonical_document``, with a deterministic Toolbox
(``tests/differential/fake_toolbox.py``). Its normalized canonical document is
compared with the one each reference recorded on the core before a migration
(``tests/differential/references/<label>``,
``scripts/record_differential_references.py``):

- ``core-0.3.11``: before M2 (tables);
- ``core-0.3.13``: before M1 (picture descriptions);
- ``core-0.3.14``: before M3 (formula LaTeX);
- ``core-0.3.18``: before M4a (formula regions);
- ``core-0.3.19``: before M4b (prose inline math).

A step-level differential test shows a step is equivalent once planned; this
one shows the pipeline is, so a regression between steps (the formula LaTeX
gap of M1, #846) fails here. A difference a later release made on purpose is
declared in the reference's ``intended.json``, with the release that made it;
any other one fails, and so does a declared one that no longer happens.
"""

from __future__ import annotations

import json
from fnmatch import fnmatchcase

import pytest

from tests.differential.runner import CASES, REFERENCES, differences, run_case

CASE_NAMES = sorted(path.parent.name for path in CASES.glob("*/case.json"))
LABELS = sorted(path.name for path in REFERENCES.iterdir() if path.is_dir()) if REFERENCES.is_dir() else []


@pytest.fixture(scope="module")
def runs() -> dict[str, dict]:
    """Each case run once on this tree, shared by every reference."""
    return {name: run_case(CASES / name / "case.json") for name in CASE_NAMES}


def _declared(label: str) -> dict[str, list[dict[str, str]]]:
    """``intended.json``: per case name (``*``: any case), the differences a
    later release made on purpose, each ``{kind, path, reason}``; ``path`` is
    a JSON pointer, with ``*`` matching any run of characters."""
    path = REFERENCES / label / "intended.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _matches(difference: dict[str, str], declared: dict[str, str]) -> bool:
    return difference["kind"] == declared["kind"] and fnmatchcase(difference["path"], declared["path"])


def test_every_reference_covers_every_case() -> None:
    assert LABELS, "no reference recorded"
    for label in LABELS:
        recorded = sorted(path.stem for path in (REFERENCES / label).glob("*.json")
                          if path.stem not in {"SOURCE", "intended"})
        assert recorded == CASE_NAMES, f"{label}: record it again for the cases {CASE_NAMES}"


@pytest.mark.parametrize("case", CASE_NAMES)
def test_the_fake_toolbox_answers_every_call(runs, case) -> None:
    assert runs[case]["unhandled"] == []


@pytest.mark.parametrize("label", LABELS)
@pytest.mark.parametrize("case", CASE_NAMES)
def test_the_canonical_output_matches_the_core_before_each_migration(runs, case, label) -> None:
    reference = json.loads((REFERENCES / label / f"{case}.json").read_text(encoding="utf-8"))
    found = differences(reference["canonical"], runs[case]["canonical"])
    own = _declared(label).get(case, [])
    declared = [*_declared(label).get("*", []), *own]

    unexpected = [item for item in found if not any(_matches(item, entry) for entry in declared)]
    stale = [entry for entry in own if not any(_matches(item, entry) for item in found)]

    assert not unexpected, (
        f"{case} departs from {label} where no release declared it "
        f"(declare it in {label}/intended.json, or fix the regression): {unexpected}"
    )
    assert not stale, f"{label}/intended.json declares differences {case} no longer has: {stale}"


@pytest.mark.parametrize("label", LABELS)
def test_a_difference_declared_for_every_case_still_happens(runs, label) -> None:
    """An entry under ``*`` must still match some case; one that matches
    none describes a difference that is gone."""
    found = []
    for case in CASE_NAMES:
        reference = json.loads((REFERENCES / label / f"{case}.json").read_text(encoding="utf-8"))
        found.extend(differences(reference["canonical"], runs[case]["canonical"]))
    stale = [entry for entry in _declared(label).get("*", []) if not any(_matches(item, entry) for item in found)]
    assert not stale, f"{label}/intended.json declares differences no case has: {stale}"
