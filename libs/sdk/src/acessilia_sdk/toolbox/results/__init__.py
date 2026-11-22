"""Typed readers for selected, published Toolbox result documents.

Raw clients and legacy normalization helpers retain their compatibility policy.
These additive readers validate the published shape and raise the SDK's existing
ToolboxContractViolation on invalid output. Artifact verification remains in the
clients that download binary payloads.
"""

from __future__ import annotations

from typing import Any, TypeVar

from acessilia_sdk.toolbox.errors import ToolboxContractViolation
from acessilia_sdk.toolbox.results._model import ResultModel
from acessilia_sdk.toolbox.results.execute import (
    LatexResult,
    MathmlResult,
    MediaInspection,
    PageJudgement,
    PdfValidationReport,
    RegionTranscription,
    RenderedPageMetadata,
    TextSpansResult,
    VerbalizedResult,
)

T = TypeVar("T", bound=ResultModel)


def read_result(document: Any, model: type[T]) -> T:
    """Validate a result document, reporting the existing SDK contract error."""
    try:
        return model.from_dict(document)
    except ValueError as exc:
        raise ToolboxContractViolation(str(exc)) from exc


def read_document(envelope: Any, model: type[T]) -> T:
    """Validate the document in an execute response, without changing its envelope.

    Example: ``read_document(await client.verbalize(latex), VerbalizedResult)``.
    This is deliberately strict; legacy formula lists and coercible judgement
    probabilities still belong to their existing compatibility helpers.
    """
    try:
        if not isinstance(envelope, dict) or "document" not in envelope:
            raise ValueError("execute response is missing its document")
        return model.from_dict(envelope["document"])
    except ValueError as exc:
        raise ToolboxContractViolation(str(exc)) from exc


__all__ = [
    "LatexResult",
    "MathmlResult",
    "VerbalizedResult",
    "PageJudgement",
    "RegionTranscription",
    "PdfValidationReport",
    "MediaInspection",
    "RenderedPageMetadata",
    "TextSpansResult",
    "read_document",
    "read_result",
]
