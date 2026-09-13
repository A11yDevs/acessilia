"""Toolbox-backed PDF split and render operations.

Replaces pdf_splitter.py and image_converter.py with remote calls
to the Acessilia Toolbox. Falls back to local PyMuPDF/pypdf on failure.
"""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any

from backend.tools.logger import logger
from backend.tools.pdf_splitter import split_pdf as _local_split_pdf
from backend.tools.toolbox_pdf_client import ToolboxPdfClient


def _run_async(coro) -> Any:
    """Run an async coroutine from a sync context."""
    return asyncio.run(coro)


def toolbox_split_pdf(file_path: Path, tmpdir: Path, max_pages: int = 50) -> list[Path]:
    """Split a PDF into individual pages.

    Validates via Toolbox (pdf.split), then splits locally.
    Falls back to local-only split if Toolbox is unavailable.
    """
    try:
        result = _run_async(_split_async(file_path))
        doc = result.get("document", {})
        page_count = doc.get("page_count", 0)
        logger.info(
            "Toolbox: PDF validated ({} pages), proceeding with local split",
            page_count,
        )
    except Exception as e:
        logger.warning("Toolbox split unavailable ({}), using local fallback", e)

    return _local_split_pdf(file_path, tmpdir, max_pages)


async def _split_async(file_path: Path) -> dict:
    client = ToolboxPdfClient()
    try:
        return await client.split(file_path=file_path)
    finally:
        await client.close()


def toolbox_render_page(pdf_path: Path, page_number: int = 1, dpi: int = 150) -> bytes:
    """Render a PDF page as PNG via Toolbox, falling back to local PyMuPDF.

    The local fallback renders the exact requested page (not just page 1).
    """
    try:
        result = _run_async(_render_async(pdf_path, page_number, dpi))
        b64 = result.get("document", {}).get("image_bytes_base64")
        if b64:
            logger.info("Toolbox: page {} rendered ({} dpi)", page_number, dpi)
            return base64.b64decode(b64)
        logger.warning("Toolbox render missing image_bytes, falling back to local")
    except Exception as e:
        logger.warning("Toolbox render failed ({}), falling back to local", e)

    import fitz

    doc = fitz.open(pdf_path)
    try:
        page = doc[page_number - 1]
        pix = page.get_pixmap(dpi=dpi)
        logger.info("Local fallback: page {} rendered ({} dpi)", page_number, dpi)
        return pix.tobytes("png")
    finally:
        doc.close()


async def _render_async(pdf_path: Path, page_number: int, dpi: int) -> dict:
    client = ToolboxPdfClient()
    try:
        return await client.render(
            file_path=pdf_path, page_number=page_number, dpi=dpi
        )
    finally:
        await client.close()


__all__ = ["toolbox_split_pdf", "toolbox_render_page"]