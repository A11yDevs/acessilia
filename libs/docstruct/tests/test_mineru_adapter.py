"""Tests for MinerU adapter in docstruct.adapters.mineru."""
from __future__ import annotations

from docstruct.adapters.mineru import (
    clean_mineru_text,
    extract_mineru_blocks,
    format_mineru_block_text,
)


class TestCleanMineruText:
    def test_line_spacing_preservation(self):
        lines = ["First paragraph line.", "Second paragraph line.", "Third line."]
        assert clean_mineru_text(lines) == "First paragraph line. Second paragraph line. Third line."

    def test_dehyphenation_lowercase_continuation(self):
        lines = [
            "This is an impor-",
            "tant discovery in biology.",
        ]
        assert clean_mineru_text(lines) == "This is an important discovery in biology."

    def test_hyphen_with_uppercase_not_dehyphenated(self):
        lines = [
            "Post-",
            "Modern architecture.",
        ]
        assert clean_mineru_text(lines) == "Post- Modern architecture."

    def test_soft_hyphen_dehyphenation(self):
        lines = [
            "inter\u00ad",
            "national treaty.",
        ]
        assert clean_mineru_text(lines) == "international treaty."

    def test_empty_and_whitespace_pieces(self):
        assert clean_mineru_text([]) == ""
        assert clean_mineru_text(["", "   ", "Valid piece", ""]) == "Valid piece"


class TestFormatMineruBlockText:
    def test_table_html_extraction(self):
        block = {
            "type": "table",
            "blocks": [
                {
                    "type": "table_body",
                    "lines": [
                        {
                            "spans": [
                                {
                                    "type": "table",
                                    "html": "<table><tr><td>1</td></tr></table>",
                                }
                            ]
                        }
                    ],
                }
            ],
        }
        assert format_mineru_block_text(block) == "<table><tr><td>1</td></tr></table>"

    def test_interline_equation_formatting(self):
        block = {
            "type": "interline_equation",
            "latex": r"\int_0^\infty e^{-x} dx = 1",
        }
        assert format_mineru_block_text(block) == r"$$\int_0^\infty e^{-x} dx = 1$$"

    def test_inline_equation_within_text_lines(self):
        block = {
            "type": "text",
            "lines": [
                {
                    "spans": [
                        {"type": "text", "content": "Where "},
                        {"type": "inline_equation", "content": "x > 0"},
                        {"type": "text", "content": " is positive."},
                    ]
                }
            ],
        }
        assert format_mineru_block_text(block) == "Where $x > 0$ is positive."


class TestExtractMineruBlocks:
    def test_extract_blocks_from_middle_json(self):
        middle_json = {
            "pdf_info": [
                {
                    "page_idx": 0,
                    "page_size": [600.0, 800.0],
                    "preproc_blocks": [
                        {
                            "type": "title",
                            "bbox": [50.0, 50.0, 300.0, 80.0],
                            "lines": [
                                {"spans": [{"type": "text", "content": "Document Title"}]}
                            ],
                        },
                        {
                            "type": "text",
                            "bbox": [50.0, 100.0, 500.0, 200.0],
                            "lines": [
                                {"spans": [{"type": "text", "content": "First line of text."}]}
                            ],
                        },
                    ],
                    "discarded_blocks": [
                        {
                            "type": "discarded",
                            "bbox": [50.0, 750.0, 100.0, 780.0],
                            "lines": [
                                {"spans": [{"type": "text", "content": "Footer discarded."}]}
                            ],
                        }
                    ],
                }
            ]
        }

        # Default: discarded excluded
        blocks = extract_mineru_blocks(middle_json, include_discarded=False)
        assert len(blocks) == 2
        assert blocks[0]["type"] == "title"
        assert blocks[0]["text"] == "Document Title"
        assert blocks[0]["bbox"] == (50.0, 50.0, 300.0, 80.0)
        assert blocks[0]["page_index"] == 0

        # With include_discarded=True
        blocks_all = extract_mineru_blocks(middle_json, include_discarded=True)
        assert len(blocks_all) == 3
        assert blocks_all[2]["metadata"]["discarded"] is True
