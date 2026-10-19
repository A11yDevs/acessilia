"""Toolbox-backed OCR text extraction.

Replaces local tesseract/rapidocr with a remote call to the Acessilia
Toolbox document.ocr capability. Falls back to empty string on failure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.tools.logger import logger
from acessilia_sdk.toolbox.clients import ToolboxOcrClient
from backend.tools.toolbox_client import make_toolbox_client, run_sync


def _run_async(coro) -> Any:
    """Run an async coroutine from a sync context, even inside a running loop."""
    return run_sync(coro)


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
        logger.warning("Toolbox OCR failed ({}), returning empty", e)
        return ""


async def _ocr_async(file_path: Path, language: str, force_ocr: bool) -> str:
    client = make_toolbox_client(ToolboxOcrClient)
    try:
        result = await client.ocr(
            file_path=file_path, language=language, force_ocr=force_ocr
        )
        doc = result.get("document", {})
        text = doc.get("full_text", "")
        count = doc.get("item_count", 0)
        logger.info("Toolbox OCR: {} items, {} chars", count, len(text))
        return text
    finally:
        await client.close()


__all__ = ["toolbox_ocr_text"]