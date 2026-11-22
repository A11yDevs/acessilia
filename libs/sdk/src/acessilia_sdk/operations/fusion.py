"""Dual-provider structure extraction and pure payload fusion (ADR-0017).

Composes two :class:`~acessilia_sdk.toolbox.clients.structure.ToolboxStructureClient`
calls (primary and secondary, reusing ``artifact_id`` when present and falling
back to uploading ``file_path`` on :class:`~acessilia_sdk.toolbox.errors.ToolboxArtifactNotFound`)
with :func:`docstruct.fusion.payload.fuse_extraction_payloads`.

The operation never logs, reads settings, or closes caller-owned clients: it
returns a :class:`DualFusionResult` reporting the resulting payload, any
single-provider failure, any artifact fallback, and the capability steps that
succeeded.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from acessilia_sdk.operations.formula import Step
from acessilia_sdk.toolbox.clients.structure import (
    CAPABILITY as STRUCTURE_CAPABILITY,
    ToolboxStructureClient,
)
from acessilia_sdk.toolbox.errors import (
    ToolboxArtifactNotFound,
    ToolboxContractViolation,
    ToolboxError,
    ToolboxProviderUnavailable,
)
from docstruct.fusion.payload import fuse_extraction_payloads
from docstruct.policy import FusionPolicy


class DualFusionUnavailable(ToolboxProviderUnavailable):
    """Both structure providers failed during :func:`extract_dual_fused`.

    Preserves each provider's :class:`~acessilia_sdk.toolbox.errors.ToolboxError`
    in ``failures`` and any ``artifact_id`` upload fallbacks in
    ``artifact_fallbacks``, so callers that log (such as the core) can record
    per-provider diagnostics without coupling the SDK to a logger (ADR-0017).
    """

    def __init__(
        self,
        failures: dict[str, ToolboxError],
        artifact_fallbacks: tuple[str, ...] = (),
        message: str = "No provider available for extraction",
    ) -> None:
        self.failures = dict(failures)
        self.artifact_fallbacks = tuple(artifact_fallbacks)
        super().__init__(message)

    def __reduce__(self) -> tuple[Any, ...]:
        return (
            type(self),
            (self.failures, self.artifact_fallbacks, str(self)),
        )


def _validated_payload(payload: Any) -> dict[str, Any]:
    """The extraction envelope, refusing an answer outside the contract.

    ``extract_structure`` is typed to return a ``dict``, but a fake client or a
    caller's implementation may still answer ``None`` or a bare payload. The
    envelope must have a ``succeeded`` status and hold the ``document`` object
    the fusion reads. Recording an invalid answer as a successful step would
    hide the provider's failure: ``_collect_outcomes`` would see no payload and
    no error, and ``DualFusionUnavailable`` would raise with an empty
    ``failures`` map (or the fusion would fail later on an unexpected
    exception). A contract violation keeps the provider's error.
    """
    if not isinstance(payload, dict):
        raise ToolboxContractViolation(
            f"{STRUCTURE_CAPABILITY} returned {type(payload).__name__}, not an object"
        )
    status = payload.get("status")
    if status != "succeeded":
        raise ToolboxContractViolation(
            f"{STRUCTURE_CAPABILITY} answered with status={status!r}, not 'succeeded'"
        )
    document = payload.get("document")
    if not isinstance(document, dict):
        raise ToolboxContractViolation(
            f"{STRUCTURE_CAPABILITY} answered without a document object: "
            f"{type(document).__name__}"
        )
    return payload


@dataclass(frozen=True)
class DualFusionResult:
    """Outcome of :func:`extract_dual_fused` across two structure providers.

    ``payload`` is the fused payload when both providers succeeded (``fused=True``)
    or the surviving provider's payload when one failed with a
    :class:`~acessilia_sdk.toolbox.errors.ToolboxError` (``fused=False``).
    ``failures`` maps each failed provider name to its ``ToolboxError``; an
    answer outside the envelope (not a JSON object, one whose ``status`` is not
    ``succeeded``, or without its ``document`` object) counts as a
    :class:`~acessilia_sdk.toolbox.errors.ToolboxContractViolation` and never
    produces a ``Step``;
    ``artifact_fallbacks`` lists providers where ``artifact_id`` was missing in
    the Toolbox and ``file_path`` was uploaded instead; ``steps`` records each
    successful ``document.structure.extract`` step.
    """

    payload: dict[str, Any]
    primary_provider: str
    secondary_provider: str
    fused: bool
    failures: dict[str, ToolboxError]
    artifact_fallbacks: tuple[str, ...]
    steps: tuple[Step, ...]


async def _extract_with_fallback(
    client: ToolboxStructureClient,
    source: Path | None,
    *,
    artifact_id: str | None,
    language: str,
    use_remote_cache: bool | None,
) -> tuple[dict[str, Any] | None, ToolboxError | None, bool, Step | None]:
    fell_back = False
    try:
        if artifact_id:
            try:
                payload = _validated_payload(
                    await client.extract_structure(
                        artifact_id=artifact_id,
                        language=language,
                        use_remote_cache=use_remote_cache,
                    )
                )
                step = Step(
                    STRUCTURE_CAPABILITY,
                    client.provider,
                    {"language": language, "source": "artifact"},
                )
                return payload, None, False, step
            except ToolboxArtifactNotFound:
                if source is None:
                    raise
                fell_back = True
        payload = _validated_payload(
            await client.extract_structure(
                source,
                language=language,
                use_remote_cache=use_remote_cache,
            )
        )
        step = Step(
            STRUCTURE_CAPABILITY,
            client.provider,
            {"language": language, "source": "file"},
        )
        return payload, None, fell_back, step
    except ToolboxError as exc:
        return None, exc, fell_back, None


def _collect_outcomes(
    primary_name: str,
    secondary_name: str,
    primary_out: tuple[dict[str, Any] | None, ToolboxError | None, bool, Step | None],
    secondary_out: tuple[dict[str, Any] | None, ToolboxError | None, bool, Step | None],
    *,
    policy: FusionPolicy | None,
) -> DualFusionResult:
    primary_res, primary_err, primary_fb, primary_step = primary_out
    secondary_res, secondary_err, secondary_fb, secondary_step = secondary_out

    failures: dict[str, ToolboxError] = {}
    if primary_err is not None:
        failures[primary_name] = primary_err
    if secondary_err is not None:
        failures[secondary_name] = secondary_err

    fallbacks = tuple(
        name
        for name, flag in ((primary_name, primary_fb), (secondary_name, secondary_fb))
        if flag
    )
    steps = tuple(step for step in (primary_step, secondary_step) if step is not None)

    if primary_res is None and secondary_res is None:
        raise DualFusionUnavailable(failures, fallbacks)
    if primary_res is None or secondary_res is None:
        surviving = secondary_res if primary_res is None else primary_res
        assert surviving is not None
        return DualFusionResult(
            payload=surviving,
            primary_provider=primary_name,
            secondary_provider=secondary_name,
            fused=False,
            failures=failures,
            artifact_fallbacks=fallbacks,
            steps=steps,
        )

    fused_payload = fuse_extraction_payloads(
        primary_res,
        secondary_res,
        primary_provider=primary_name,
        secondary_provider=secondary_name,
        policy=policy,
    )
    return DualFusionResult(
        payload=fused_payload,
        primary_provider=primary_name,
        secondary_provider=secondary_name,
        fused=True,
        failures={},
        artifact_fallbacks=fallbacks,
        steps=steps,
    )


async def extract_dual_fused(
    primary: ToolboxStructureClient,
    secondary: ToolboxStructureClient,
    file_path: Path | str | None = None,
    *,
    artifact_id: str | None = None,
    language: str = "pt-BR",
    use_remote_cache: bool | None = None,
    policy: FusionPolicy | None = None,
) -> DualFusionResult:
    """Extract with ``primary`` and ``secondary`` in parallel and fuse their payloads.

    Requires at least one of ``file_path`` or ``artifact_id``. When
    ``artifact_id`` is given and a provider answers with
    :class:`~acessilia_sdk.toolbox.errors.ToolboxArtifactNotFound`, falls back
    to uploading ``file_path`` (when provided) and records that provider in
    :attr:`DualFusionResult.artifact_fallbacks`.

    If one provider raises a :class:`~acessilia_sdk.toolbox.errors.ToolboxError`,
    returns the other provider's payload with ``fused=False`` and records the
    error in :attr:`DualFusionResult.failures`. An answer outside the envelope
    (not a JSON object, one whose ``status`` is not ``succeeded``, or without
    its ``document`` object) counts as a
    :class:`~acessilia_sdk.toolbox.errors.ToolboxContractViolation`, so its
    error is recorded too instead of passing for a successful step. If both
    fail with ``ToolboxError``, raises :class:`DualFusionUnavailable` (a
    subclass of
    :class:`~acessilia_sdk.toolbox.errors.ToolboxProviderUnavailable`) carrying
    ``failures`` and ``artifact_fallbacks``. Unexpected (non-``ToolboxError``)
    exceptions propagate unchanged.
    """
    if file_path is None and not artifact_id:
        raise ValueError("Provide file_path or artifact_id")

    source = Path(file_path) if file_path is not None else None
    primary_name = str(primary.provider or "primary")
    secondary_name = str(secondary.provider or "secondary")

    primary_out, secondary_out = await asyncio.gather(
        _extract_with_fallback(
            primary,
            source,
            artifact_id=artifact_id,
            language=language,
            use_remote_cache=use_remote_cache,
        ),
        _extract_with_fallback(
            secondary,
            source,
            artifact_id=artifact_id,
            language=language,
            use_remote_cache=use_remote_cache,
        ),
    )
    return _collect_outcomes(
        primary_name,
        secondary_name,
        primary_out,
        secondary_out,
        policy=policy,
    )


__all__ = [
    "DualFusionResult",
    "DualFusionUnavailable",
    "extract_dual_fused",
]
