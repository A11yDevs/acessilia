"""JSON values keep boolean identity without splitting the number category (#919)."""

import pytest

from tests.differential.compare import differences, explain


@pytest.mark.parametrize("before,after", [(True, 1), (False, 0), (True, 1.0), (False, 0.0)])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("container", ["scalar", "object", "list"])
def test_booleans_and_numbers_are_different_in_each_direction(before, after, reverse, container):
    if reverse:
        before, after = after, before
    path = ""
    if container == "object":
        before, after, path = {"value": before}, {"value": after}, "/value"
    elif container == "list":
        before, after, path = [before], [after], "/0"
    assert differences(before, after) == [{"kind": "changed", "path": path}]


@pytest.mark.parametrize("number,boolean", [(1, True), (0, False)])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("kind", ["added", "changed", "removed"])
@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("bind_id", [False, True])
def test_declaration_values_distinguish_booleans_from_numbers(number, boolean, reverse, kind, nested, bind_id):
    actual, wrong = (boolean, number) if reverse else (number, boolean)
    if nested:
        actual, wrong = {"items": [{"value": actual}]}, {"items": [{"value": wrong}]}
    target = {"id": "a", "value": actual}
    reference, current = {"blocks": [{"id": "a"}]}, {"blocks": [target]}
    if kind == "changed":
        reference["blocks"][0]["value"] = "old"
    elif kind == "removed":
        reference, current = current, reference
    value_key = "was" if kind == "removed" else "expected"
    declaration = {"kind": kind, "path": "/blocks/0/value", value_key: wrong, "reason": "r"}
    if bind_id:
        declaration["id"] = "a"
    found = [{"kind": kind, "path": "/blocks/0/value"}]
    assert differences(reference, current) == found
    assert explain(reference, current, [declaration]) == (found, [declaration])
    correct = {**declaration, value_key: actual}
    assert explain(reference, current, [correct]) == ([], [])


@pytest.mark.parametrize("before,after", [(1, 1.0), (0, -0.0), (2**60, float(2**60))])
def test_numeric_representations_keep_exact_value_equality(before, after):
    reference = {"items": [{"id": "a", "value": before}]}
    current = {"items": [{"id": "a", "value": after}]}
    assert differences(reference, current) == []
    unused = [{"kind": "changed", "path": "/items/0/value", "expected": after, "reason": "r"}]
    assert explain(reference, current, unused) == ([], unused)
    for kind, value_key in (("added", "expected"), ("removed", "was")):
        old, new = ({}, current) if kind == "added" else (current, {})
        declared = [{"kind": kind, "path": "/items", value_key: reference["items"], "reason": "r"}]
        assert explain(old, new, declared) == ([], [])
    changed = [{"kind": "changed", "path": "/items", "expected": reference["items"], "reason": "r"}]
    assert explain({"items": "old"}, current, changed) == ([], [])


@pytest.mark.parametrize("before,after", [(1, 1.0000000000000002), (2**53 + 1, float(2**53)), (0, None), (1, "1")])
def test_numeric_equality_does_not_coerce_types_or_add_a_tolerance(before, after):
    assert differences(before, after) == [{"kind": "changed", "path": ""}]
    declared = [{"kind": "changed", "path": "", "expected": before, "reason": "r"}]
    assert explain("old", after, declared) == ([{"kind": "changed", "path": ""}], declared)


def test_moved_identified_members_keep_order_identity_and_historical_paths():
    reference = [{"id": "a", "value": True}, {"id": "b"}]
    current = [{"id": "b"}, {"id": "a", "value": 1}]
    found = [
        {"kind": "changed", "path": ""},
        {"kind": "changed", "path": "/1/value", "reference_path": "/0/value"},
    ]
    assert differences(reference, current) == found
    wrong = [{"kind": "changed", "path": "/*/value", "id": "a", "expected": True, "reason": "r"}]
    assert explain(reference, current, wrong) == (found, wrong)
    correct = [{**wrong[0], "expected": 1}]
    assert explain(reference, current, correct) == ([found[0]], [])


def test_whole_object_values_keep_key_order_irrelevant_and_array_order_significant():
    current = {"field": {"a": 1, "b": [True, False]}}
    reordered_keys = {"b": [True, False], "a": 1.0}
    declared = [{"kind": "added", "path": "/field", "expected": reordered_keys, "reason": "r"}]
    assert explain({}, current, declared) == ([], [])
    reordered_items = [{**declared[0], "expected": {"a": 1, "b": [False, True]}}]
    assert explain({}, current, reordered_items) == ([{"kind": "added", "path": "/field"}], reordered_items)


@pytest.mark.parametrize("expected", [
    {"a": 1}, {"a": 1, "b": [True]}, {"a": 1, "b": [True, False, True]},
    {"a": 1, "b": [True, False], "extra": None},
])
def test_whole_value_comparison_keeps_object_keys_and_array_lengths(expected):
    current = {"field": {"a": 1, "b": [True, False]}}
    declared = [{"kind": "added", "path": "/field", "expected": expected, "reason": "r"}]
    assert explain({}, current, declared) == ([{"kind": "added", "path": "/field"}], declared)
