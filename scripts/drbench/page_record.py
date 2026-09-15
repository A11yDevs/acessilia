"""Canonical Dr.DocBench page record helpers.

A ``DrBenchPage`` carries the metadata required by the EvalAI submission
format: ``subject``, ``document_id``, ``page`` plus the parsed page image
path. Item ids follow ``{doc_uuid}_p{page_no}``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

ITEM_ID_RE = re.compile(r"^(?P<doc>[0-9a-fA-F-]+)_p(?P<page>\d+)$")


@dataclass
class DrBenchPage:
    """One page of the Dr.DocBench dataset (submission unit)."""

    item_id: str
    document_id: str
    page: int
    subject: str = ""
    split: str = "dev"
    image_path: Path | None = None
    ground_truth_md: str | None = None
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_item_id(
        cls,
        item_id: str,
        *,
        split: str = "dev",
        subject: str = "",
    ) -> "DrBenchPage":
        m = ITEM_ID_RE.match(item_id)
        if not m:
            raise ValueError(f"Invalid Dr.DocBench item id: {item_id!r}")
        return cls(
            item_id=item_id,
            document_id=m.group("doc"),
            page=int(m.group("page")),
            subject=subject,
            split=split,
        )

    @property
    def markdown_filename(self) -> str:
        """Output file name for the *.drbench.md prediction."""
        return f"{self.item_id}.drbench.md"


def parse_items_metadata(items: list[dict]) -> list[DrBenchPage]:
    """Convert Toolbox list_items/get_item payloads into DrBenchPage records."""
    pages: list[DrBenchPage] = []
    for raw in items:
        item_id = raw.get("id") or raw.get("item_id") or ""
        metadata = raw.get("metadata") or {}
        try:
            page = DrBenchPage.from_item_id(
                item_id,
                split=raw.get("split", "dev"),
                subject=str(metadata.get("subject", "")),
            )
        except ValueError:
            continue
        page.extra = metadata
        pages.append(page)
    return pages


__all__ = ["DrBenchPage", "parse_items_metadata", "ITEM_ID_RE"]
