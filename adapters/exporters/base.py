"""Base contract for export adapters.

Exporters receive a *canonical document* (dict) and a destination path.
They return ``Path`` (or ``None``) and raise on error.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Mapping


class AbstractExporter(ABC):
    """Interface que todos os exportadores devem implementar.

    Cada exportador deve ser capaz de receber o documento canônico e escrever o
    arquivo no ``output_path``.
    """

    @abstractmethod
    def export(self, canonical_doc: Mapping[str, Any], output_path: Path, source_name: str) -> Path:
        """Exporta ``canonical_doc`` para ``output_path``.

        Args:
            canonical_doc: Dicionário contendo a estrutura padronizada.
            output_path: Caminho onde o arquivo será salvo.
            source_name: Nome original do arquivo (usado em alguns exportadores).
        """
        raise NotImplementedError
