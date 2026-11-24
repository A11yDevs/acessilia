"""The localized location of a unit of work: "page 3", "pages 3, 4", "page 3 of 12".

Moved from ``obligations.py`` (#640, M1), so the enrichment stages that label
their progress do not import the obligation rules that plan them.
"""

from __future__ import annotations

from collections.abc import Iterable

from acessilia_core.i18n import t
from acessilia_core.i18n.stage_messages import (
    STAGE_PAGE,
    STAGE_PAGE_OF,
    STAGE_PAGE_UNKNOWN,
    STAGE_PAGES,
    STAGE_PAGES_SPAN,
)

#: Up to this many pages, a label lists them; beyond, it gives the span.
_PAGES_LISTED = 5


def _pages_label(
    pages: Iterable[int | None], total_pages: int | None = None
) -> str:
    """Localized location of a unit of work, e.g. "page 3" or "pages 3, 4".

    When the document's page count is known and the work sits on a single page,
    the label also names the total, e.g. "page 3 of 12": progress messages pair
    that with image or step counters ("image 11 of 37 (page 18 of 42)"), and
    without the total users could read 37 as the page count. Single-page
    documents keep the plain "page 1" label because "of 1" adds nothing.
    Work over more than ``_PAGES_LISTED`` pages, such as a step over every
    table of the document, gets its count and span, not the list.
    """
    numbers = sorted({page for page in pages if page})
    if not numbers:
        return t(STAGE_PAGE_UNKNOWN)
    if len(numbers) == 1:
        if total_pages is not None and total_pages > 1:
            return t(STAGE_PAGE_OF).format(page=numbers[0], total_pages=total_pages)
        return t(STAGE_PAGE).format(page=numbers[0])
    if len(numbers) > _PAGES_LISTED:
        return t(STAGE_PAGES_SPAN).format(count=len(numbers), first=numbers[0], last=numbers[-1])
    return t(STAGE_PAGES).format(pages=", ".join(str(page) for page in numbers))
