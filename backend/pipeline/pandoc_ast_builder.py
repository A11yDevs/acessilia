from __future__ import annotations

from typing import Any


def build_pandoc_ast(document: dict[str, Any]) -> dict[str, Any]:
    blocks = []
    for section in document.get("sections", []):
        blocks.extend(_section_to_blocks(section))
    return {
        "pandoc-api-version": [1, 23, 1],
        "meta": {
            "title": {
                "t": "MetaInlines",
                "c": _meta_inlines(document.get("title", "")),
            },
            "lang": {"t": "MetaString", "c": document.get("language", "pt-BR")},
            "verbosity": {
                "t": "MetaString",
                "c": document.get("verbosity", "detailed"),
            },
        },
        "blocks": blocks,
        "source_document": document,
    }


def _section_to_blocks(section: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = [
        {
            "t": "Header",
            "c": [
                section.get("level", 1),
                [section.get("id", ""), [], []],
                _meta_inlines(section.get("title", "")),
            ],
        }
    ]
    for block in section.get("blocks", []):
        blocks.extend(_block_to_ast(block))
    for child in section.get("children", []):
        blocks.extend(_section_to_blocks(child))
    return blocks


def _block_to_ast(block: dict[str, Any]) -> list[dict[str, Any]]:
    block_type = block.get("type")
    if block_type == "heading":
        return [
            {
                "t": "Header",
                "c": [
                    block.get("level", 1),
                    [block.get("id", ""), [], []],
                    _meta_inlines(block.get("text", "")),
                ],
            }
        ]
    if block_type == "paragraph":
        return [{"t": "Para", "c": _meta_inlines(block.get("text", ""))}]
    if block_type == "code":
        return [
            {
                "t": "CodeBlock",
                "c": [
                    [block.get("id", ""), [block.get("language", "")], []],
                    block.get("text", ""),
                ],
            }
        ]
    if block_type == "list":
        return [
            {
                "t": "BulletList",
                "c": [
                    [{"t": "Para", "c": _meta_inlines(str(item))}]
                    for item in block.get("items", [])
                ],
            }
        ]
    if block_type == "table":
        return [
            {"t": "Para", "c": _meta_inlines(" | ".join(str(cell) for cell in row))}
            for row in block.get("rows", [])
        ]
    if block_type == "image":
        return [
            {
                "t": "Para",
                "c": _meta_inlines(block.get("alt_text", block.get("text", ""))),
            }
        ]
    if block_type == "math":
        return [
            {
                "t": "Para",
                "c": [{"t": "Math", "c": [{"t": "InlineMath"}, block.get("text", "")]}],
            }
        ]
    if block_type in {"quote", "details", "note", "warning"}:
        return [
            {
                "t": "BlockQuote",
                "c": [{"t": "Para", "c": _meta_inlines(block.get("text", ""))}],
            }
        ]
    return [{"t": "Para", "c": _meta_inlines(block.get("text", ""))}]


def _meta_inlines(text: str) -> list[dict[str, Any]]:
    inlines: list[dict[str, Any]] = []
    for chunk in str(text).split(" "):
        if not chunk:
            continue
        if inlines:
            inlines.append({"t": "Space"})
        inlines.append({"t": "Str", "c": chunk})
    return inlines
