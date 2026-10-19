"""What a benchmark adapter provides to the harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class BenchPage:
    """One page: the unit the core runs on and the metrics score."""

    item_id: str
    document_id: str
    page: int
    image_path: Path
    gt_path: Path | None = None
    meta: dict = field(default_factory=dict)


class Dataset(Protocol):
    name: str

    def download(self, split: str, root: Path, limit: int | None = None) -> int:
        """Materialize ``split`` as a local tree under ``root``; return pages written."""

    def pages(self, root: Path) -> list[BenchPage]:
        """Pages of a local tree, sorted by item id."""

    def build_submission(self, pages: list[BenchPage], predictions: Path, out: Path) -> Path:
        """Package predictions in the benchmark's submission format."""
