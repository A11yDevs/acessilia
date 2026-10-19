"""Core-side access to the Acessilia Toolbox.

The transport, the capability registry and the per-capability clients live in
the SDK (``libs/sdk``, package ``acessilia_sdk``). This module builds those
clients from the core's ``settings`` (:func:`make_toolbox_client`) and keeps
the names other modules import from here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypeVar

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
from acessilia_sdk.toolbox import (
    ToolboxCapabilityClient,
    ToolboxEndpoint,
    ToolboxUnavailable,
    parse_endpoints,
)
from acessilia_sdk.toolbox.clients import ToolboxMathClient, ToolboxPdfUaClient
from acessilia_sdk.toolbox.transport import media_type_for as _media_type
from acessilia_sdk.toolbox.transport import raise_for_error as _raise_for_error
from backend.config.settings import settings
from backend.tools.logger import logger


ClientT = TypeVar("ClientT", bound=ToolboxCapabilityClient)


def toolbox_endpoints() -> tuple[ToolboxEndpoint, ...]:
    """The Toolbox endpoints configured for the capability clients.

    ``TOOLBOX_BASE_URLS`` lists independent deployments, tried in order;
    without it, ``TOOLBOX_BASE_URL`` is the only endpoint (docs/adr/0006).
    """
    base_urls = settings.toolbox_base_urls.strip()
    return parse_endpoints(base_urls or settings.toolbox_base_url)


def _log_failover(endpoint: ToolboxEndpoint, error: ToolboxError) -> None:
    logger.warning(
        "Toolbox endpoint {} failed ({}: {}); trying the next one",
        endpoint.base_url,
        type(error).__name__,
        error,
    )


def _class_defaults(client_cls: type[ToolboxCapabilityClient]) -> dict[str, Any]:
    """Settings that only some clients take."""
    if issubclass(client_cls, ToolboxMathClient):
        return {"transform_provider": settings.toolbox_math_provider}
    if issubclass(client_cls, ToolboxPdfUaClient):
        # The shared Toolbox timeout (default one hour) is far too long for
        # an export that renders in seconds.
        return {"timeout_seconds": settings.toolbox_pdf_ua_timeout_seconds}
    return {}


def make_toolbox_client(client_cls: type[ClientT], **overrides: Any) -> ClientT:
    """Build an SDK capability client configured from the core's ``settings``.

    The provider comes from the ``settings`` attribute named by the class's
    ``provider_key``, so ``TOOLBOX_*_PROVIDER`` overrides keep working.
    ``overrides`` win over settings; ``None`` values are ignored, and passing
    ``base_url`` replaces the configured endpoints.
    """
    kwargs: dict[str, Any] = {
        "endpoints": toolbox_endpoints(),
        "provider": getattr(settings, client_cls.provider_key),
        "timeout_seconds": settings.toolbox_timeout_seconds,
        "api_key": settings.toolbox_api_key,
        "on_failover": _log_failover,
        **_class_defaults(client_cls),
    }
    overrides = {key: value for key, value in overrides.items() if value is not None}
    if "base_url" in overrides:
        kwargs.pop("endpoints")
    kwargs.update(overrides)
    return client_cls(**kwargs)


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
    "ToolboxUnavailable",
    "ToolboxUnsupportedMediaType",
    "auth_headers",
    "execute_capability",
    "make_toolbox_client",
    "require_capability",
    "run_sync",
    "toolbox_endpoints",
]
