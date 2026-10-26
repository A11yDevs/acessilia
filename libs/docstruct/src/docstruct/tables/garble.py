"""Tables an extractor read with the right cells in the wrong shape.

Two shapes come back from slide decks often enough to be worth naming:

- **collapsed rows** — every row of a column landed in one cell, so a row's
  cells each hold the same number of values ("yota zeta exa …" beside
  "Y Z E …" beside "10²⁴ 10²¹ 10¹⁸ …"). 006.pdf slide 5 read its two prefix
  tables as one row of ten values per cell. A cell must hold more than twice
  as many values as the table has rows, so a short table with long header
  cells ("Summary of main findings" over two rows) is not named.
- **duplicated cells** — each cell holds its text twice ("34.97 34.97"), as
  when two overlapping text layers are read together. 006.pdf slide 15 read
  its chlorine isotope table that way.

Either is a reason to read the table again from its image; neither is fixed
here, since splitting on spaces cannot tell "Atomic Mass" from two values.
Pure functions, no I/O.
"""
from __future__ import annotations

from typing import Literal

TableGarbleReason = Literal["collapsed_rows", "duplicated_cells"]

#: Fewest values a collapsed cell holds: a row of short cells that happen to
#: have three words each ("New York City") is a real row.
COLLAPSED_MIN_VALUES = 4

#: Share of non-empty cells that must hold their text twice.
DUPLICATED_MIN_SHARE = 0.6


def table_garble_reason(rows: list[list[str]]) -> TableGarbleReason | None:
    """Why ``rows`` (cell texts, row by row) look misread, or None."""
    if _collapsed(rows):
        return "collapsed_rows"
    if _duplicated(rows):
        return "duplicated_cells"
    return None


def _collapsed(rows: list[list[str]]) -> bool:
    """A row whose cells all hold the same number of values, over twice the table's rows."""
    for row in rows:
        counts = {len(cell.split()) for cell in row if cell.strip()}
        filled = sum(1 for cell in row if cell.strip())
        if filled >= 2 and len(counts) == 1:
            (values,) = counts
            if values >= COLLAPSED_MIN_VALUES and values > 2 * len(rows):
                return True
    return False


def _duplicated(rows: list[list[str]]) -> bool:
    cells = [cell.split() for row in rows for cell in row if cell.strip()]
    doubled = sum(
        1 for words in cells
        if len(words) % 2 == 0 and words[: len(words) // 2] == words[len(words) // 2 :]
    )
    return doubled >= 2 and doubled >= DUPLICATED_MIN_SHARE * len(cells)


__all__ = [
    "COLLAPSED_MIN_VALUES",
    "DUPLICATED_MIN_SHARE",
    "TableGarbleReason",
    "table_garble_reason",
]
