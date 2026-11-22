"""The walker owns traversal and dispatch, while consumers own output policy."""

import json
from copy import deepcopy
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

from docstruct.export.walk import (
    BLOCK_TYPES,
    BlockContext,
    SectionContext,
    Visitor,
    walk,
)


def document():
    return {"sections": [
        {"id": "root", "title": "Title", "level": 1, "blocks": [
            {"id": "alias", "type": "heading", "text": "Title", "level": 1},
            {"id": "body", "type": "paragraph", "text": "Body"},
        ], "children": [
            {"id": "child", "blocks": [{"id": "child-body", "type": "paragraph"}],
             "children": [{"id": "grandchild", "blocks": []}]},
            {"id": "sibling", "blocks": []},
        ]},
        {"id": "second", "blocks": [{"id": "unknown", "type": "custom"}]},
    ]}


def test_dispatch_contract_matches_all_schema_types():
    root = Path(__file__).resolve().parents[3]
    schema = json.loads((root / "schemas/accessible_document.schema.json").read_text("utf-8"))
    assert BLOCK_TYPES == tuple(schema["$defs"]["block"]["properties"]["type"]["enum"])
    assert {field.name for field in fields(Visitor)} == {
        *BLOCK_TYPES, "default", "enter_section", "leave_section",
    }


@pytest.mark.parametrize("kind", BLOCK_TYPES)
def test_each_known_type_has_its_own_callback(kind):
    source = {"sections": [{"blocks": [{"type": kind}]}]}
    visitor = Visitor(default=lambda block, ctx: "fallback", **{
        kind: lambda block, ctx: (kind, ctx.section.path, ctx.index),
    })
    assert list(walk(source, visitor)) == [(kind, (0,), 0)]


@pytest.mark.parametrize("kind", [None, "custom", "__dict__", [], 7])
def test_unknown_types_use_only_the_explicit_fallback(kind):
    source = {"sections": [{"blocks": [{"type": kind}]}]}
    assert list(walk(source, Visitor(default=lambda block, ctx: "fallback"))) == ["fallback"]


def test_default_is_mandatory_and_handles_unregistered_known_types():
    with pytest.raises(TypeError):
        Visitor()
    with pytest.raises(TypeError, match="callable"):
        Visitor(default=None)
    source = {"sections": [{"blocks": [{"type": "paragraph"}]}]}
    assert list(walk(source, Visitor(default=lambda block, ctx: "known fallback"))) == ["known fallback"]


def test_depth_first_order_section_hooks_and_original_context():
    source = document()
    before = deepcopy(source)
    visitor = Visitor(
        default=lambda block, ctx: ("block", block["id"], ctx.section.path, ctx.index),
        enter_section=lambda ctx: ("enter", ctx.data["id"], ctx.path, ctx.depth),
        leave_section=lambda ctx: ("leave", ctx.data["id"], ctx.path),
    )
    assert list(walk(source, visitor)) == [
        ("enter", "root", (0,), 0),
        ("block", "alias", (0,), 0), ("block", "body", (0,), 1),
        ("enter", "child", (0, 0), 1), ("block", "child-body", (0, 0), 0),
        ("enter", "grandchild", (0, 0, 0), 2), ("leave", "grandchild", (0, 0, 0)),
        ("leave", "child", (0, 0)),
        ("enter", "sibling", (0, 1), 1), ("leave", "sibling", (0, 1)),
        ("leave", "root", (0,)),
        ("enter", "second", (1,), 0), ("block", "unknown", (1,), 0),
        ("leave", "second", (1,)),
    ]
    assert source == before
    assert json.dumps(source) == json.dumps(before)


def test_selection_does_not_prune_children_or_renumber_blocks():
    source = document()
    seen = []

    def select(block, ctx):
        seen.append((block["id"], ctx.section.path, ctx.index))
        return block["id"] == "child-body"

    visitor = Visitor(
        default=lambda block, ctx: block["id"],
        enter_section=lambda ctx: ctx.data["id"],
    )
    assert list(walk(source, visitor, select)) == [
        "root", "child", "child-body", "grandchild", "sibling", "second",
    ]
    assert seen == [("alias", (0,), 0), ("body", (0,), 1), ("child-body", (0, 0), 0), ("unknown", (1,), 0)]


@pytest.mark.parametrize("field", ["text", "title"])
@pytest.mark.parametrize("same_id", [False, True])
def test_legacy_metadata_is_available_but_does_not_omit_blocks(field, same_id):
    legacy = {"id": "root" if same_id else "alias", "type": "heading", field: "Title", "level": 1}
    section = {"id": "root", "title": "Title", "level": 1, "blocks": [legacy]}
    context = SectionContext(section, (0,))
    assert context.legacy_title is legacy
    assert context.title_alias == ("" if same_id else "alias")
    assert list(walk({"sections": [section]}, Visitor(
        default=lambda block, ctx: (block is legacy, ctx.is_legacy_title),
    ))) == [(True, True)]
    assert list(walk({"sections": [section]}, Visitor(default=lambda block, ctx: block),
                     lambda block, ctx: not ctx.is_legacy_title)) == []


@pytest.mark.parametrize("change", ["title", "level", "position", "untitled"])
def test_distinct_headings_are_not_marked_as_legacy(change):
    source = document()
    section = source["sections"][0]
    if change == "title":
        section["blocks"][0]["text"] = "Other"
    elif change == "level":
        section["blocks"][0]["level"] = 2
    elif change == "position":
        section["blocks"].reverse()
    else:
        section["title"] = ""
    ctx = SectionContext(section, (0,))
    assert ctx.legacy_title is None and ctx.title_alias == ""
    assert not BlockContext(ctx, 0).is_legacy_title


def test_context_metadata_is_frozen_and_retains_the_original_mapping():
    section = document()["sections"][0]
    ctx = SectionContext(section, (0,))
    assert ctx.data is section
    with pytest.raises(FrozenInstanceError):
        ctx.path = (1,)
    block_ctx = BlockContext(ctx, 1)
    with pytest.raises(FrozenInstanceError):
        block_ctx.index = 0


def test_only_none_is_suppressed_not_falsey_results():
    values = [None, "", 0, False, [], {}]
    source = {"sections": [{"blocks": [{"value": value} for value in values]}]}
    result = list(walk(source, Visitor(default=lambda block, ctx: block["value"])))
    assert result == values[1:]
    assert [type(value) for value in result] == [str, int, bool, list, dict]


@pytest.mark.parametrize("source", [{}, {"sections": []}])
def test_empty_documents_have_no_events(source):
    assert list(walk(source, Visitor(default=lambda block, ctx: "unexpected"))) == []


def test_callbacks_are_lazy():
    calls = []
    iterator = walk(document(), Visitor(default=lambda block, ctx: calls.append(block["id"])))
    assert calls == []
    assert list(iterator) == []
    assert calls == ["alias", "body", "child-body", "unknown"]


@pytest.mark.parametrize("phase", ["select", "enter", "block", "leave"])
def test_consumer_exceptions_propagate(phase):
    def fail(*args):
        raise RuntimeError("consumer failed")

    visitor = Visitor(
        default=fail if phase == "block" else lambda block, ctx: None,
        enter_section=fail if phase == "enter" else None,
        leave_section=fail if phase == "leave" else None,
    )
    with pytest.raises(RuntimeError, match="consumer failed"):
        list(walk(document(), visitor, fail if phase == "select" else None))
