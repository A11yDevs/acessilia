from __future__ import annotations

from typing import Any

from backend.pipeline.table_ast import split_header_and_body
from backend.pipeline.table_ast import table_ast_from_block


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
        table_ast = table_ast_from_block(block)
        if table_ast is None:
            return []
        return [_table_to_pandoc_ast(table_ast)]
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


def _table_to_pandoc_ast(table_ast: dict[str, Any]) -> dict[str, Any]:
    header_rows, body_rows, footer_rows = split_header_and_body(table_ast)

    all_rows = header_rows + body_rows + footer_rows
    column_count = max((len(row.get("cells", [])) for row in all_rows), default=1)
    colspecs = [
        [{"t": "AlignDefault"}, {"t": "ColWidthDefault"}]
        for _ in range(column_count)
    ]

    caption_text = table_ast.get("caption")
    short_caption = _meta_inlines(caption_text) if isinstance(caption_text, str) and caption_text.strip() else None
    caption = [short_caption, []]

    head = [["", [], []], [_pandoc_row(row, header=True) for row in header_rows]]
    bodies = [
        [
            ["", [], []],
            0,
            [],
            [_pandoc_row(row, header=False) for row in body_rows],
        ]
    ]
    foot = [["", [], []], [_pandoc_row(row, header=False) for row in footer_rows]]

    return {
        "t": "Table",
        "c": [
            ["", [], []],
            caption,
            colspecs,
            head,
            bodies,
            foot,
        ],
    }


def _pandoc_row(row: dict[str, Any], *, header: bool) -> list[Any]:
    cells = row.get("cells", []) if isinstance(row, dict) else []
    return [
        ["", [], []],
        [
            _pandoc_cell(cell, header=header)
            for cell in cells
            if isinstance(cell, dict) and str(cell.get("text", "")).strip()
        ],
    ]


def _pandoc_cell(cell: dict[str, Any], *, header: bool) -> list[Any]:
    text = str(cell.get("text", "")).strip()
    rowspan = cell.get("rowspan") if isinstance(cell.get("rowspan"), int) else 1
    colspan = cell.get("colspan") if isinstance(cell.get("colspan"), int) else 1

    scope = str(cell.get("scope", "")).strip().lower()
    if scope in {"row", "rowgroup"}:
        alignment = {"t": "AlignRight"}
    elif scope in {"col", "colgroup"}:
        alignment = {"t": "AlignLeft"}
    else:
        alignment = {"t": "AlignDefault"}

    block_kind = "Plain" if header else "Para"
    return [
        ["", [], []],
        alignment,
        max(1, int(rowspan)),
        max(1, int(colspan)),
        [{"t": block_kind, "c": _meta_inlines(text)}],
    ]
