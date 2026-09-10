from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from time import perf_counter
from typing import Any


@dataclass(frozen=True)
class DoclingExtraction:
    document: Any
    started_at: datetime
    completed_at: datetime
    duration_ms: int
    version: str
    configuration: dict[str, Any]


class DoclingManifestExtractor:
    """Adaptador fino que converte exatamente uma vez por documento."""

    def __init__(
        self,
        *,
        enable_ocr: bool = True,
        structurer: Any = None,
    ) -> None:
        self.enable_ocr = enable_ocr
        self._structurer = structurer

    def extract(self, source_path: Path) -> DoclingExtraction:
        source_path = source_path.resolve()
        if not source_path.is_file():
            raise FileNotFoundError(f"Documento não encontrado: {source_path}")

        if self._structurer is None:
            structurer = self._build_structurer()
        else:
            structurer = self._structurer
        started_at = datetime.now(timezone.utc)
        started_clock = perf_counter()
        document = self._convert_document(structurer, source_path)
        duration_ms = round((perf_counter() - started_clock) * 1000)
        completed_at = datetime.now(timezone.utc)

        return DoclingExtraction(
            document=document,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            version=_package_version("docling"),
            configuration={
                "ocr": self.enable_ocr,
                "table_structure": True,
                "remote_services": False,
            },
        )

    def _build_structurer(self) -> Any:
        from backend.tools.structurer import DOCLING_AVAILABLE, DoclingStructurer

        if not DOCLING_AVAILABLE:
            raise RuntimeError(
                "Docling não está instalado. Execute `poetry install` ou "
                "`pip install docling`."
            )

        return DoclingStructurer(enable_ocr=self.enable_ocr)

    @staticmethod
    def _convert_document(structurer: Any, source_path: Path) -> Any:
        if hasattr(structurer, "convert_document"):
            return structurer.convert_document(source_path)
        if hasattr(structurer, "_process_document"):
            return structurer._process_document(source_path)
        raise RuntimeError(
            "Structurer incompatível: esperado convert_document() ou _process_document()."
        )


def _package_version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "unknown"
