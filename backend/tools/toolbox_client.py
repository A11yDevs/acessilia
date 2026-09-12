from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Literal

import httpx

from backend.config.settings import settings
from backend.tools.logger import logger


class ToolboxError(Exception):
    """Erro base para falhas de comunicação com a Acessilia Toolbox."""


class ToolboxProviderUnavailable(ToolboxError):
    """Provedor da Toolbox está offline ou não respondeu."""


class ToolboxTimeout(ToolboxError):
    """A requisição excedeu o timeout configurado."""


class ToolboxUnsupportedMediaType(ToolboxError):
    """Tipo de mídia não suportado pela capacidade solicitada."""


class ToolboxArtifactNotFound(ToolboxError):
    """Artefato requisitado não foi encontrado na Toolbox."""


class ToolboxContractViolation(ToolboxError):
    """Resposta da Toolbox violou o contrato esperado."""


class ToolboxCapabilityError(ToolboxError):
    """Capacidade inválida ou não disponível na Toolbox."""


class ToolboxAuthenticationError(ToolboxError):
    """Autenticação falhou — chave inválida ou ausente."""


class ToolboxClient:
    """Cliente HTTP para a Acessilia Toolbox (REST API na porta 8002).

    Encapsula os endpoints documentados em:
    https://github.com/A11yDevs/acessilia-toolbox/blob/main/docs/api.md
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

    async def health(self) -> dict[str, Any]:
        """GET /v1/health — verifica se a Toolbox está operacional."""
        return await self._get("/v1/health")

    async def capabilities(self) -> list[dict[str, Any]]:
        """GET /v1/capabilities — lista capacidades disponíveis."""
        data = await self._get("/v1/capabilities")
        if isinstance(data, list):
            return data
        return data.get("capabilities", [])

    async def upload_artifact(self, file_path: Path) -> str:
        """POST /v1/artifacts — faz upload de um arquivo e retorna o artifact_id."""
        url = f"{self.base_url}/v1/artifacts"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout_seconds)) as client:
                with open(file_path, "rb") as f:
                    response = await client.post(
                        url,
                        files={"file": (file_path.name, f, _media_type(file_path))},
                        headers=self._auth_headers,
                    )
                _raise_for_error(response, "artifact.store")
                data = response.json()
                artifact_id = data.get("artifact_id") or data.get("id")
                if not artifact_id:
                    raise ToolboxContractViolation(
                        "Resposta de artifact.store sem artifact_id"
                    )
                logger.info(
                    "Toolbox: artifact {} armazenado ({})",
                    artifact_id,
                    file_path.name,
                )
                return str(artifact_id)
        except httpx.TimeoutException as e:
            raise ToolboxTimeout(
                f"Timeout ao fazer upload para Toolbox: {e}"
            ) from e
        except httpx.RequestError as e:
            raise ToolboxProviderUnavailable(
                f"Toolbox indisponível em {self.base_url}: {e}"
            ) from e

    async def retrieve_artifact(self, artifact_id: str, output_path: Path) -> None:
        """GET /v1/artifacts/{id} — baixa um artefato da Toolbox."""
        url = f"{self.base_url}/v1/artifacts/{artifact_id}"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout_seconds)) as client:
                response = await client.get(url, headers=self._auth_headers)
            _raise_for_error(response, "artifact.retrieve")
            output_path.write_bytes(response.content)
            logger.info(
                "Toolbox: artifact {} recuperado -> {}",
                artifact_id,
                output_path,
            )
        except httpx.TimeoutException as e:
            raise ToolboxTimeout(
                f"Timeout ao recuperar artifact {artifact_id}: {e}"
            ) from e
        except httpx.RequestError as e:
            raise ToolboxProviderUnavailable(
                f"Toolbox indisponível em {self.base_url}: {e}"
            ) from e

    async def extract_structure(
        self,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        language: str = "pt-BR",
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """POST /v1/capabilities/document.structure.extract:execute.

        Aceita upload direto (file_path) ou referência a artifact já armazenado
        (artifact_id). Retorna o JSON completo da resposta.
        """
        if file_path is None and artifact_id is None:
            raise ValueError("Forneça file_path ou artifact_id")

        use_cache = (
            use_remote_cache
            if use_remote_cache is not None
            else settings.toolbox_use_remote_cache
        )

        url = f"{self.base_url}/v1/capabilities/document.structure.extract:execute"

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout_seconds)) as client:
                if artifact_id:
                    data = {
                        "artifact_id": artifact_id,
                        "language": language,
                        "provider": self.provider,
                    }
                    if not use_cache:
                        data["no_cache"] = True
                    response = await client.post(url, data=data, headers=self._auth_headers)
                else:
                    with open(file_path, "rb") as f:
                        files = {"file": (file_path.name, f, _media_type(file_path))}
                        params: dict[str, Any] = {
                            "language": language,
                            "provider": self.provider,
                        }
                        if not use_cache:
                            params["no_cache"] = True
                        response = await client.post(url, files=files, data=params, headers=self._auth_headers)

            _raise_for_error(response, "document.structure.extract")
            result = response.json()

            if result.get("status") != "succeeded":
                raise ToolboxContractViolation(
                    f"Extração falhou na Toolbox: status={result.get('status')}"
                )

            logger.info(
                "Toolbox: extração concluída ({} ms, provider={})",
                result.get("provenance", {}).get("duration_ms", "?"),
                result.get("provider", "?"),
            )
            return result

        except httpx.TimeoutException as e:
            raise ToolboxTimeout(
                f"Timeout ao extrair documento via Toolbox: {e}"
            ) from e
        except httpx.RequestError as e:
            raise ToolboxProviderUnavailable(
                f"Toolbox indisponível em {self.base_url}: {e}"
            ) from e

    async def close(self) -> None:
        await self._client.aclose()

    @property
    def _auth_headers(self) -> dict[str, str]:
        if self.api_key:
            return {"Authorization": f"Bearer {self.api_key}"}
        return {}

    async def _get(self, path: str) -> Any:
        try:
            response = await self._client.get(path)
            _raise_for_error(response, path)
            return response.json()
        except httpx.TimeoutException as e:
            raise ToolboxTimeout(f"Timeout em GET {path}: {e}") from e
        except httpx.RequestError as e:
            raise ToolboxProviderUnavailable(
                f"Toolbox indisponível em {self.base_url}: {e}"
            ) from e


def _media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    mapping = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
        ".bmp": "image/bmp",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".html": "text/html",
        ".txt": "text/plain",
    }
    return mapping.get(suffix, "application/octet-stream")


def _raise_for_error(response: httpx.Response, context: str) -> None:
    """Converte códigos HTTP em exceções Toolbox específicas."""
    if response.is_success:
        return

    status = response.status_code
    try:
        body = response.json()
        detail = body.get("detail", body.get("message", ""))
    except Exception:
        detail = response.text[:500]

    if status == 503:
        raise ToolboxProviderUnavailable(
            f"Provedor indisponível ({context}): {detail}"
        )
    if status == 504:
        raise ToolboxTimeout(
            f"Timeout do provedor ({context}): {detail}"
        )
    if status == 415:
        raise ToolboxUnsupportedMediaType(
            f"Tipo de mídia não suportado ({context}): {detail}"
        )
    if status == 404:
        raise ToolboxArtifactNotFound(
            f"Artefato não encontrado ({context}): {detail}"
        )
    if status == 422:
        raise ToolboxContractViolation(
            f"Requisição inválida ({context}): {detail}"
        )
    if status == 400:
        raise ToolboxCapabilityError(
            f"Capacidade inválida ({context}): {detail}"
        )
    if status == 401:
        raise ToolboxAuthenticationError(
            f"Autenticação falhou ({context}): {detail}"
        )

    raise ToolboxError(
        f"Erro HTTP {status} na Toolbox ({context}): {detail}"
    )