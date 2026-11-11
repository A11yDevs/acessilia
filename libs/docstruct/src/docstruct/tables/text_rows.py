"""Rows of a table read from its plain text (pure).

Moved from the core's PDDL orchestrator (#402): when a table element reaches
the payload with text but no structure, these rules look for a pipe table or
delimited lines in that text.
"""
from __future__ import annotations

import re


def rows_from_visual_table_text(raw_text: str) -> list[list[str]]:
    """Rows of a table read from its plain text, or ``[]``.

    Tries a pipe table first, then tab-separated lines, then the better of
    semicolon- and comma-separated lines (semicolons on a tie). A result
    counts only when it scores at least 4 (rows times widest row).
    """
    text = raw_text.strip()
    if not text:
        return []

    rows = rows_from_pipe_table(text)
    if rows:
        return rows

    rows = rows_from_delimited_lines(text, delimiter="\t")
    if rows:
        return rows

    semicolon_rows = rows_from_delimited_lines(text, delimiter=";")
    comma_rows = rows_from_delimited_lines(text, delimiter=",")
    if score_rows(semicolon_rows) >= score_rows(comma_rows):
        return semicolon_rows
    return comma_rows


def rows_from_pipe_table(text: str) -> list[list[str]]:
    """Rows of a ``|``-separated table, without Markdown separator lines."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    rows: list[list[str]] = []
    for line in lines:
        if "|" not in line:
            continue
        if looks_like_markdown_separator(line):
            continue
        cleaned = line.strip().strip("|")
        cells = [cell.strip() for cell in cleaned.split("|")]
        cells = [cell for cell in cells if cell]
        if len(cells) >= 2:
            rows.append(cells)
    if score_rows(rows) >= 4:
        return rows
    return []


def rows_from_delimited_lines(text: str, *, delimiter: str) -> list[list[str]]:
    """Rows split on ``delimiter``; lines that hold a ``|`` are left out."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    rows: list[list[str]] = []
    for line in lines:
        if delimiter not in line:
            continue
        if "|" in line and delimiter != "|":
            continue
        cells = [cell.strip() for cell in line.split(delimiter)]
        cells = [cell for cell in cells if cell]
        if len(cells) >= 2:
            rows.append(cells)
    if score_rows(rows) >= 4:
        return rows
    return []


def looks_like_markdown_separator(line: str) -> bool:
    """Whether ``line`` is a Markdown table separator (``| --- | :--: |``)."""
    cleaned = line.strip().strip("|").replace(" ", "")
    if not cleaned:
        return False
    parts = cleaned.split("|")
    if not parts:
        return False
    return all(re.fullmatch(r":?-{2,}:?", part or "") for part in parts)


def score_rows(rows: list[list[str]]) -> int:
    """Rows times the widest row: how much of a table ``rows`` make."""
    if not rows:
        return 0
    row_count = len(rows)
    width = max((len(row) for row in rows), default=0)
    return row_count * width


__all__ = [
    "looks_like_markdown_separator",
    "rows_from_delimited_lines",
    "rows_from_pipe_table",
    "rows_from_visual_table_text",
    "score_rows",
]
