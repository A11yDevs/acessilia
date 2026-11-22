"""Existing format delivery policy, including legacy and internal roles.

The worker owns its plan, flags and failure policy. This catalogue owns format
metadata. API labels are historical wire tokens; display labels are English
msgids translated by consumers. No translation or I/O happens here.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

from acessilia_core.export.messages import (
    MSG_FORMAT_DOCX,
    MSG_FORMAT_HTML,
    MSG_FORMAT_MP3,
    MSG_FORMAT_PDF,
    MSG_FORMAT_PDF_UA,
    MSG_FORMAT_TXT,
    MSG_FORMAT_ZIP,
)
from acessilia_sdk.toolbox.capabilities import TOOLBOX_CAPABILITIES
from acessilia_sdk.toolbox.clients import ToolboxDocxClient, ToolboxPdfUaClient
from docstruct.export.formats import FormatSpec

DETAIL_LEVELS = frozenset({"basic", "detailed", "technical"})


@dataclass(frozen=True, kw_only=True)
class FormatDelivery:
    spec: FormatSpec
    status: Literal["stable", "experimental", "internal"]
    produced: bool
    downloadable: bool
    packaged_in_zip: bool
    output_suffix: str
    label_msgid: str
    api_label: str | None
    capability: str | None = None
    detail_levels: frozenset[str] = DETAIL_LEVELS
    canonical_export: bool = False
    legacy: bool = False

    def available(self, *, experimental: bool = False) -> bool:
        return self.status == "stable" or (experimental and self.status == "experimental")

    def output_filename(self, stem: str) -> str:
        separator = "" if self.output_suffix.startswith("_") else "."
        return f"{stem}{separator}{self.output_suffix}"


def _remote_spec(format_id: str, client: type[Any], extension: str) -> FormatSpec:
    capability = TOOLBOX_CAPABILITIES[client.capability]
    return FormatSpec(format_id, str(capability.contract_version), client.media_type, extension, "remote")


TXT = FormatDelivery(
    spec=FormatSpec("txt", "1", "text/plain; charset=utf-8", "txt", "local_pure"),
    status="stable", produced=True, downloadable=True, packaged_in_zip=True,
    output_suffix="txt", label_msgid=MSG_FORMAT_TXT, api_label="texto", canonical_export=True,
)
DOCX = FormatDelivery(
    spec=_remote_spec("docx", ToolboxDocxClient, "docx"),
    status="stable", produced=True, downloadable=True, packaged_in_zip=True,
    output_suffix="docx", label_msgid=MSG_FORMAT_DOCX, api_label="word",
    capability=TOOLBOX_CAPABILITIES[ToolboxDocxClient.capability].id, canonical_export=True,
)
# Existing PDF links retain their identity and media type; no new PDF is made.
PDF = FormatDelivery(
    spec=FormatSpec("pdf", "1", "application/pdf", "pdf", None),
    status="stable", produced=False, downloadable=True, packaged_in_zip=False,
    output_suffix="pdf", label_msgid=MSG_FORMAT_PDF, api_label="pdf",
    detail_levels=frozenset(), legacy=True,
)
PDF_UA = FormatDelivery(
    spec=_remote_spec("pdf_ua", ToolboxPdfUaClient, "pdf"),
    status="stable", produced=True, downloadable=True, packaged_in_zip=True,
    output_suffix="pdf_ua.pdf", label_msgid=MSG_FORMAT_PDF_UA, api_label="pdf/ua",
    capability=TOOLBOX_CAPABILITIES[ToolboxPdfUaClient.capability].id, canonical_export=True,
)
HTML = FormatDelivery(
    spec=FormatSpec("html", "1", "text/html; charset=utf-8", "html", "local_pure"),
    status="stable", produced=True, downloadable=True, packaged_in_zip=True,
    output_suffix="html", label_msgid=MSG_FORMAT_HTML, api_label="html", canonical_export=True,
)
# The existing edge-tts deviation (ADR-0003 / Toolbox #73), not a Toolbox binding.
MP3 = FormatDelivery(
    spec=FormatSpec("mp3", "1", "audio/mpeg", "mp3", "local"),
    status="stable", produced=True, downloadable=True, packaged_in_zip=True,
    output_suffix="mp3", label_msgid=MSG_FORMAT_MP3, api_label="audio",
)
ZIP = FormatDelivery(
    spec=FormatSpec("zip", "1", "application/zip", "zip", "local"),
    status="stable", produced=True, downloadable=True, packaged_in_zip=False,
    output_suffix="_acessivel.zip", label_msgid=MSG_FORMAT_ZIP, api_label="completo",
    detail_levels=frozenset(),
)
DRBENCH_MD = FormatDelivery(
    spec=FormatSpec("drbench_md", "1", "text/markdown; charset=utf-8", "md", "local_pure"),
    status="internal", produced=True, downloadable=False, packaged_in_zip=False,
    output_suffix="drbench.md", label_msgid="Benchmark Markdown", api_label=None,
)

# Preserve the historical download listing order. Production order is the worker's.
CATALOG = MappingProxyType({item.spec.id: item for item in (TXT, DOCX, PDF, PDF_UA, HTML, MP3, ZIP, DRBENCH_MD)})


def downloadable_formats(*, experimental: bool = False) -> tuple[FormatDelivery, ...]:
    return tuple(item for item in CATALOG.values() if item.downloadable and item.available(experimental=experimental))


DOWNLOAD_MEDIA_TYPES = {item.spec.id: item.spec.media_type for item in downloadable_formats()}
DOWNLOAD_LABELS = {item.spec.id: item.api_label for item in downloadable_formats()}
DOWNLOAD_SUFFIXES = {item.spec.id: item.output_suffix for item in downloadable_formats() if item.output_suffix != item.spec.id}


__all__ = [
    "CATALOG", "DETAIL_LEVELS", "DOCX", "DOWNLOAD_LABELS", "DOWNLOAD_MEDIA_TYPES",
    "DOWNLOAD_SUFFIXES", "DRBENCH_MD", "FormatDelivery", "HTML", "MP3", "PDF",
    "PDF_UA", "TXT", "ZIP", "downloadable_formats",
]
