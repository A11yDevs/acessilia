"""Cliente especializado para capacidades matemáticas da Toolbox.

Encapsula math.recognize (imagem → LaTeX via docling-serve),
math.convert (LaTeX ↔ MathML via pure-python) e
math.verbalize (LaTeX → texto pt-BR via pure-python).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from backend.config.settings import settings
from backend.tools.logger import logger
from backend.tools.toolbox_client import (
    ToolboxContractViolation,
    ToolboxProviderUnavailable,
    ToolboxTimeout,
    _media_type,
    _raise_for_error,
)

RECOGNIZE_CAPABILITY = "math.recognize"
CONVERT_CAPABILITY = "math.convert"
VERBALIZE_CAPABILITY = "math.verbalize"
RECOGNIZE_PATH = f"/v1/capabilities/{RECOGNIZE_CAPABILITY}:execute"
CONVERT_PATH = f"/v1/capabilities/{CONVERT_CAPABILITY}:execute"
VERBALIZE_PATH = f"/v1/capabilities/{VERBALIZE_CAPABILITY}:execute"


class ToolboxMathClient:
    """Cliente para operações matemáticas via Acessilia Toolbox.

    Encapsula as capacidades:
    - math.recognize: reconhecer fórmulas em imagens → LaTeX
    - math.convert: converter LaTeX ↔ MathML
    - math.verbalize: converter LaTeX → texto natural pt-BR
    """

    def __init__(
        self,
        base_url: str | None = None,
        provider: str | None = None,
        timeout_seconds: int | None = None,
        api_key: str | None = None,
    ) -> None:
        self.base_url = (base_url or settings.toolbox_base_url).rstrip("/")
        self.provider = provider or settings.toolbox_provider
        self.timeout_seconds = timeout_seconds or settings.toolbox_timeout_seconds
        self.api_key = api_key if api_key is not None else settings.toolbox_api_key
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout_seconds),
            headers=headers,
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

        Reconhece expressões matemáticas em imagens e retorna LaTeX.

        Args:
            file_path: Caminho para a imagem.
            artifact_id: ID do artifact previamente armazenado.
            language: Idioma para contexto (default: pt-BR).
            use_remote_cache: Se False, força re-processamento remoto.

        Returns:
            Dict com formulas (lista de {latex, confidence, page, bbox}),
            formula_count, raw_text.
        """
        if file_path is None and artifact_id is None:
            raise ValueError("Forneça file_path ou artifact_id")

        url = f"{self.base_url}{RECOGNIZE_PATH}"

        try:
            if artifact_id:
                data: dict[str, Any] = {
                    "artifact_id": artifact_id,
                    "language": language,
                    "provider": self.provider,
                }
                if use_remote_cache is False:
                    data["no_cache"] = True
                response = await self._client.post(url, data=data)
            else:
                with open(file_path, "rb") as f:
                    files = {
                        "file": (
                            file_path.name,
                            f,
                            _media_type(file_path),
                        )
                    }
                    params: dict[str, Any] = {
                        "language": language,
                        "provider": self.provider,
                    }
                    if use_remote_cache is False:
                        params["no_cache"] = True
                    response = await self._client.post(
                        url, files=files, data=params
                    )

            _raise_for_error(response, RECOGNIZE_CAPABILITY)
            result = response.json()

            if result.get("status") != "succeeded":
                raise ToolboxContractViolation(
                    f"Reconhecimento de fórmula falhou na Toolbox: "
                    f"status={result.get('status')}"
                )

            logger.info(
                "Toolbox: {} fórmula(s) reconhecida(s)",
                result.get("document", {}).get("formula_count", "?"),
            )
            return result

        except httpx.TimeoutException as e:
            raise ToolboxTimeout(
                f"Timeout ao reconhecer fórmula via Toolbox: {e}"
            ) from e
        except httpx.RequestError as e:
            raise ToolboxProviderUnavailable(
                f"Toolbox indisponível em {self.base_url}: {e}"
            ) from e

    async def convert(
        self,
        latex: str,
        *,
        direction: str = "latex-to-mathml",
    ) -> dict[str, Any]:
        """POST /v1/capabilities/math.convert:execute.

        Converte LaTeX para MathML ou vice-versa.

        Args:
            latex: Expressão LaTeX (ou MathML, se direction=mathml-to-latex).
            direction: "latex-to-mathml" (default) ou "mathml-to-latex".

        Returns:
            Dict com latex, mathml, direction.
        """
        url = f"{self.base_url}{CONVERT_PATH}"

        try:
            data: dict[str, Any] = {
                "provider": "pure-math",
                "direction": direction,
            }
            response = await self._client.post(
                url,
                content=latex.encode("utf-8"),
                headers={"Content-Type": "text/plain", **self._auth_headers},
                params=data,
            )

            _raise_for_error(response, CONVERT_CAPABILITY)
            result = response.json()

            if result.get("status") != "succeeded":
                raise ToolboxContractViolation(
                    f"Conversão de fórmula falhou na Toolbox: "
                    f"status={result.get('status')}"
                )

            logger.info(
                "Toolbox: fórmula convertida ({})",
                direction,
            )
            return result

        except httpx.TimeoutException as e:
            raise ToolboxTimeout(
                f"Timeout ao converter fórmula via Toolbox: {e}"
            ) from e
        except httpx.RequestError as e:
            raise ToolboxProviderUnavailable(
                f"Toolbox indisponível em {self.base_url}: {e}"
            ) from e

    async def verbalize(
        self,
        latex: str,
        *,
        language: str = "pt-BR",
    ) -> dict[str, Any]:
        """POST /v1/capabilities/math.verbalize:execute.

        Converte LaTeX para texto natural em português.

        Args:
            latex: Expressão LaTeX para verbalizar.
            language: Idioma da verbalização (default: pt-BR).

        Returns:
            Dict com latex, verbalized, language.
        """
        url = f"{self.base_url}{VERBALIZE_PATH}"

        try:
            data: dict[str, Any] = {
                "provider": "pure-math",
                "language": language,
            }
            response = await self._client.post(
                url,
                content=latex.encode("utf-8"),
                headers={"Content-Type": "text/plain", **self._auth_headers},
                params=data,
            )

            _raise_for_error(response, VERBALIZE_CAPABILITY)
            result = response.json()

            if result.get("status") != "succeeded":
                raise ToolboxContractViolation(
                    f"Verbalização de fórmula falhou na Toolbox: "
                    f"status={result.get('status')}"
                )

            logger.info(
                "Toolbox: fórmula verbalizada ({} caracteres)",
                len(result.get("document", {}).get("verbalized", "")),
            )
            return result

        except httpx.TimeoutException as e:
            raise ToolboxTimeout(
                f"Timeout ao verbalizar fórmula via Toolbox: {e}"
            ) from e
        except httpx.RequestError as e:
            raise ToolboxProviderUnavailable(
                f"Toolbox indisponível em {self.base_url}: {e}"
            ) from e

    async def health(self) -> dict[str, Any]:
        """Verifica se a Toolbox está operacional."""
        try:
            response = await self._client.get("/v1/health")
            _raise_for_error(response, "health")
            return response.json()
        except httpx.TimeoutException as e:
            raise ToolboxTimeout(
                f"Timeout ao verificar health da Toolbox: {e}"
            ) from e
        except httpx.RequestError as e:
            raise ToolboxProviderUnavailable(
                f"Toolbox indisponível em {self.base_url}: {e}"
            ) from e

    async def close(self) -> None:
        """Libera a conexão HTTP."""
        await self._client.aclose()

    @property
    def _auth_headers(self) -> dict[str, str]:
        if self.api_key:
            return {"Authorization": f"Bearer {self.api_key}"}
        return {}


__all__ = ["ToolboxMathClient"]