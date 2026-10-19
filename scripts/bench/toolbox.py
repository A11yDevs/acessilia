"""Synchronous access to the Toolbox for the harness: datasets and structure."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from acessilia_sdk.toolbox.clients import ToolboxDatasetClient, ToolboxStructureClient

from backend.tools.toolbox_client import make_toolbox_client, run_sync

# The Toolbox caps a listing page at 1000 items.
PAGE_SIZE = 1000


async def _with_dataset_client(call):
    client = make_toolbox_client(ToolboxDatasetClient)
    try:
        return await call(client)
    finally:
        await client.close()


def list_items(dataset_id: str, split: str, limit: int | None = None) -> list[dict[str, Any]]:
    """Every item of a split (paged), or the first ``limit``."""
    items: list[dict[str, Any]] = []
    while limit is None or len(items) < limit:
        size = PAGE_SIZE if limit is None else min(PAGE_SIZE, limit - len(items))
        batch = run_sync(_with_dataset_client(
            lambda c: c.list_items(dataset_id, split, limit=size, offset=len(items))
        ))
        items.extend(batch)
        if len(batch) < size:
            break
    return items


def get_item(dataset_id: str, split: str, item_id: str) -> dict[str, Any]:
    return run_sync(_with_dataset_client(lambda c: c.get_item(dataset_id, split, item_id)))


def get_artifact(dataset_id: str, split: str, item_id: str, path: str) -> bytes:
    return run_sync(_with_dataset_client(
        lambda c: c.get_dataset_artifact(dataset_id, split, item_id, path)
    ))


def extract_structure(image_path: Path, provider: str | None = None) -> dict[str, Any]:
    """``document.structure.extract`` on one page image (``structured-document@1``)."""

    async def _call():
        client = make_toolbox_client(ToolboxStructureClient, provider=provider)
        try:
            return await client.extract_structure(file_path=image_path)
        finally:
            await client.close()

    return run_sync(_call())
