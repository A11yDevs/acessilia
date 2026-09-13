"""Toolbox-backed PDF split and render operations.

Replaces pdf_splitter.py and image_converter.py with remote calls
to the Acessilia Toolbox. Falls back to local PyMuPDF/pypdf on failure.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from backend.tools.logger import logger
from backend.tools.image_converter import convert_pdf_to_png
from backend.tools.pdf_splitter import split_pdf as _local_split_pdf
from backend.tools.toolbox_pdf_client import ToolboxPdfClient


def _run_async(coro):
    return asyncio.run(coro)


def toolbox_split_pdf(file_path: Path, tmpdir: Path, max_pages: int = 50) -> list[Path]:
    """Split a PDF into individual pages via Toolbox, falling back to local pypdf."""
    try:
        result = _run_async(_split_async(file_path))
        doc = result.get("document", {})
        pages_data = doc.get("pages", [])

        if not pages_data:
            logger.warning("Toolbox split retornou 0 páginas, fallback local")
            return _local_split_pdf(file_path, tmpdir, max_pages)

        from pypdf import PdfReader, PdfWriter

        reader = PdfReader(file_path)
        page_paths: list[Path] = []
        total = min(len(pages_data), max_pages, len(reader.pages))
        for i in range(total):
            writer = PdfWriter()
            writer.add_page(reader.pages[i])
            out = tmpdir / f"pagina_{i + 1:03d}.pdf"
            with open(out, "wb") as f:
                writer.write(f)
            page_paths.append(out)

        logger.info("Toolbox: PDF dividido em {} páginas", len(page_paths))
        return page_paths
    except Exception as e:
        logger.warning("Toolbox split falhou ({}), fallback local", e)
        return _local_split_pdf(file_path, tmpdir, max_pages)


async def _split_async(file_path: Path) -> dict:
    client = ToolboxPdfClient()
    try:
        return await client.split(file_path=file_path)
    finally:
        await client.close()


def toolbox_render_page(pdf_path: Path, page_number: int = 1, dpi: int = 150) -> bytes:
    """Render a PDF page as PNG via Toolbox, falling back to local PyMuPDF."""
    try:
        result = _run_async(_render_async(pdf_path, page_number, dpi))
        import base64
        b64 = result.get("document", {}).get("image_bytes_base64")
        if b64:
            logger.info("Toolbox: página {} renderizada ({} dpi)", page_number, dpi)
            return base64.b64decode(b64)
        logger.warning("Toolbox render sem image_bytes, fallback local")
    except Exception as e:
        logger.warning("Toolbox render falhou ({}), fallback local", e)

    return convert_pdf_to_png(pdf_path, dpi=dpi)


async def _render_async(pdf_path: Path, page_number: int, dpi: int) -> dict:
    client = ToolboxPdfClient()
    try:
        return await client.render(file_path=pdf_path, page_number=page_number, dpi=dpi)
    finally:
        await client.close()


__all__ = ["toolbox_split_pdf", "toolbox_render_page"]