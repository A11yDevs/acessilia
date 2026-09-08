"""Base contract for export adapters.

Exporters receive a *canonical document* (dict) and a destination path.
They return ``Path`` (or ``None``) and raise on error.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Mapping


class AbstractExporter(ABC):
    """Interface every exporter must implement.

    Each exporter must be able to receive the canonical document and write the
    exported file at ``output_path``.
    """

    @abstractmethod
    def export(self, canonical_doc: Mapping[str, Any], output_path: Path, source_name: str) -> Path:
        """Exports ``canonical_doc`` to ``output_path``.

        Args:
            canonical_doc (dict): Mapping holding the standardized document structure.
            output_path (Path): Destination path where the exported file will be saved.
            source_name (str): Original filename, used by some exporters for naming/templating purposes.
        """
        raise NotImplementedError
