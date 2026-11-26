"""The two ``id_factory`` injection hooks are distinguishable (#675).

Both parameters share the name ``id_factory`` but not the arity: the document
hook takes no arguments, the block hook takes the block's 1-based index. The
aliases in ``docstruct.types`` are what the annotations expose.
"""
from __future__ import annotations

from typing import Callable, get_type_hints

from docstruct.blocks.parser import parse_text_to_blocks
from docstruct.canonical import build_canonical_document
from docstruct.types import BlockIdFactory, DocumentIdFactory


def test_the_aliases_have_different_arities() -> None:
    assert DocumentIdFactory == Callable[[], str]
    assert BlockIdFactory == Callable[[int], str]
    assert DocumentIdFactory != BlockIdFactory


def test_canonical_annotates_a_document_id_factory() -> None:
    hints = get_type_hints(build_canonical_document)

    assert hints["id_factory"] == DocumentIdFactory | None


def test_parser_annotates_a_block_id_factory() -> None:
    hints = get_type_hints(parse_text_to_blocks)

    assert hints["id_factory"] == BlockIdFactory | None


def test_each_hook_is_invoked_with_its_declared_arguments() -> None:
    document = build_canonical_document("text", id_factory=lambda: "doc-custom")
    blocks = parse_text_to_blocks(
        "primeiro\n\nsegundo", id_factory=lambda index: f"blk-custom-{index}"
    )

    assert document["id"] == "doc-custom"
    assert [block["id"] for block in blocks] == ["blk-custom-1", "blk-custom-2"]
