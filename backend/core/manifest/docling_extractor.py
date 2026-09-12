from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from time import perf_counter
from typing import Any

from backend.i18n import t

MSG_SOURCE_NOT_FOUND = "Source file not found: {source_path}"
#: Canonical English id for the hint raised when the optional Docling stack is absent from the environment.
MSG_DOCLING_MISSING = (
    "Docling is not installed. Run `poetry install` or `pip install docling`."
)
MSG_INCOMPATIBLE_STRUCTURER = (
    "Incompatible structurer: expected convert_document() or _process_document()."
)


@dataclass(frozen=True)
class DoclingExtraction:
    document: Any
    started_at: datetime
    completed_at: datetime
    duration_ms: int
    version: str
    configuration: dict[str, Any]


class DoclingManifestExtractor:
    """Thin adapter converting the caller-provided source exactly once per call."""

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
            raise FileNotFoundError(t(MSG_SOURCE_NOT_FOUND).format(source_path=source_path))

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
            raise RuntimeError(t(MSG_DOCLING_MISSING))

        return DoclingStructurer(enable_ocr=self.enable_ocr)

    @staticmethod
    def _convert_document(structurer: Any, source_path: Path) -> Any:
        if hasattr(structurer, "convert_document"):
            return structurer.convert_document(source_path)
        if hasattr(structurer, "_process_document"):
            return structurer._process_document(source_path)
        raise RuntimeError(t(MSG_INCOMPATIBLE_STRUCTURER))


def _package_version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "unknown"
