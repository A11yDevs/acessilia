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


@pytest.mark.parametrize("side", ["reference", "current"])
@pytest.mark.parametrize("invalid", ["duplicate", "missing", "empty", "integer", "unhashable"])
def test_a_bound_change_requires_valid_identity_on_both_sides(side, invalid):
    reference = {"blocks": [{"id": "a", "text": "old"}, {"id": "b", "text": "other"}]}
    current = deepcopy(reference)
    current["blocks"][0]["text"] = "new"
    block = (reference if side == "reference" else current)["blocks"][1]
    if invalid == "missing":
        block.pop("id")
    else:
        block["id"] = {"duplicate": "a", "empty": "", "integer": 1, "unhashable": ["b"]}[invalid]
    declared = [{"kind": "changed", "path": "/blocks/0/text", "id": "a", "expected": "new", "reason": "r"}]
    assert explain(reference, current, declared) == (differences(reference, current), declared)


@pytest.mark.parametrize("binding", ["a", "outer"])
def test_an_outer_identity_does_not_hide_a_one_sided_inner_list(binding):
    reference = {"groups": [{"id": "outer", "blocks": [{"id": "a", "text": "old"}, {"id": "a"}]}]}
    current = {"groups": [{"id": "outer", "blocks": [{"id": "a", "text": "new"}, {"id": "b"}]}]}
    declared = [{"kind": "changed", "path": "/groups/0/blocks/0/text", "id": binding, "expected": "new", "reason": "r"}]
    assert explain(reference, current, declared) == (differences(reference, current), declared)


@pytest.mark.parametrize("other_id", ["other", "group"])
def test_equal_inner_ids_do_not_override_ambiguous_parent_contexts(other_id):
    reference = {"groups": [{"id": "group", "blocks": [{"id": "a", "text": "old"}]}, {"id": "group"}]}
    current = {"groups": [{"id": "group", "blocks": [{"id": "a", "text": "new"}]}, {"id": other_id}]}
    declared = [{"kind": "changed", "path": "/groups/0/blocks/0/text", "id": "a", "expected": "new", "reason": "r"}]
    assert explain(reference, current, declared) == (differences(reference, current), declared)


def test_a_changed_member_of_a_root_identified_list_is_bound():
    reference, current = [{"id": "a", "text": "old"}], [{"id": "a", "text": "new"}]
    declared = [{"kind": "changed", "path": "/0/text", "id": "a", "expected": "new", "reason": "r"}]
    assert explain(reference, current, declared) == ([], [])


def test_moved_ancestors_keep_their_corresponding_inner_list_context():
    reference = {"groups": [{"id": "group", "blocks": [{"id": "a", "text": "old"}]}]}
    current = {"groups": [{"id": "new-group"}, {"id": "group", "blocks": [{"id": "a", "text": "new"}]}]}
    declared = [{"kind": "changed", "path": "/groups/1/blocks/0/text", "id": "a", "expected": "new", "reason": "r"}]
    found, unused = explain(reference, current, declared)
    assert found == [{"kind": "added", "path": "/groups/0"}]
    assert unused == []
    assert differences(reference, current)[-1]["reference_path"] == "/groups/0/blocks/0/text"


def test_reused_ids_in_different_lists_need_a_specific_path():
    reference = {"groups": [{"id": name, "blocks": [{"id": "a", "text": "old"}]} for name in ("left", "right")]}
    current = deepcopy(reference)
    for group in current["groups"]:
        group["blocks"][0]["text"] = "new"
    broad = {"kind": "changed", "path": "/groups/*/blocks/*/text", "id": "a", "expected": "new", "reason": "r"}
    assert explain(reference, current, [broad]) == ([], [])
    specific = {**broad, "path": "/groups/0/blocks/*/text"}
    assert explain(reference, current, [specific]) == ([{"kind": "changed", "path": "/groups/1/blocks/0/text"}], [])


def test_a_path_wildcard_crosses_slashes_even_with_a_local_id_binding():
    reference = {"blocks": [{"id": "a", "text": "old", "children": [{"id": "a", "text": "old"}]}]}
    current = deepcopy(reference)
    current["blocks"][0]["text"] = current["blocks"][0]["children"][0]["text"] = "new"
    broad = {"kind": "changed", "path": "/blocks/*/text", "id": "a", "expected": "new", "reason": "r"}
    assert explain(reference, current, [broad]) == ([], [])
    specific = {**broad, "path": "/blocks/0/text"}
    assert explain(reference, current, [specific]) == ([{"kind": "changed", "path": "/blocks/0/children/0/text"}], [])


@pytest.mark.parametrize("used_somewhere", [True, False])
def test_global_bindings_remain_unused_when_absent_and_must_be_used_in_some_case(monkeypatch, used_somewhere):
    from tests import test_differential_canonical as corpus

    common = [{"kind": "changed", "path": "/blocks/*/text", "id": "a", "expected": "new", "reason": "r"}]
    reference = {"with-id": {"blocks": [{"id": "a", "text": "old"}]}, "without-id": {"blocks": [{"id": "b", "text": "same"}]}}
    runs = {case: {"canonical": deepcopy(document)} for case, document in reference.items()}
    if used_somewhere:
        runs["with-id"]["canonical"]["blocks"][0]["text"] = "new"
    monkeypatch.setattr(corpus, "CASE_NAMES", list(reference))
    monkeypatch.setattr(corpus, "_declared", lambda _label: {"*": common})
    monkeypatch.setattr(corpus, "_reference", lambda _label, case: {"canonical": reference[case]})
    assert explain(reference["without-id"], runs["without-id"]["canonical"], common) == ([], common)
    corpus.test_the_canonical_output_matches_the_core_before_each_migration(runs, "without-id", "synthetic")
    if used_somewhere:
        corpus.test_a_difference_declared_for_every_case_still_happens(runs, "synthetic")
    else:
        with pytest.raises(AssertionError, match="no case has"):
            corpus.test_a_difference_declared_for_every_case_still_happens(runs, "synthetic")
