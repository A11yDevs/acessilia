"""Multi-provider fusion adapter binding ``ToolboxConfig`` and logging to SDK/docstruct.

Dual-provider structure extraction runs through
:func:`acessilia_sdk.operations.fusion.extract_dual_fused` and pure payload
fusion / page routing through :mod:`docstruct.fusion.payload` (#612, ADR-0002,
ADR-0017). The core owns ``ToolboxConfig`` client lifecycle and operational
logging.
"""

from __future__ import annotations

from typing import Any

from acessilia_sdk.operations.fusion import DualFusionUnavailable, extract_dual_fused
from acessilia_sdk.toolbox.clients import ToolboxStructureClient
from docstruct.fusion.payload import (
    fuse_extraction_payloads as _docstruct_fuse_extraction_payloads,
)
from docstruct.fusion.payload import route_pages as _docstruct_route_pages
from docstruct.policy import FusionPolicy

from acessilia_core.config import ToolboxConfig
from acessilia_core.logger import logger
from acessilia_core.toolbox.toolbox_client import make_toolbox_client


def _structure_client(provider: str, toolbox: ToolboxConfig) -> ToolboxStructureClient:
    """A structure-extraction client for ``provider``, configured from the run's ``toolbox``."""
    return make_toolbox_client(ToolboxStructureClient, toolbox, provider=provider)


def _log_fusion_events(
    *,
    artifact_id: str | None,
    artifact_fallbacks: tuple[str, ...],
    failures: dict[str, Exception],
) -> None:
    for provider in artifact_fallbacks:
        logger.info(
            "Fusion: artifact {} not in the Toolbox; uploading for {}",
            artifact_id,
            provider,
        )
    for provider, exc in failures.items():
        logger.info("Fusion: provider {} failed ({})", provider, type(exc).__name__)


async def extract_fused(
    file_path,
    *,
    language: str = "pt-BR",
    secondary_provider: str,
    toolbox: ToolboxConfig,
    policy: FusionPolicy | None = None,
    primary_provider: str | None = None,
    artifact_id: str | None = None,
) -> dict[str, Any]:
    """Extract with the primary + secondary providers and merge the results.

    Delegates the dual-provider extraction and pure payload fusion to
    :func:`acessilia_sdk.operations.fusion.extract_dual_fused`, keeping
    ``ToolboxConfig`` client construction/teardown and operational logs in the
    core.

    Fallback: if one provider reports a Toolbox error, returns the other result
    and logs which provider failed. If both fail, logs both errors and raises
    :class:`~acessilia_sdk.toolbox.errors.ToolboxProviderUnavailable`.
    Unexpected errors propagate unchanged.
    """
    primary = primary_provider or toolbox.providers["toolbox_provider"]
    secondary = secondary_provider

    primary_client = _structure_client(primary, toolbox)
    secondary_client = None
    try:
        secondary_client = _structure_client(secondary, toolbox)
        try:
            result = await extract_dual_fused(
                primary_client,
                secondary_client,
                file_path,
                artifact_id=artifact_id,
                language=language,
                use_remote_cache=toolbox.use_remote_cache,
                policy=policy,
            )
        except DualFusionUnavailable as exc:
            _log_fusion_events(
                artifact_id=artifact_id,
                artifact_fallbacks=exc.artifact_fallbacks,
                failures=exc.failures,
            )
            raise
    finally:
        await primary_client.close()
        if secondary_client is not None:
            await secondary_client.close()

    _log_fusion_events(
        artifact_id=artifact_id,
        artifact_fallbacks=result.artifact_fallbacks,
        failures=result.failures,
    )
    if result.fused:
        elements = (result.payload.get("document") or {}).get("elements") or []
        logger.info(
            "Fusion done: {} final blocks, decisions: {}",
            len(elements),
            result.payload.get("fusion_stats") or {},
        )
    return result.payload


def fuse_extraction_payloads(
    primary_res: dict[str, Any],
    secondary_res: dict[str, Any],
    *,
    primary_provider: str,
    secondary_provider: str,
    policy: FusionPolicy | None = None,
) -> dict[str, Any]:
    """Fuse two already-extracted payloads via ``docstruct.fusion.payload`` and log stats."""
    fused = _docstruct_fuse_extraction_payloads(
        primary_res,
        secondary_res,
        primary_provider=primary_provider,
        secondary_provider=secondary_provider,
        policy=policy,
    )
    elements = (fused.get("document") or {}).get("elements") or []
    logger.info(
        "Fusion done: {} final blocks, decisions: {}",
        len(elements),
        fused.get("fusion_stats") or {},
    )
    return fused


def apply_page_routes(
    primary_res: dict[str, Any],
    secondary_res: dict[str, Any],
    page_evidence: list[dict[str, Any]],
    *,
    secondary_provider: str,
) -> tuple[dict[str, Any], dict[int, list[dict[str, Any]]]]:
    """Put the secondary provider's page where the deterministic router prefers it.

    Delegates pure routing to :func:`docstruct.fusion.payload.route_pages` and
    logs routed and missing secondary pages in the core.
    """
    result = _docstruct_route_pages(
        primary_res,
        secondary_res,
        page_evidence,
        secondary_provider=secondary_provider,
    )
    if result.missing_pages:
        logger.warning(
            "Fusion: {} has no elements on pages {} the router sent to it; "
            "they stay with the primary provider",
            secondary_provider,
            list(result.missing_pages),
        )
    if result.routed_pages:
        logger.info(
            "Fusion: {} pages taken from {} by the deterministic router: {}",
            len(result.routed_pages),
            secondary_provider,
            list(result.routed_pages),
        )
    return result.payload, result.replaced
