"""Client for ``math.recognize``, ``math.convert`` and ``math.verbalize``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from acessilia_sdk.toolbox.capabilities import provider_default
from acessilia_sdk.toolbox.client import ToolboxCapabilityClient

RECOGNIZE_CAPABILITY = "math.recognize"
CONVERT_CAPABILITY = "math.convert"
VERBALIZE_CAPABILITY = "math.verbalize"


def _latex_upload(latex: str) -> tuple[str, bytes, str]:
    return ("formula.tex", latex.encode("utf-8"), "text/plain")


class ToolboxMathClient(ToolboxCapabilityClient):
    """Formulas: recognize them in images (LaTeX), convert LaTeX and MathML,
    and verbalize LaTeX as natural language.

    ``provider`` is the recognition provider. Text transformations
    (``convert``, ``verbalize``) use ``transform_provider``, by default the
    ``toolbox_math_provider`` registry default.
    """

    provider_key = "toolbox_math_recognize_provider"

    def __init__(self, *, transform_provider: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.transform_provider = transform_provider or provider_default(
            "toolbox_math_provider"
        )

    async def recognize(
        self,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        language: str = "pt-BR",
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """``POST /v1/capabilities/math.recognize:execute``.

        Returns the response envelope. Its ``document`` depends on the
        provider: ``artifact/latex@1`` (``pp-formulanet``, ``rapid-latex-ocr``)
        holds one expression, ``{latex, confidence?, bbox?}``; ``docling-math``
        holds ``formulas`` ({latex, confidence, page, bbox}), ``formula_count``
        and ``raw_text``.
        """
        return await self._execute(
            RECOGNIZE_CAPABILITY,
            file_path=file_path,
            artifact_id=artifact_id,
            language=language,
            no_cache=use_remote_cache is False,
        )

    async def convert(
        self,
        latex: str,
        *,
        direction: str = "latex-to-mathml",
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """``POST /v1/capabilities/math.convert:execute``.

        The formula is sent as a ``text/plain`` file; ``direction`` is
        ``latex-to-mathml`` or ``mathml-to-latex``. Returns the response
        envelope; its ``document`` holds ``latex``, ``mathml`` and
        ``direction``.
        """
        return await self._execute(
            CONVERT_CAPABILITY,
            provider=self.transform_provider,
            upload=_latex_upload(latex),
            parameters={"direction": direction},
            no_cache=use_remote_cache is False,
        )

    async def verbalize(
        self,
        latex: str,
        *,
        language: str = "pt-BR",
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """``POST /v1/capabilities/math.verbalize:execute``.

        The formula is sent as a ``text/plain`` file. Returns the response
        envelope; its ``document`` holds ``latex``, ``verbalized`` and
        ``language``.
        """
        return await self._execute(
            VERBALIZE_CAPABILITY,
            provider=self.transform_provider,
            upload=_latex_upload(latex),
            language=language,
            no_cache=use_remote_cache is False,
        )


__all__ = [
    "CONVERT_CAPABILITY",
    "RECOGNIZE_CAPABILITY",
    "VERBALIZE_CAPABILITY",
    "ToolboxMathClient",
]
