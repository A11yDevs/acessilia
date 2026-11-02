"""Tests for math block detection in docstruct.blocks.parser."""
from __future__ import annotations

from docstruct.blocks.parser import parse_text_to_blocks


def test_parser_detects_dollar_wrapped_math():
    blocks = parse_text_to_blocks("Introdução.\n\n$E=mc^2$\n\nConclusão.")
    types = [b["type"] for b in blocks]
    assert "math" in types
    math_block = next(b for b in blocks if b["type"] == "math")
    assert math_block["text"] == "$E=mc^2$"


def test_parser_detects_latex_commands_without_dollars():
    blocks = parse_text_to_blocks(r"x = \frac { - b \pm \sqrt { b ^ { 2 } } } { 2 a }")
    assert blocks[0]["type"] == "math"


def test_parser_keeps_normal_text_as_paragraph():
    blocks = parse_text_to_blocks("O preço é $10 e nada mais.")
    assert all(b["type"] != "math" for b in blocks)
