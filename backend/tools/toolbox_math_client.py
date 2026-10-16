"""Cliente especializado para capacidades matemáticas da Toolbox.

Encapsula math.recognize (imagem → LaTeX via docling-serve),
math.convert (LaTeX ↔ MathML via pure-python) e
math.verbalize (LaTeX → texto pt-BR via pure-python).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.config.settings import settings
from backend.tools.logger import logger
from backend.tools.toolbox_client import ToolboxCapabilityClient

RECOGNIZE_CAPABILITY = "math.recognize"
CONVERT_CAPABILITY = "math.convert"
VERBALIZE_CAPABILITY = "math.verbalize"


def _latex_upload(latex: str) -> tuple[str, bytes, str]:
    return ("formula.tex", latex.encode("utf-8"), "text/plain")


class ToolboxMathClient(ToolboxCapabilityClient):
    """Cliente para operações matemáticas via Acessilia Toolbox.

    Encapsula as capacidades:
    - math.recognize: reconhecer fórmulas em imagens → LaTeX
    - math.convert: converter LaTeX ↔ MathML
    - math.verbalize: converter LaTeX → texto natural pt-BR
    """

    # provider remains the recognition-provider override for backward
    # compatibility. Text transformations use the pure-math provider.
    provider_key = "toolbox_math_recognize_provider"

    def __init__(
        self,
        base_url: str | None = None,
        provider: str | None = None,
        transform_provider: str | None = None,
        timeout_seconds: int | None = None,
        api_key: str | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            provider=provider,
            timeout_seconds=timeout_seconds,
            api_key=api_key,
        )
        self.transform_provider = (
            transform_provider or settings.toolbox_math_provider
        )

    async def recognize(
        self,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        language: str = "pt-BR",
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """POST /v1/capabilities/math.recognize:execute.

        Args:
            file_path: Caminho para a imagem.
            artifact_id: ID do artifact previamente armazenado.
            language: Idioma para contexto (default: pt-BR).
            use_remote_cache: Se False, força re-processamento remoto.

        Returns:
            Dict com formulas (lista de {latex, confidence, page, bbox}),
            formula_count, raw_text.
        """
        result = await self._execute(
            RECOGNIZE_CAPABILITY,
            file_path=file_path,
            artifact_id=artifact_id,
            language=language,
            no_cache=use_remote_cache is False,
        )
        logger.info(
            "Toolbox: {} fórmula(s) reconhecida(s)",
            result.get("document", {}).get("formula_count", "?"),
        )
        return result

    async def convert(
        self,
        latex: str,
        *,
        direction: str = "latex-to-mathml",
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """POST /v1/capabilities/math.convert:execute.

        O LaTeX é enviado como arquivo text/plain em um formulário multipart.

        Args:
            latex: Expressão LaTeX (ou MathML, se direction=mathml-to-latex).
            direction: "latex-to-mathml" (default) ou "mathml-to-latex".
            use_remote_cache: Se False, força re-processamento remoto.

        Returns:
            Dict com latex, mathml, direction.
        """
        result = await self._execute(
            CONVERT_CAPABILITY,
            provider=self.transform_provider,
            upload=_latex_upload(latex),
            parameters={"direction": direction},
            no_cache=use_remote_cache is False,
        )
        logger.info("Toolbox: fórmula convertida ({})", direction)
        return result

    async def verbalize(
        self,
        latex: str,
        *,
        language: str = "pt-BR",
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """POST /v1/capabilities/math.verbalize:execute.

        O LaTeX é enviado como arquivo text/plain em um formulário multipart;
        provider e language são campos do mesmo formulário.

        Args:
            latex: Expressão LaTeX para verbalizar.
            language: Idioma da verbalização (default: pt-BR).
            use_remote_cache: Se False, força re-processamento remoto.

        Returns:
            Dict com latex, verbalized, language.
        """
        result = await self._execute(
            VERBALIZE_CAPABILITY,
            provider=self.transform_provider,
            upload=_latex_upload(latex),
            language=language,
            no_cache=use_remote_cache is False,
        )
        logger.info(
            "Toolbox: fórmula verbalizada ({} caracteres)",
            len(result.get("document", {}).get("verbalized", "")),
        )
        return result


__all__ = ["ToolboxMathClient"]
