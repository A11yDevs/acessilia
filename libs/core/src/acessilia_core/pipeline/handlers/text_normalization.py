"""Core target selection and atomic acceptance of remote normalization observations."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from acessilia_core.config import CoreConfig
from acessilia_core.execution.models import MethodResult
from acessilia_core.i18n import n, t
from acessilia_core.logger import logger
from acessilia_core.manifest.models import (
    ManifestElement,
    Obligation,
    ProcessingManifest,
)
from acessilia_core.pipeline.handlers.common import (
    _missing_obligation,
    _target_elements,
)
from acessilia_core.pipeline.handlers.messages import (
    MSG_NORMALIZE_APPLIED,
    MSG_NORMALIZE_FAILED,
    MSG_NORMALIZE_NO_TEXT,
    MSG_NORMALIZE_STALE,
)
from acessilia_core.ports import NormalizationOperationSlot, RunPorts
from acessilia_core.toolbox.toolbox_client import make_toolbox_client
from acessilia_sdk.runtime import run_sync
from acessilia_sdk.toolbox.capabilities import provider_default
from acessilia_sdk.toolbox.clients import ToolboxTextNormalizeClient
from acessilia_sdk.toolbox.errors import ToolboxError
from acessilia_sdk.toolbox.operation import new_operation_id, operation_context
from acessilia_sdk.toolbox.text_normalization import (
    CAPABILITY,
    DOCSTRUCT_VERSION,
    PROVIDER_VERSION,
    NormalizationBatch,
    TextObservation,
    TextTarget,
    canonical_json,
    fingerprint,
    normalization_batches,
)


@dataclass(frozen=True)
class _Context:
    manifest_id: str
    revision: int
    source_sha256: str
    obligation: Obligation
    elements: tuple[ManifestElement, ...]


def _context(manifest: ProcessingManifest, obligation_id: str) -> _Context:
    obligation = next(item for item in manifest.obligations if item.id == obligation_id)
    return _Context(
        manifest.manifest_id,
        manifest.revision,
        manifest.source.sha256,
        deepcopy(obligation),
        tuple(deepcopy(_target_elements(manifest, obligation_id))),
    )


def _scope(context: _Context, config: CoreConfig, ports: RunPorts) -> str:
    """A journal slot's semantic context; attempt bookkeeping is not input."""
    return fingerprint(
        canonical_json(
            {
                "manifest": context.manifest_id,
                "revision": context.revision,
                "source": context.source_sha256,
                "obligation": {
                    "id": context.obligation.id,
                    "kind": context.obligation.kind,
                    "target_ids": context.obligation.target_ids,
                },
                "elements": [
                    {
                        "id": item.id,
                        "text": item.text,
                        "type": item.type,
                        "page": item.page_number,
                        "order": item.reading_order,
                    }
                    for item in context.elements
                ],
                "capability": CAPABILITY,
                "version": 1,
                "provider_version": PROVIDER_VERSION,
                "docstruct": DOCSTRUCT_VERSION,
                "provider": config.toolbox.providers.get(
                    "toolbox_text_normalize_provider"
                )
                or provider_default("toolbox_text_normalize_provider"),
                "no_cache": not config.toolbox.use_remote_cache,
                "deployment": {
                    "base_url": config.toolbox.base_url,
                    "base_urls": config.toolbox.base_urls,
                    "revision": getattr(ports.checkpoints, "options", {})
                    .get("execution", {})
                    .get("processing_model_revision", ""),
                },
            }
        )
    )


async def _observe(
    batches: tuple[NormalizationBatch, ...],
    scope: str,
    *,
    config: CoreConfig,
    ports: RunPorts,
) -> tuple[TextObservation, ...]:
    client = make_toolbox_client(ToolboxTextNormalizeClient, config.toolbox)
    observations: list[TextObservation] = []
    try:
        for batch in batches:
            slot = NormalizationOperationSlot(
                "norm-fix:"
                + fingerprint(canonical_json([scope, fingerprint(batch.payload)]))
            )
            operations = ports.operations
            operation_id = (
                operations.begin(slot) if operations is not None else new_operation_id()
            )
            task_id = operations.job_id if operations is not None else scope
            try:
                with operation_context(task_id, operation_id):
                    result = await client.normalize(
                        batch, use_remote_cache=config.toolbox.use_remote_cache
                    )
                observations.extend(result.observations)
                logger.debug(
                    "Text normalization batch: {} bytes; {}",
                    len(batch.payload),
                    result.provenance,
                )
            finally:
                if operations is not None:
                    operations.finish(operation_id)
    finally:
        await client.close()
    return tuple(observations)


def _handle_norm_fix_method(
    manifest: ProcessingManifest,
    obligation_id: str,
    *,
    config: CoreConfig,
    ports: RunPorts,
) -> MethodResult:
    """Collect all bounded observations before accepting one obligation's update."""
    if not _target_elements(manifest, obligation_id):
        return _missing_obligation(obligation_id)
    before = _context(manifest, obligation_id)
    targets = tuple(
        TextTarget(item.id, item.text) for item in before.elements if item.text
    )
    if not targets:
        return MethodResult(
            success=False, validated=False, message=t(MSG_NORMALIZE_NO_TEXT)
        )
    try:
        batches = normalization_batches(targets)
        observations = run_sync(
            _observe(batches, _scope(before, config, ports), config=config, ports=ports)
        )
    except (ToolboxError, ValueError) as exc:
        logger.warning("Text normalization refused: {}", exc)
        return MethodResult(
            success=False,
            validated=False,
            message=t(MSG_NORMALIZE_FAILED).format(reason=str(exc)),
        )
    if not any(item.id == obligation_id for item in manifest.obligations) or (
        _context(manifest, obligation_id) != before
    ):
        return MethodResult(
            success=False, validated=False, message=t(MSG_NORMALIZE_STALE)
        )
    by_id = {item.id: item for item in observations}
    for element in _target_elements(manifest, obligation_id):
        item = by_id.get(element.id)
        if item is not None and item.changed:
            element.text = item.text
            element.metadata["norm_fixed"] = True
    return MethodResult(
        success=True,
        validated=True,
        message=n(*MSG_NORMALIZE_APPLIED, len(targets)).format(count=len(targets)),
    )
