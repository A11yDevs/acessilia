"""Toolbox-backed math formula recognition.

Replaces the local CodeFormula + RapidOCR cascade with a remote call
to the Acessilia Toolbox math.recognize capability. Falls back to
returning empty results on failure.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from backend.tools.logger import logger
from backend.tools.toolbox_math_client import ToolboxMathClient


def _run_async(coro) -> Any:
    """Run an async coroutine from a sync context."""
    return asyncio.run(coro)


def toolbox_recognize_formula(image_bytes: bytes) -> list[dict[str, Any]]:
    """Recognize mathematical formulas in an image via Toolbox.

    Args:
        image_bytes: PNG/JPEG image bytes containing a formula.

    Returns:
        List of {latex, confidence, page, bbox} dicts, or empty list on failure.
    """
    import tempfile

    tmp = Path(tempfile.mkdtemp()) / "formula.png"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(image_bytes)
    try:
        return _run_async(_recognize_formula_async(tmp))
    except Exception as e:
        logger.warning("Toolbox Math recognize failed ({}), returning empty", e)
        return []
    finally:
        tmp.unlink(missing_ok=True)
        import shutil
        shutil.rmtree(tmp.parent, ignore_errors=True)


async def _recognize_formula_async(file_path: Path) -> list[dict[str, Any]]:
    client = ToolboxMathClient()
    try:
        result = await client.recognize(file_path=file_path)
        return result.get("document", {}).get("formulas", [])
    finally:
        await client.close()


def toolbox_convert_latex(latex: str, direction: str = "latex-to-mathml") -> str:
    """Convert LaTeX to MathML or vice-versa via Toolbox.

    Args:
        latex: LaTeX or MathML expression.
        direction: "latex-to-mathml" or "mathml-to-latex".

    Returns:
        Converted string, or empty string on failure.
    """
    try:
        return _run_async(_convert_latex_async(latex, direction))
    except Exception as e:
        logger.warning("Toolbox Math convert failed ({}), returning empty", e)
        return ""


async def _convert_latex_async(latex: str, direction: str) -> str:
    client = ToolboxMathClient()
    try:
        result = await client.convert(latex, direction=direction)
        doc = result.get("document", {})
        return doc.get("mathml", "") if direction == "latex-to-mathml" else doc.get("latex", "")
    finally:
        await client.close()


def toolbox_verbalize_latex(latex: str, language: str = "pt-BR") -> str:
    """Convert LaTeX to natural language text via Toolbox.

    Args:
        latex: LaTeX expression.
        language: Target language (default: pt-BR).

    Returns:
        Verbalized text, or empty string on failure.
    """
    try:
        return _run_async(_verbalize_latex_async(latex, language))
    except Exception as e:
        logger.warning("Toolbox Math verbalize failed ({}), returning empty", e)
        return ""


async def _verbalize_latex_async(latex: str, language: str) -> str:
    client = ToolboxMathClient()
    try:
        result = await client.verbalize(latex, language=language)
        return result.get("document", {}).get("verbalized", "")
    finally:
        await client.close()


__all__ = [
    "toolbox_recognize_formula",
    "toolbox_convert_latex",
    "toolbox_verbalize_latex",
]