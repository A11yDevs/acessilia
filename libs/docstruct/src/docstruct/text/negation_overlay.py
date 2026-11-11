"""Reattach a detached negation slash to the relation it negates.

TeX draws ``≠`` (and ``∉``, ``≮``, ...) as a slash glyph laid over the
relation. A legacy text layer may extract that slash as its own text cell,
``U+0338`` (combining long solidus overlay), which extractors then deliver as a
separate element: the relation reads ``h = 0`` and the slash is lost, which
inverts the meaning.

The slash's position is the only link back to its relation. The functions
here are pure and coordinate-free: the caller turns boxes into positions
relative to the element that holds the relation, and gets back the index of
the character to negate, or ``None`` when the choice is not unambiguous.
Composing the wrong ``=`` would turn a true statement into a false one, so an
ambiguous case is left alone.
"""
from __future__ import annotations

import unicodedata
from typing import Any

from docstruct.tables.ast import TABLE_SECTIONS
from docstruct.text.math_spans import mask_inline_math

NEGATION_OVERLAY = "̸"

#: How much farther the second-best candidate must be than the best one, and
#: the least gap between them (characters in text, columns in a table), so a
#: best candidate at distance 0 does not accept a neighbour right beside it.
_MARGIN = 2.0
_MIN_TEXT_GAP = 3.0
_MIN_COLUMN_GAP = 0.5

#: A text line is about this many slash heights tall (glyph plus leading).
OVERLAY_LINE_HEIGHTS = 1.25


def negates(char: str) -> bool:
    """Whether ``char`` has a precomposed negated form (``=`` → ``≠``, ``∈`` → ``∉``)."""
    composed = unicodedata.normalize("NFC", char + NEGATION_OVERLAY)
    return len(composed) == 1 and composed != char


def is_detached_overlay(text: str | None) -> bool:
    """Whether ``text`` is nothing but negation slashes (and whitespace)."""
    stripped = "".join((text or "").split())
    return bool(stripped) and set(stripped) == {NEGATION_OVERLAY}


def compose_negation(text: str, index: int) -> str:
    """``text`` with the relation at ``index`` negated (``h = 0`` → ``h ≠ 0``)."""
    negated = unicodedata.normalize("NFC", text[index] + NEGATION_OVERLAY)
    return text[:index] + negated + text[index + 1 :]


def locate_in_text(
    text: str, *, lines: int, line_position: float, x_fraction: float
) -> int | None:
    """Index of the relation a slash negates, in text laid out on ``lines`` lines.

    ``line_position`` is the slash's vertical position in lines from the top
    of the element (0 = first line); ``x_fraction`` its horizontal position
    across the element (0 = left edge, 1 = right edge). Text is assumed to
    fill the lines evenly, which is rough, so a candidate is accepted only when
    it falls on the estimated line and the second-closest candidate is at least
    twice as far.
    """
    candidates = [index for index, char in enumerate(text) if negates(char)]
    if not candidates or lines < 1 or not text:
        return None
    line = min(lines - 1, max(0, int(line_position)))
    per_line = len(text) / lines
    estimate = (line + min(max(x_fraction, 0.0), 1.0)) * per_line
    ranked = sorted(candidates, key=lambda index: abs(index - estimate))
    best = ranked[0]
    if not line * per_line - per_line / 2 <= best <= (line + 1) * per_line + per_line / 2:
        return None
    if len(ranked) > 1:
        best_distance, second_distance = abs(best - estimate), abs(ranked[1] - estimate)
        if second_distance < _MARGIN * best_distance or second_distance - best_distance < _MIN_TEXT_GAP:
            return None
    return best


