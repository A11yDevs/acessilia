"""Persisted declaration validation and corpus bookkeeping keep entry identity."""

import json

import pytest

from tests import test_differential_canonical as corpus
from tests.differential.compare import explain


def _documents(kind, value):
    if kind == "added":
        return {}, {"field": value}
    if kind == "removed":
        return {"field": value}, {}
    return {"field": "old"}, {"field": value}


def _synthetic_corpus(monkeypatch, declarations, documents):
    monkeypatch.setattr(corpus, "CASE_NAMES", list(documents))
    monkeypatch.setattr(corpus, "_declared", lambda _label: declarations)
    monkeypatch.setattr(corpus, "_reference", lambda _label, case: {"canonical": documents[case][0]})
    return {case: {"canonical": current} for case, (_, current) in documents.items()}


_VALUE_CASES = [
    ("changed", True, 1, False), ("changed", False, 0, False),
    ("changed", True, 1, True), ("removed", True, 1, True),
    ("removed", False, 0, False), ("added", True, 1, True),
]


@pytest.mark.parametrize("kind,boolean,number,nested", _VALUE_CASES)
def test_common_and_case_specific_usage_is_tracked_by_entry_identity(monkeypatch, kind, boolean, number, nested):
    if nested:
        boolean, number = {"items": [boolean]}, {"items": [number]}
    key = "was" if kind == "removed" else "expected"
    common = {"kind": kind, "path": "/field", key: boolean, "reason": "r"}
    own = {**common, key: number}
    reference, current = _documents(kind, number)
    unexplained, unused = explain(reference, current, [common, own])
    assert unexplained == [] and len(unused) == 1 and unused[0] is common
    declarations = {"*": [common], "case": [own]}
    runs = _synthetic_corpus(monkeypatch, declarations, {"case": (reference, current)})
    corpus.test_the_canonical_output_matches_the_core_before_each_migration(runs, "case", "synthetic")
    # A genuinely unused case-specific entry must still fail.
    declarations["*"], declarations["case"] = [own], [common]
    with pytest.raises(AssertionError, match="differences case no longer has"):
        corpus.test_the_canonical_output_matches_the_core_before_each_migration(runs, "case", "synthetic")


@pytest.mark.parametrize("kind,boolean,number,nested", _VALUE_CASES)
def test_common_entries_are_individually_used_across_cases(monkeypatch, kind, boolean, number, nested):
    if nested:
        boolean, number = {"items": [boolean]}, {"items": [number]}
    key = "was" if kind == "removed" else "expected"
    common = [{"kind": kind, "path": "/field", key: value, "reason": "r"} for value in (boolean, number)]
    documents = {"boolean": _documents(kind, boolean), "number": _documents(kind, number)}
    runs = _synthetic_corpus(monkeypatch, {"*": common}, documents)
    corpus.test_a_difference_declared_for_every_case_still_happens(runs, "synthetic")
    for case in documents:
        monkeypatch.setattr(corpus, "CASE_NAMES", [case])
        with pytest.raises(AssertionError, match="differences no case has"):
            corpus.test_a_difference_declared_for_every_case_still_happens(runs, "synthetic")


def _intended_file(monkeypatch, tmp_path, text):
    directory = tmp_path / "synthetic"
    directory.mkdir()
    path = directory / "intended.json"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(corpus, "REFERENCES", tmp_path)
    monkeypatch.setattr(corpus, "CASE_NAMES", ["case", "other"])
    return path


@pytest.mark.parametrize("value", [None, [], 1, "text"])
def test_intended_file_requires_an_object_root(monkeypatch, tmp_path, value):
    path = _intended_file(monkeypatch, tmp_path, json.dumps(value))
    with pytest.raises(ValueError, match="object") as error:
        corpus._declared("synthetic")
    assert str(path) in str(error.value)


@pytest.mark.parametrize("value", [None, {}, 1, "entries"])
def test_intended_groups_must_be_lists(monkeypatch, tmp_path, value):
    path = _intended_file(monkeypatch, tmp_path, json.dumps({"*": value}))
    with pytest.raises(ValueError, match="list") as error:
        corpus._declared("synthetic")
    assert str(path) in str(error.value) and "'*'" in str(error.value)


def test_intended_groups_cannot_name_an_unknown_case(monkeypatch, tmp_path):
    path = _intended_file(monkeypatch, tmp_path, '{"unknown-case": []}')
    with pytest.raises(ValueError, match="unknown case") as error:
        corpus._declared("synthetic")
    assert str(path) in str(error.value) and "unknown-case" in str(error.value)


@pytest.mark.parametrize("entry,diagnostic", [
    (None, "object"), ({"kind": "removed", "path": "/field"}, "reason"),
    ({"kind": "removed", "path": "/field", "reason": "  "}, "reason"),
    ({"kind": "removed", "path": "/field", "reason": 3}, "reason"),
    ({"kind": "removed", "path": "/field", "expected": 999, "reason": "r"}, "expected"),
    ({"kind": "changed", "path": "/field", "was": 0, "expected": 1, "reason": "r"}, "was"),
    ({"kind": "added", "path": "/field", "expected": 1, "extra": True, "reason": "r"}, "extra"),
])
def test_all_stored_entries_are_validated_with_file_group_and_index(monkeypatch, tmp_path, entry, diagnostic):
    valid = {"kind": "removed", "path": "/valid", "reason": "r"}
    path = _intended_file(monkeypatch, tmp_path, json.dumps({"other": [valid, entry]}))
    with pytest.raises(ValueError, match=diagnostic) as error:
        corpus._declared("synthetic")
    message = str(error.value)
    assert str(path) in message and "'other'" in message and "entry 1" in message


def test_malformed_json_reports_the_file(monkeypatch, tmp_path):
    path = _intended_file(monkeypatch, tmp_path, '{"*":')
    with pytest.raises(ValueError) as error:
        corpus._declared("synthetic")
    assert str(path) in str(error.value)


def test_stored_declarations_keep_valid_roots_patterns_and_optional_was(monkeypatch, tmp_path):
    declarations = {"*": [{"kind": "changed", "path": "", "expected": False, "reason": "r"}],
                    "case": [{"kind": "removed", "path": "/~*", "reason": "r"}], "other": []}
    _intended_file(monkeypatch, tmp_path, json.dumps(declarations))
    assert corpus._declared("synthetic") == declarations


def test_a_missing_intended_file_still_means_no_declarations(monkeypatch, tmp_path):
    monkeypatch.setattr(corpus, "REFERENCES", tmp_path)
    assert corpus._declared("synthetic") == {}
