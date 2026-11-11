"""Synchronous access to the Toolbox for the harness: datasets and structure.

The harness configures its clients itself (#402): :func:`client_config` builds
the SDK's :class:`ToolboxClientConfig` from the environment (and ``.env``),
reading the same variables, with the same defaults, as the core's settings.
It needs no core settings to reach the Toolbox;
``tests/test_bench_toolbox.py`` keeps it equal to the core's configuration for
the clients used here.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from acessilia_sdk.runtime import run_sync
from acessilia_sdk.toolbox import (
    ToolboxClientConfig,
    ToolboxEndpoint,
    ToolboxError,
    make_client,
)
from acessilia_sdk.toolbox.clients import ToolboxDatasetClient, ToolboxStructureClient
from dotenv import load_dotenv

# The same .env the core's settings load; variables already set win.
load_dotenv()


def _report_failover(endpoint: ToolboxEndpoint, error: ToolboxError) -> None:
    print(
        f"[WARN] Toolbox endpoint {endpoint.base_url} failed "
        f"({type(error).__name__}: {error}); trying the next one",
        file=sys.stderr,
    )


def client_config() -> ToolboxClientConfig:
    """The harness's client configuration, read from the environment on every call.

    ``TOOLBOX_BASE_URLS`` (comma-separated, tried in order) wins over
    ``TOOLBOX_BASE_URL``; the key, timeout, retries and backoff use the core's
    variable names and defaults. ``TOOLBOX_PROVIDER``, when set and not empty,
    is the structure provider; otherwise the SDK's default applies.
    """
    env = os.environ
    base_urls = env.get("TOOLBOX_BASE_URLS", "").strip()
    provider = env.get("TOOLBOX_PROVIDER")
    return ToolboxClientConfig(
        endpoints=base_urls or env.get("TOOLBOX_BASE_URL", "http://localhost:8002"),
        api_key=env.get("TOOLBOX_API_KEY", ""),
        timeout_seconds=int(env.get("TOOLBOX_TIMEOUT_SECONDS", "3600")),
        retries=int(env.get("TOOLBOX_RETRIES", "1")),
        retry_backoff_seconds=float(env.get("TOOLBOX_RETRY_BACKOFF_SECONDS", "0.5")),
        providers={"toolbox_provider": provider} if provider else {},
        on_failover=_report_failover,
    )


async def _with_dataset_client(call):
    client = make_client(ToolboxDatasetClient, client_config())
    try:
        return await call(client)
    finally:
        await client.close()


def list_items(dataset_id: str, split: str, limit: int | None = None) -> list[dict[str, Any]]:
    """Every item of a split (paged), or the first ``limit``."""
    return run_sync(_with_dataset_client(
        lambda c: c.list_all_items(dataset_id, split, limit=limit)
    ))


def get_item(dataset_id: str, split: str, item_id: str) -> dict[str, Any]:
    return run_sync(_with_dataset_client(lambda c: c.get_item(dataset_id, split, item_id)))


def get_artifact(dataset_id: str, split: str, item_id: str, path: str) -> bytes:
    return run_sync(_with_dataset_client(
        lambda c: c.get_dataset_artifact(dataset_id, split, item_id, path)
    ))


def extract_structure(image_path: Path, provider: str | None = None) -> dict[str, Any]:
    """``document.structure.extract`` on one page image (``structured-document@1``)."""

    async def _call():
        client = make_client(ToolboxStructureClient, client_config(), provider=provider)
        try:
            return await client.extract_structure(file_path=image_path)
        finally:
            await client.close()

    return run_sync(_call())
