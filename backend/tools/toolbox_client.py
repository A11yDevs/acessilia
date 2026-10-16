"""Core-side access to the Acessilia Toolbox.

The transport, the capability registry and the client base class live in the
SDK (``libs/sdk``, package ``acessilia_sdk``); this module binds them to the
core's ``settings`` and keeps the names other modules import from here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from acessilia_sdk.runtime import run_sync
from acessilia_sdk.toolbox import (
    ToolboxArtifactNotFound,
    ToolboxAuthenticationError,
    ToolboxCapabilityError,
    ToolboxContractViolation,
    ToolboxError,
    ToolboxProviderUnavailable,
    ToolboxTimeout,
    ToolboxUnsupportedMediaType,
    auth_headers,
    execute_capability,
    require_capability,
)
from acessilia_sdk.toolbox import ToolboxCapabilityClient as _SdkCapabilityClient
from acessilia_sdk.toolbox.transport import media_type_for as _media_type
from acessilia_sdk.toolbox.transport import raise_for_error as _raise_for_error
from backend.config.settings import settings
from backend.tools.logger import logger


class ToolboxCapabilityClient(_SdkCapabilityClient):
    """SDK client base with defaults taken from the core's ``settings``.

    The provider default is read from the ``settings`` attribute named by
    ``provider_key`` at construction time, so ``TOOLBOX_*_PROVIDER`` overrides
    keep working.
    """

    def __init__(
        self,
        base_url: str | None = None,
        provider: str | None = None,
        timeout_seconds: int | None = None,
        api_key: str | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url or settings.toolbox_base_url,
            provider=provider or getattr(settings, self.provider_key),
            timeout_seconds=timeout_seconds or settings.toolbox_timeout_seconds,
            api_key=api_key if api_key is not None else settings.toolbox_api_key,
        )


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
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout_seconds),
            headers=auth_headers(self.api_key),
        )

    async def execute(
        self,
        capability_id: str,
        *,
        provider: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute any capability registered in ``TOOLBOX_CAPABILITIES``.

        Accepts the keyword arguments of :func:`execute_capability`. A fresh
        connection is opened per call so the client can be shared by code that
        runs each extraction on its own event loop.
        """
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout_seconds),
            headers=auth_headers(self.api_key),
        ) as http:
            return await execute_capability(
                http,
                capability_id,
                provider=provider or self.provider,
                **kwargs,
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
        use_cache = (
            use_remote_cache
            if use_remote_cache is not None
            else settings.toolbox_use_remote_cache
        )
        result = await self.execute(
            "document.structure.extract",
            file_path=file_path,
            artifact_id=artifact_id,
            language=language,
            no_cache=not use_cache,
        )
        logger.info(
            "Toolbox: extração concluída ({} ms, provider={})",
            result.get("provenance", {}).get("duration_ms", "?"),
            result.get("provider", "?"),
        )
        return result

    async def close(self) -> None:
        await self._client.aclose()

    # ── Dataset capabilities ────────────────────────────────────────────

    async def list_datasets(self) -> list[dict[str, Any]]:
        """GET /v1/datasets — list all datasets available through the toolbox."""
        return await self._get("/v1/datasets")

    async def sync_dataset(
        self,
        dataset_id: str,
        revision: str | None = None,
        split: str | None = None,
        timeout_seconds: int | None = None,
    ) -> Any:
        """POST /v1/datasets/{dataset_id}/sync — re-mirror dataset artifacts.

        Re-mirrors all artifacts of the dataset (or a single split) to the
        local artifact store. Requires mirroring enabled in the provider
        config (``dataset-huggingface`` has ``mirror: true``).

        Args:
            dataset_id: The dataset identifier (e.g. ``dr-docbench``).
            revision: Optional Git/HF revision to pin.
            split: Optional split name to sync only that split.
            timeout_seconds: Optional longer timeout (sync can be slow).

        Returns:
            The sync report (list of mirrored artifacts).
        """
        url = f"{self.base_url}/v1/datasets/{dataset_id}/sync"
        params: dict[str, Any] = {}
        if revision:
            params["revision"] = revision
        if split:
            params["split"] = split
        timeout = timeout_seconds or max(self.timeout_seconds, 1800)
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
                response = await client.post(url, params=params, headers=self._auth_headers)
            _raise_for_error(response, "dataset.sync")
            result = response.json()
            logger.info("Toolbox: dataset {} sincronizado", dataset_id)
            return result
        except httpx.TimeoutException as e:
            raise ToolboxTimeout(
                f"Timeout ao sincronizar dataset {dataset_id}: {e}"
            ) from e
        except httpx.RequestError as e:
            raise ToolboxProviderUnavailable(
                f"Toolbox indisponível em {self.base_url}: {e}"
            ) from e

    async def describe_dataset(
        self, dataset_id: str, revision: str | None = None
    ) -> dict[str, Any]:
        """GET /v1/datasets/{dataset_id} — get detailed metadata about a dataset."""
        params = {}
        if revision:
            params["revision"] = revision
        return await self._get(f"/v1/datasets/{dataset_id}", params=params)

    async def list_splits(
        self, dataset_id: str, revision: str | None = None
    ) -> list[dict[str, Any]]:
        """GET /v1/datasets/{dataset_id}/splits — list available splits."""
        params = {}
        if revision:
            params["revision"] = revision
        return await self._get(f"/v1/datasets/{dataset_id}/splits", params=params)

    async def list_items(
        self,
        dataset_id: str,
        split: str,
        revision: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """GET /v1/datasets/{dataset_id}/splits/{split}/items — list items with pagination."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if revision:
            params["revision"] = revision
        return await self._get(
            f"/v1/datasets/{dataset_id}/splits/{split}/items",
            params=params,
        )

    async def get_item(
        self,
        dataset_id: str,
        split: str,
        item_id: str,
        revision: str | None = None,
    ) -> dict[str, Any]:
        """GET /v1/datasets/{dataset_id}/splits/{split}/items/{item_id} — get a full item."""
        params = {}
        if revision:
            params["revision"] = revision
        return await self._get(
            f"/v1/datasets/{dataset_id}/splits/{split}/items/{item_id}",
            params=params,
        )

    async def get_dataset_artifact(
        self,
        dataset_id: str,
        split: str,
        item_id: str,
        artifact_path: str,
        revision: str | None = None,
    ) -> bytes:
        """GET /v1/datasets/{dataset_id}/splits/{split}/items/{item_id}/artifacts/{path}
        — retrieve the raw bytes of a dataset artifact."""
        params = {}
        if revision:
            params["revision"] = revision
        url = f"{self.base_url}/v1/datasets/{dataset_id}/splits/{split}/items/{item_id}/artifacts/{artifact_path}"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout_seconds)) as client:
                response = await client.get(url, headers=self._auth_headers, params=params)
            _raise_for_error(response, "dataset.get_artifact")
            return response.content
        except httpx.TimeoutException as e:
            raise ToolboxTimeout(f"Timeout ao baixar artifact de dataset: {e}") from e
        except httpx.RequestError as e:
            raise ToolboxProviderUnavailable(
                f"Toolbox indisponível em {self.base_url}: {e}"
            ) from e

    async def sample_dataset(
        self,
        dataset_id: str,
        split: str,
        revision: str | None = None,
        n: int = 5,
    ) -> list[dict[str, Any]]:
        """GET /v1/datasets/{dataset_id}/splits/{split}/sample — get a random sample of items."""
        params: dict[str, Any] = {"n": n}
        if revision:
            params["revision"] = revision
        return await self._get(
            f"/v1/datasets/{dataset_id}/splits/{split}/sample",
            params=params,
        )

    @property
    def _auth_headers(self) -> dict[str, str]:
        return auth_headers(self.api_key)

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            response = await self._client.get(path, params=params)
            _raise_for_error(response, path)
            return response.json()
        except httpx.TimeoutException as e:
            raise ToolboxTimeout(f"Timeout em GET {path}: {e}") from e
        except httpx.RequestError as e:
            raise ToolboxProviderUnavailable(
                f"Toolbox indisponível em {self.base_url}: {e}"
            ) from e


__all__ = [
    "ToolboxArtifactNotFound",
    "ToolboxAuthenticationError",
    "ToolboxCapabilityClient",
    "ToolboxCapabilityError",
    "ToolboxClient",
    "ToolboxContractViolation",
    "ToolboxError",
    "ToolboxProviderUnavailable",
    "ToolboxTimeout",
    "ToolboxUnsupportedMediaType",
    "auth_headers",
    "execute_capability",
    "require_capability",
    "run_sync",
]
