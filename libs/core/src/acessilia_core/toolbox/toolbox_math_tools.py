"""Toolbox-backed math: recognition, LaTeX/MathML conversion and speech.

``math.recognize`` replaces the local CodeFormula + RapidOCR cascade and
returns no formulas when nothing is recognized; callers that batch many crops
can ask for an explicit ``MathCapabilityUnavailable`` instead. ``math.convert``
and ``math.verbalize`` are the only source of MathML and spoken text in the
core (ADR-0007): an unavailable capability raises ``MathCapabilityUnavailable``
instead of falling back to a local converter.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from acessilia_core.config import ToolboxConfig
from acessilia_core.logger import logger
from acessilia_core.toolbox.toolbox_client import make_toolbox_client
from acessilia_sdk.operations.formula import (
    convert_formula,
    recognize_formula,
    verbalize_formula,
)
from acessilia_sdk.runtime import run_sync
from acessilia_sdk.toolbox import ToolboxError, ToolboxInvalidInput
from acessilia_sdk.toolbox.clients import ToolboxMathClient
from acessilia_sdk.toolbox.clients.math import (
    CONVERT_CAPABILITY,
    RECOGNIZE_CAPABILITY,
    VERBALIZE_CAPABILITY,
)

T = TypeVar("T")


async def _with_math_client(
    toolbox: ToolboxConfig, call: Callable[[ToolboxMathClient], Awaitable[T]]
) -> T:
    client = make_toolbox_client(ToolboxMathClient, toolbox)
    try:
        return await call(client)
    finally:
        await client.close()


def toolbox_recognize_formula(
    image_bytes: bytes, *, toolbox: ToolboxConfig, raise_on_unavailable: bool = False
) -> list[dict[str, Any]]:
    """Recognize mathematical formulas in an image: the SDK's ``recognize_formula``.

    Args:
        image_bytes: PNG/JPEG image bytes containing a formula.
        toolbox: The run's Toolbox configuration.
        raise_on_unavailable: Raise ``MathCapabilityUnavailable`` when the
            capability cannot serve the request, instead of returning an empty
            list. Callers processing many crops use it to stop after one
            outage instead of paying the timeout once per crop.

    Returns:
        The LaTeX candidates, best first (``ranked_latex_candidates``): each
        with a non-empty ``latex`` without delimiters, a ``confidence`` that
        is a finite number or ``None``, and the ``page`` and ``bbox`` the
        provider reported; empty when no formula was recognized or the image
        was rejected.

    Raises:
        MathCapabilityUnavailable: the capability could not serve the request
            and ``raise_on_unavailable`` is true.

    Only Toolbox errors are handled here. Anything else, such as an unusable
    endpoint configuration or a bug, propagates: turning it into "no formula"
    would hide it (P6).
    """
    try:
        return run_sync(_recognize_formula_async(image_bytes, toolbox))
    except ToolboxInvalidInput as exc:
        logger.info("{} rejected the image ({})", RECOGNIZE_CAPABILITY, exc)
        return []
    except ToolboxError as exc:
        if raise_on_unavailable:
            raise MathCapabilityUnavailable(RECOGNIZE_CAPABILITY, exc) from exc
        logger.warning("Toolbox Math recognize failed ({}), returning empty", exc)
        return []


async def _recognize_formula_async(
    image_bytes: bytes, toolbox: ToolboxConfig
) -> list[dict[str, Any]]:
    return (
        await _with_math_client(
            toolbox, lambda client: recognize_formula(client, image_bytes)
        )
    ).candidates


class MathCapabilityUnavailable(RuntimeError):
    """``math.convert`` or ``math.verbalize`` could not serve a request.

    Raised for an unreachable, failing or misconfigured Toolbox, or for an
    answer outside the contract (``reason`` ``ToolboxContractViolation``: a
    broken provider, not a formula without that text), never for an
    expression the Toolbox rejected. ADR-0007 forbids a silent local fallback:
    the caller decides between failing, replanning and a documented
    degradation. ``reason`` is the SDK error class, safe to show; the message
    may carry Toolbox details and is meant for logs.
    """

    def __init__(self, capability: str, error: ToolboxError) -> None:
        super().__init__(f"{capability}: {type(error).__name__}: {error}")
        self.capability = capability
        self.reason = type(error).__name__


#: Technical warning and method message when math.convert is unavailable.
MSG_MATHML_UNAVAILABLE: str = "math.convert unavailable ({reason}): formulas kept without MathML"
#: Technical warning and method message when math.verbalize is unavailable.
MSG_SPEECH_UNAVAILABLE: str = (
    "math.verbalize unavailable ({reason}): formulas kept without spoken text"
)
#: Technical warning when math.convert rejected the LaTeX of some formulas.
MSG_MATHML_REJECTED: str = (
    "math.convert rejected the LaTeX of {count} formula(s): kept without MathML"
)
#: Technical warning when math.verbalize rejected the LaTeX of some formulas.
MSG_SPEECH_REJECTED: str = (
    "math.verbalize rejected the LaTeX of {count} formula(s): kept without spoken text"
)


def toolbox_convert_latex(
    latex: str, direction: str = "latex-to-mathml", *, toolbox: ToolboxConfig
) -> str:
    """Convert LaTeX to MathML (or MathML to LaTeX): the SDK's ``convert_formula``.

    Args:
        latex: LaTeX expression, or MathML for ``mathml-to-latex``.
        direction: ``latex-to-mathml`` or ``mathml-to-latex``.
        toolbox: The run's Toolbox configuration.

    Returns:
        The converted expression, or ``""`` when the Toolbox rejected the
        input as invalid (a formula without MathML, not a failure).

    Raises:
        MathCapabilityUnavailable: the capability could not serve the request.
    """
    try:
        return run_sync(_convert_latex_async(latex, direction, toolbox))
    except ToolboxInvalidInput as exc:
        logger.info("{} rejected the input ({}): {!r}", CONVERT_CAPABILITY, exc, latex)
        return ""
    except ToolboxError as exc:
        raise MathCapabilityUnavailable(CONVERT_CAPABILITY, exc) from exc


async def _convert_latex_async(latex: str, direction: str, toolbox: ToolboxConfig) -> str:
    return (
        await _with_math_client(
            toolbox,
            lambda client: convert_formula(client, latex, direction=direction),
        )
    ).text


def toolbox_verbalize_latex(
    latex: str, language: str = "pt-BR", *, toolbox: ToolboxConfig
) -> str:
    """Speak a LaTeX expression (pt-BR): the SDK's ``verbalize_formula``.

    Args:
        latex: LaTeX expression.
        language: Target language; ``math.verbalize@1`` speaks pt-BR only.
        toolbox: The run's Toolbox configuration.

    Returns:
        The spoken text, or ``""`` when the Toolbox rejected the input.

    Raises:
        MathCapabilityUnavailable: the capability could not serve the request.
    """
    try:
        return run_sync(_verbalize_latex_async(latex, language, toolbox))
    except ToolboxInvalidInput as exc:
        logger.info("{} rejected the input ({}): {!r}", VERBALIZE_CAPABILITY, exc, latex)
        return ""
    except ToolboxError as exc:
        raise MathCapabilityUnavailable(VERBALIZE_CAPABILITY, exc) from exc


async def _verbalize_latex_async(latex: str, language: str, toolbox: ToolboxConfig) -> str:
    return (
        await _with_math_client(
            toolbox,
            lambda client: verbalize_formula(client, latex, language=language),
        )
    ).text


__all__ = [
    "MSG_MATHML_REJECTED",
    "MSG_MATHML_UNAVAILABLE",
    "MSG_SPEECH_REJECTED",
    "MSG_SPEECH_UNAVAILABLE",
    "MathCapabilityUnavailable",
    "toolbox_recognize_formula",
    "toolbox_convert_latex",
    "toolbox_verbalize_latex",
]