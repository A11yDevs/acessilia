"""Toolbox-backed OCR text extraction.

Replaces local tesseract/rapidocr with a remote call to the Acessilia
Toolbox document.ocr capability. Falls back to empty string on failure.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from backend.tools.logger import logger
from backend.tools.toolbox_ocr_client import ToolboxOcrClient


def _run_async(coro):
    return asyncio.run(coro)


def toolbox_ocr_text(
    file_path: Path,
    *,
    language: str = "pt-BR",
    force_ocr: bool = True,
) -> str:
    """Extract OCR text from a document/image via Toolbox."""
    try:
        return _run_async(_ocr_async(file_path, language, force_ocr))
    except Exception as e:
        logger.warning("Toolbox OCR falhou ({}), retornando vazio", e)
        return ""


async def _ocr_async(file_path: Path, language: str, force_ocr: bool) -> str:
    client = ToolboxOcrClient()
    try:
        result = await client.ocr(file_path=file_path, language=language, force_ocr=force_ocr)
        doc = result.get("document", {})
        text = doc.get("full_text", "")
        count = doc.get("item_count", 0)
        logger.info("Toolbox OCR: {} itens, {} chars", count, len(text))
        return text
    finally:
        await client.close()