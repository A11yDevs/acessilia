"""Synchronous access to the Toolbox for the harness: datasets, structure and formulas.

The harness configures its clients itself (#402): :func:`client_config` builds
the SDK's :class:`ToolboxClientConfig` from the environment (and ``.env``),
reading the same variables, with the same defaults, as the core's settings.
It needs no core settings to reach the Toolbox;
``tests/test_bench_toolbox.py`` keeps it equal to the core's configuration for
the clients used here. Formula steps call the SDK's official
``acessilia_sdk.operations.formula`` operation directly (ADR-0017, #614).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from acessilia_sdk.operations.formula import (
    FORMULA_CROP_DPI,
    FormulaChain,
    convert_formula,
    formula_chain,
    verbalize_formula,
)
from acessilia_sdk.runtime import run_sync
from acessilia_sdk.toolbox import (
    ToolboxClientConfig,
    ToolboxEndpoint,
    ToolboxError,
    make_client,
)
from acessilia_sdk.toolbox.clients import (
    ToolboxDatasetClient,
    ToolboxMathClient,
    ToolboxPdfClient,
    ToolboxStructureClient,
)
from dotenv import load_dotenv

# The same .env the core's settings load; variables already set win.
load_dotenv()

_PROVIDER_VARS: dict[str, str] = {
    "toolbox_provider": "TOOLBOX_PROVIDER",
    "toolbox_pdf_provider": "TOOLBOX_PDF_PROVIDER",
    "toolbox_math_recognize_provider": "TOOLBOX_MATH_RECOGNIZE_PROVIDER",
    "toolbox_math_provider": "TOOLBOX_MATH_PROVIDER",
}


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
    variable names and defaults. Provider variables (``TOOLBOX_PROVIDER``,
    ``TOOLBOX_PDF_PROVIDER``, ``TOOLBOX_MATH_RECOGNIZE_PROVIDER``,
    ``TOOLBOX_MATH_PROVIDER``), when set and not empty, override the SDK's
    defaults.
    """
    env = os.environ
    base_urls = env.get("TOOLBOX_BASE_URLS", "").strip()
    providers = {
        key: value for key, var in _PROVIDER_VARS.items() if (value := env.get(var))
    }
    return ToolboxClientConfig(
        endpoints=base_urls or env.get("TOOLBOX_BASE_URL", "http://localhost:8002"),
        api_key=env.get("TOOLBOX_API_KEY", ""),
        timeout_seconds=int(env.get("TOOLBOX_TIMEOUT_SECONDS", "3600")),
        retries=int(env.get("TOOLBOX_RETRIES", "1")),
        retry_backoff_seconds=float(env.get("TOOLBOX_RETRY_BACKOFF_SECONDS", "0.5")),
        providers=providers,
        timeouts={
            "toolbox_structure_timeout_seconds": int(
                env.get("TOOLBOX_STRUCTURE_TIMEOUT_SECONDS", "600")
            )
        },
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
    """``document.structure.extract`` on one page image or PDF (``structured-document@1``)."""

    async def _call():
        client = make_client(ToolboxStructureClient, client_config(), provider=provider)
        try:
            return await client.extract_structure(file_path=image_path)
        finally:
            await client.close()

    return run_sync(_call())


def convert_latex(
    latex: str,
    *,
    direction: str = "latex-to-mathml",
    transform_provider: str | None = None,
    use_remote_cache: bool | None = None,
) -> str:
    """Convert LaTeX/MathML via the SDK's ``convert_formula`` operation."""

    async def _call() -> str:
        client = make_client(
            ToolboxMathClient, client_config(), transform_provider=transform_provider
        )
        try:
            return (
                await convert_formula(
                    client, latex, direction=direction, use_remote_cache=use_remote_cache
                )
            ).text
        finally:
            await client.close()

    return run_sync(_call())


def verbalize_latex(
    latex: str,
    *,
    language: str = "pt-BR",
    transform_provider: str | None = None,
    use_remote_cache: bool | None = None,
) -> str:
    """Verbalize a LaTeX expression via the SDK's ``verbalize_formula`` operation."""

    async def _call() -> str:
        client = make_client(
            ToolboxMathClient, client_config(), transform_provider=transform_provider
        )
        try:
            return (
                await verbalize_formula(
                    client, latex, language=language, use_remote_cache=use_remote_cache
                )
            ).text
        finally:
            await client.close()

    return run_sync(_call())


def run_formula_chain(
    source: Path | None,
    *,
    page_number: int,
    box: Any,
    artifact_id: str | None = None,
    candidate: int = 1,
    dpi: int = FORMULA_CROP_DPI,
    language: str = "pt-BR",
    recognize_provider: str | None = None,
    transform_provider: str | None = None,
    use_remote_cache: bool | None = None,
) -> FormulaChain:
    """Run the SDK's ``formula_chain`` operation on one formula region."""

    async def _call() -> FormulaChain:
        config = client_config()
        pdf = make_client(ToolboxPdfClient, config)
        math = make_client(
            ToolboxMathClient,
            config,
            provider=recognize_provider,
            transform_provider=transform_provider,
        )
        try:
            return await formula_chain(
                pdf,
                math,
                source,
                artifact_id=artifact_id,
                page_number=page_number,
                box=box,
                candidate=candidate,
                dpi=dpi,
                language=language,
                use_remote_cache=use_remote_cache,
            )
        finally:
            await pdf.close()
            await math.close()

    return run_sync(_call())
