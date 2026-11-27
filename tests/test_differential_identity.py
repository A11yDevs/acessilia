"""An intended difference belongs to an object as well as a position (#895)."""

from copy import deepcopy

import pytest

from tests.differential.compare import differences, explain


def test_a_change_in_another_object_moved_to_the_declared_position_is_not_explained():
    reference = {"blocks": [{"id": "a", "text": "old"}, {"id": "b", "text": "old"}]}
    declared = [{"kind": "changed", "path": "/blocks/0/text", "id": "a", "expected": "new", "reason": "r"}]
    intended = {"blocks": [{"id": "a", "text": "new"}, {"id": "b", "text": "old"}]}
    assert explain(reference, intended, declared) == ([], [])
    moved = {"blocks": [{"id": "b", "text": "new"}, {"id": "a", "text": "old"}]}
    found = differences(reference, moved)
    assert found == [
        {"kind": "changed", "path": "/blocks"},
        {"kind": "changed", "path": "/blocks/0/text", "reference_path": "/blocks/1/text"},
    ]
    assert explain(reference, moved, declared) == (found, declared)
    # Older declarations keep their positional meaning; the order change still fails.
    positional = [{key: value for key, value in declared[0].items() if key != "id"}]
    assert explain(reference, moved, positional) == ([found[0]], [])


@pytest.mark.parametrize("kind", ["added", "changed", "removed"])
def test_id_binding_keeps_value_checks_and_uses_the_correct_side(kind):
    target = {"id": "target", "text": "old"}
    keep = {"id": "keep"}
    if kind == "added":
        reference, current = {"blocks": [keep]}, {"blocks": [target, keep]}
        path, value_key, expected = "/blocks/0", "expected", target
    elif kind == "removed":
        reference, current = {"blocks": [target, keep]}, {"blocks": [keep]}
        path, value_key, expected = "/blocks/0", "was", target
    else:
        reference = {"blocks": [target, keep]}
        current = {"blocks": [{**target, "text": "new"}, keep]}
        path, value_key, expected = "/blocks/0/text", "expected", "new"
    declaration = {"kind": kind, "path": path, "id": "target", value_key: expected, "reason": "r"}
    assert explain(reference, current, [declaration]) == ([], [])
    for invalid in ({**declaration, "id": "keep"}, {**declaration, value_key: "wrong value"}):
        assert explain(reference, current, [invalid]) == (differences(reference, current), [invalid])
    if kind == "removed":
        without_value = {key: value for key, value in declaration.items() if key != "was"}
        assert explain(reference, current, [without_value]) == ([], [])


@pytest.mark.parametrize("kind", ["added", "changed", "removed"])
def test_a_field_of_a_moved_object_uses_current_path_except_for_removals(kind):
    target = {"id": "target", "metadata": {"text": "old"} if kind != "added" else {}}
    reference = {"blocks": [target]}
    current_target = {"id": "target", "metadata": {"text": "new"} if kind != "removed" else {}}
    inserted = {"id": "inserted"}
    current = {"blocks": [inserted, current_target]}
    addition = {"kind": "added", "path": "/blocks/0", "id": "inserted", "expected": inserted, "reason": "r"}
    path = "/blocks/0/metadata/text" if kind == "removed" else "/blocks/*/metadata/text"
    value = {"was": "old"} if kind == "removed" else {"expected": "new"}
    declared = [addition, {"kind": kind, "path": path, "id": "target", **value, "reason": "r"}]
    assert explain(reference, current, declared) == ([], [])
    if kind != "removed":
        old_position = {**declared[1], "path": "/blocks/0/metadata/text"}
        unexplained, unused = explain(reference, current, [addition, old_position])
        assert unexplained == [item for item in differences(reference, current) if item["kind"] != "added" or item["path"] != "/blocks/0"]
        assert unused == [old_position]


@pytest.mark.parametrize("binding", ["block", "section", "metadata-id"])
def test_the_nearest_identified_object_wins_with_escaped_keys(binding):
    reference = {"sections": [{"id": "section", "blocks": [
        {"id": "block", "metadata": {"id": "metadata-id", "a/b": {"~note": "old"}}},
    ]}]}
    current = deepcopy(reference)
    current["sections"][0]["blocks"][0]["metadata"]["a/b"]["~note"] = "new"
    declared = [{"kind": "changed", "path": "/sections/0/blocks/0/metadata/a~1b/~0note",
                 "id": binding, "expected": "new", "reason": "r"}]
    assert explain(reference, current, declared) == (
        ([], []) if binding == "block" else (differences(reference, current), declared)
    )


@pytest.mark.parametrize("ids", [["a", "a"], [None, "b"], ["", "b"], [1, 2], [["a"], "b"]])
def test_a_positional_list_cannot_supply_an_ambiguous_or_invalid_identity(ids):
    reference = {"blocks": [{"id": value, "text": "old"} for value in ids]}
    current = deepcopy(reference)
    current["blocks"][0]["text"] = "new"
    declared = [{"kind": "changed", "path": "/blocks/0/text", "id": "a", "expected": "new", "reason": "r"}]
    assert explain(reference, current, declared) == (differences(reference, current), declared)


def test_a_list_order_change_cannot_be_bound_to_one_of_its_members():
    reference = {"blocks": [{"id": "a"}, {"id": "b"}]}
    current = {"blocks": [{"id": "b"}, {"id": "a"}]}
    declared = [{"kind": "changed", "path": "/blocks", "id": "a", "expected": current["blocks"], "reason": "r"}]
    assert differences(reference, current) == [{"kind": "changed", "path": "/blocks"}]
    assert explain(reference, current, declared) == (differences(reference, current), declared)


@pytest.mark.parametrize("binding", [None, "", 1, False, [], {}])
def test_an_invalid_id_binding_is_rejected_even_when_there_are_no_differences(binding):
    with pytest.raises(ValueError, match="id must be a non-empty string"):
        explain({}, {}, [{"kind": "added", "path": "/blocks", "id": binding, "expected": [], "reason": "r"}])


def test_id_binding_does_not_hide_a_missing_expected_value():
    with pytest.raises(ValueError, match="expected value"):
        explain({"blocks": [{"id": "a", "text": "old"}]}, {"blocks": [{"id": "a", "text": "new"}]},
                [{"kind": "changed", "path": "/blocks/0/text", "id": "another", "reason": "r"}])