def locate_in_grid(
    rows: list[list[str]], *, row_position: float, column_position: float
) -> tuple[int, int, int] | None:
    """``(row, column, index)`` of the relation a slash negates in a table.

    ``row_position``/``column_position`` are the slash's position in rows and
    columns from the top-left cell. Only the estimated row is searched; its
    candidates are compared by the distance from the slash to the centre of
    their column, with the same margin as :func:`locate_in_text`, and a cell
    holding more than one candidate is ambiguous.

    Every column counts as equally wide and ``rows`` must already be laid on
    the visual column grid (a cell spanning two columns takes two slots, the
    second empty): a table AST carries no column widths, so a very wide column
    next to a narrow one shifts the estimate, and the margin is what refuses
    the close calls this produces.
    """
    row = int(row_position)
    if not 0 <= row < len(rows):
        return None
    candidates: list[tuple[float, int, int]] = []
    for column, cell in enumerate(rows[row]):
        indices = [index for index, char in enumerate(cell or "") if negates(char)]
        if not indices:
            continue
        distance = abs(column + 0.5 - column_position)
        if len(indices) > 1:
            candidates.append((distance, column, -1))
        else:
            candidates.append((distance, column, indices[0]))
    if not candidates:
        return None
    candidates.sort()
    distance, column, index = candidates[0]
    if index < 0:
        return None
    if len(candidates) > 1:
        second = candidates[1][0]
        if second < _MARGIN * distance or second - distance < _MIN_COLUMN_GAP:
            return None
    return row, column, index


def table_grid(table_ast: Any) -> list[list[tuple[str, dict[str, Any] | None]]]:
    """The table's rows on its visual column grid: a cell spanning ``n`` columns
    takes ``n`` slots, its text in the first, so a slash's column position
    matches the cell under it. Row spans are not expanded (the slash's row is
    estimated from the AST rows), and every column is taken as equally wide —
    the AST carries no widths; ``locate_in_grid``'s margin refuses close calls.
    """
    if not isinstance(table_ast, dict):
        return []
    grid: list[list[tuple[str, dict[str, Any] | None]]] = []
    for section in TABLE_SECTIONS:
        for row in table_ast.get(section) or []:
            if not isinstance(row, dict):
                continue
            slots: list[tuple[str, dict[str, Any] | None]] = []
            for cell in row.get("cells") or []:
                if not isinstance(cell, dict):
                    continue
                span = max(1, int(cell.get("colspan") or 1))
                slots.append((str(cell.get("text") or ""), cell))
                slots.extend(("", None) for _ in range(span - 1))
            grid.append(slots)
    return grid


def compose_in_grid(table_ast: Any, x_fraction: float, y_fraction: float) -> str:
    """Negate the relation under the slash in a table; returns the outcome.

    ``x_fraction`` and ``y_fraction`` place the slash in the table's box. The
    chosen cell's ``text`` is rewritten in place, in ``table_ast``. A relation
    inside an inline ``$…$`` span is not a candidate (#260). Outcomes:
    ``composed``, ``no-candidate`` or ``ambiguous``.
    """
    grid = table_grid(table_ast)
    texts = [[mask_inline_math(text) for text, _ in row] for row in grid]
    if not any(negates(char) for row in texts for text in row for char in text):
        return "no-candidate"
    columns = max((len(row) for row in grid), default=0)
    found = locate_in_grid(
        texts,
        row_position=y_fraction * len(grid),
        column_position=x_fraction * columns,
    )
    if found is None:
        return "ambiguous"
    row, column, index = found
    cell = grid[row][column][1]
    if cell is None:
        return "ambiguous"
    cell["text"] = compose_negation(str(cell["text"]), index)
    return "composed"


def compose_in_text(
    text: str, x_fraction: float, y_fraction: float, height: float, slash_height: float
) -> tuple[str, str | None]:
    """Negate the relation under the slash in a text; ``(outcome, new text)``.

    ``height`` is the text's box height and ``slash_height`` the slash's, in
    the same unit, to estimate how many lines the text spans. The new text is
    ``None`` unless the outcome is ``composed``. A relation inside an inline
    ``$…$`` span is not a candidate (#260).
    """
    prose = mask_inline_math(text)
    if not any(negates(char) for char in prose):
        return "no-candidate", None
    lines = max(1, round(height / (slash_height * OVERLAY_LINE_HEIGHTS)))
    index = locate_in_text(
        prose, lines=lines, line_position=y_fraction * lines, x_fraction=x_fraction
    )
    if index is None:
        return "ambiguous", None
    return "composed", compose_negation(text, index)


__all__ = [
    "NEGATION_OVERLAY",
    "OVERLAY_LINE_HEIGHTS",
    "compose_in_grid",
    "compose_in_text",
    "compose_negation",
    "is_detached_overlay",
    "locate_in_grid",
    "locate_in_text",
    "negates",
    "table_grid",
]
