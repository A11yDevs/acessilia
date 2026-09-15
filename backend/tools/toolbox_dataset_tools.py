"""Toolbox-backed dataset access for Dr.DocBench benchmark runs.

Thin synchronous wrappers over ToolboxClient dataset endpoints, following
the same pattern as toolbox_ocr_tools.py. Provides page-image retrieval and
ground-truth (markdown/OmniDocJSON) access for the ``dr-docbench`` dataset.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from backend.tools.logger import logger
from backend.tools.toolbox_client import ToolboxClient, ToolboxError

DATASET_ID = "dr-docbench"


def _run_async(coro) -> Any:
    """Run an async coroutine from a sync context."""
    return asyncio.run(coro)


def toolbox_list_drbench_items(
    split: str = "dev",
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List Dr.DocBench items (1 page per item) in the given split."""
    try:
        return _run_async(_list_items_async(DATASET_ID, split, limit, offset))
    except ToolboxError as e:
        logger.warning("Toolbox list_items failed: {}", e)
        return []


def toolbox_get_drbench_item(
    item_id: str,
    split: str = "dev",
) -> dict[str, Any] | None:
    """Get a full Dr.DocBench item (artifact refs + annotations)."""
    try:
        return _run_async(_get_item_async(DATASET_ID, split, item_id))
    except ToolboxError as e:
        logger.warning("Toolbox get_item({}) failed: {}", item_id, e)
        return None


def toolbox_get_drbench_page_image(
    item_id: str,
    artifact_path: str,
    split: str = "dev",
) -> bytes | None:
    """Download the raw page image bytes for a Dr.DocBench item."""
    try:
        return _run_async(
            _get_artifact_async(DATASET_ID, split, item_id, artifact_path)
        )
    except ToolboxError as e:
        logger.warning("Toolbox get_artifact({}) failed: {}", artifact_path, e)
        return None


def toolbox_get_drbench_ground_truth(
    item_id: str,
    md_path: str,
    split: str = "dev",
) -> bytes | None:
    """Download the ground-truth markdown for a dev-split item."""
    return toolbox_get_drbench_page_image(
        item_id, md_path, split=split
    )


def download_drbench_page(
    item_id: str,
    split: str = "dev",
    output_dir: Path | None = None,
) -> Path | None:
    """Fetch a Dr.DocBench item and save its page image locally.

    Returns the path of the saved image, or None on failure.
    """
    item = toolbox_get_drbench_item(item_id, split=split)
    if item is None:
        return None

    image_ref = _find_image_artifact(item)
    if image_ref is None:
        logger.warning("No image artifact found for item {}", item_id)
        return None

    data = toolbox_get_drbench_page_image(item_id, image_ref["path"], split=split)
    if data is None:
        return None

    out_dir = output_dir or (Path(__file__).resolve().parents[2] / "var" / "drbench" / split)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{item_id}_{Path(image_ref['path']).name}"
    out_path.write_bytes(data)
    logger.info("Saved page image to {}", out_path)
    return out_path


def _find_image_artifact(item: dict[str, Any]) -> dict[str, Any] | None:
    """Locate the page-image artifact ref within a dataset item."""
    for ref in item.get("artifacts", []):
        media = str(ref.get("media_type", ""))
        if media.startswith("image/"):
            return ref
    return None


async def _list_items_async(
    dataset_id: str, split: str, limit: int, offset: int
) -> list[dict[str, Any]]:
    client = ToolboxClient()
    try:
        return await client.list_items(dataset_id, split, limit=limit, offset=offset)
    finally:
        await client.close()


async def _get_item_async(dataset_id: str, split: str, item_id: str) -> dict[str, Any]:
    client = ToolboxClient()
    try:
        return await client.get_item(dataset_id, split, item_id)
    finally:
        await client.close()


async def _get_artifact_async(
    dataset_id: str, split: str, item_id: str, artifact_path: str
) -> bytes:
    client = ToolboxClient()
    try:
        return await client.get_dataset_artifact(
            dataset_id, split, item_id, artifact_path
        )
    finally:
        await client.close()


__all__ = [
    "DATASET_ID",
    "toolbox_list_drbench_items",
    "toolbox_get_drbench_item",
    "toolbox_get_drbench_page_image",
    "toolbox_get_drbench_ground_truth",
    "download_drbench_page",
]
