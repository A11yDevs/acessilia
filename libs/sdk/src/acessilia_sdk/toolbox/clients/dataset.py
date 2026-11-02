"""Client for the dataset routes (``/v1/datasets``), used by benchmark runs."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from acessilia_sdk.toolbox.client import ToolboxCapabilityClient
from acessilia_sdk.toolbox.errors import ToolboxContractViolation

LIST_CAPABILITY = "dataset.list"
DESCRIBE_CAPABILITY = "dataset.describe"
LIST_SPLITS_CAPABILITY = "dataset.list_splits"
LIST_ITEMS_CAPABILITY = "dataset.list_items"
GET_ITEM_CAPABILITY = "dataset.get_item"
GET_ARTIFACT_CAPABILITY = "dataset.get_artifact"
SAMPLE_CAPABILITY = "dataset.sample"
SYNC_CAPABILITY = "dataset.sync"

#: ``dataset.sync`` re-mirrors whole datasets; it gets at least this timeout.
SYNC_MIN_TIMEOUT_SECONDS = 1800


class ToolboxDatasetClient(ToolboxCapabilityClient):
    """Datasets mirrored by the Toolbox: listing, items, artifacts, samples."""

    async def list_datasets(self) -> list[dict[str, Any]]:
        """``GET /v1/datasets``."""
        return await self._json("GET", "/v1/datasets", LIST_CAPABILITY)

    async def describe_dataset(
        self, dataset_id: str, revision: str | None = None
    ) -> dict[str, Any]:
        """``GET /v1/datasets/{dataset_id}``."""
        return await self._json(
            "GET", f"/v1/datasets/{dataset_id}", DESCRIBE_CAPABILITY, _revision(revision)
        )

    async def list_splits(
        self, dataset_id: str, revision: str | None = None
    ) -> list[dict[str, Any]]:
        """``GET /v1/datasets/{dataset_id}/splits``."""
        return await self._json(
            "GET",
            f"/v1/datasets/{dataset_id}/splits",
            LIST_SPLITS_CAPABILITY,
            _revision(revision),
        )

    async def list_items(
        self,
        dataset_id: str,
        split: str,
        revision: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """``GET /v1/datasets/{dataset_id}/splits/{split}/items``, paginated."""
        return await self._json(
            "GET",
            f"/v1/datasets/{dataset_id}/splits/{split}/items",
            LIST_ITEMS_CAPABILITY,
            {"limit": limit, "offset": offset, **_revision(revision)},
        )

    async def get_item(
        self,
        dataset_id: str,
        split: str,
        item_id: str,
        revision: str | None = None,
    ) -> dict[str, Any]:
        """``GET /v1/datasets/{dataset_id}/splits/{split}/items/{item_id}``."""
        return await self._json(
            "GET",
            f"/v1/datasets/{dataset_id}/splits/{split}/items/{item_id}",
            GET_ITEM_CAPABILITY,
            _revision(revision),
        )

    async def get_dataset_artifact(
        self,
        dataset_id: str,
        split: str,
        item_id: str,
        artifact_path: str,
        revision: str | None = None,
    ) -> bytes:
        """The raw bytes of an item's artifact."""
        encoded_path = quote(artifact_path, safe="/")
        _, response = await self._request_on(
            "GET",
            f"/v1/datasets/{dataset_id}/splits/{split}/items/{item_id}/artifacts/{encoded_path}",
            capability_id=GET_ARTIFACT_CAPABILITY,
            params=_revision(revision),
        )
        return response.content

    async def sample_dataset(
        self,
        dataset_id: str,
        split: str,
        revision: str | None = None,
        n: int = 5,
    ) -> list[dict[str, Any]]:
        """``GET /v1/datasets/{dataset_id}/splits/{split}/sample``."""
        return await self._json(
            "GET",
            f"/v1/datasets/{dataset_id}/splits/{split}/sample",
            SAMPLE_CAPABILITY,
            {"n": n, **_revision(revision)},
        )

    async def sync_dataset(
        self,
        dataset_id: str,
        revision: str | None = None,
        split: str | None = None,
        timeout_seconds: float | None = None,
    ) -> Any:
        """``POST /v1/datasets/{dataset_id}/sync``: re-mirror the dataset's artifacts.

        Requires mirroring enabled in the provider config. Syncing is slow, so
        it waits at least :data:`SYNC_MIN_TIMEOUT_SECONDS` unless
        ``timeout_seconds`` says otherwise. Returns the sync report.
        """
        params = _revision(revision)
        if split:
            params["split"] = split
        return await self._json(
            "POST",
            f"/v1/datasets/{dataset_id}/sync",
            SYNC_CAPABILITY,
            params,
            timeout_seconds=timeout_seconds
            or max(self.timeout_seconds, SYNC_MIN_TIMEOUT_SECONDS),
        )

    async def _json(
        self,
        method: str,
        path: str,
        capability_id: str,
        params: dict[str, Any] | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> Any:
        _, response = await self._request_on(
            method,
            path,
            capability_id=capability_id,
            params=params or None,
            timeout_seconds=timeout_seconds,
        )
        try:
            return response.json()
        except ValueError as e:
            raise ToolboxContractViolation(
                f"{capability_id} response is not valid JSON"
            ) from e


def _revision(revision: str | None) -> dict[str, Any]:
    return {"revision": revision} if revision else {}


__all__ = [
    "DESCRIBE_CAPABILITY",
    "GET_ARTIFACT_CAPABILITY",
    "GET_ITEM_CAPABILITY",
    "LIST_CAPABILITY",
    "LIST_ITEMS_CAPABILITY",
    "LIST_SPLITS_CAPABILITY",
    "SAMPLE_CAPABILITY",
    "SYNC_CAPABILITY",
    "SYNC_MIN_TIMEOUT_SECONDS",
    "ToolboxDatasetClient",
]
