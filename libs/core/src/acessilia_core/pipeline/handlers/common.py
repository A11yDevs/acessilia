"""Helpers every deterministic method handler shares.

A handler takes the manifest and an obligation id and returns a
``MethodResult``. The handler contract moved from the PDDL orchestrator (#402,
phase 3, step 6); ``write_atomic_artifact`` is the writer the evidence handlers
(fusion and region inspection) share for the files under the run's ``data_dir``
(#612).
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
from collections.abc import Awaitable, Callable, Coroutine
from pathlib import Path
from typing import Any

from acessilia_core.agents.fusion_agent import FusionAgent
from acessilia_core.blocking import run_blocking
from acessilia_core.execution.models import MethodResult
from acessilia_core.i18n import t
from acessilia_core.manifest.models import Artifact, ManifestElement, ProcessingManifest
from acessilia_core.pipeline.handlers.messages import MSG_HANDLER_OBLIGATION_NOT_FOUND
from acessilia_core.ports import RunPorts


def run_status(ports: RunPorts) -> Callable[[str], Coroutine[Any, Any, None]] | None:
    """The run's progress reporter as the coroutine a document-wide step
    awaits (``table-enrichment``, ``picture-description``); ``None`` without one."""
    report = ports.services.progress
    if report is None:
        return None

    async def status(message: str) -> None:
        report(message)

    return status


def step_checkpoint(
    ports: RunPorts, manifest: ProcessingManifest, obligation_id: str
) -> Callable[[], Awaitable[None]] | None:
    """The ``on_progress`` a composite method gives its stage (#836): after
    each object, the manifest it is enriching goes into the run's execution
    checkpoint, so a crash mid-step resumes from it and the stage's
    per-object gates skip the objects already done. ``None`` outside a job."""
    save = ports.services.step_checkpoint
    if save is None:
        return None
    return _StepCheckpoint(save, manifest, obligation_id).save


class _StepCheckpoint:
    """Coalesced step checkpoints, like the enrichment's before planning
    (#407): one write at a time, and a burst of finished objects during a
    write gives one more write with the latest manifest. The manifest is
    serialized on the event loop, where the stage folds its objects, so the
    write never races with them."""

    def __init__(
        self, save: Callable[[str, dict[str, Any]], None], manifest: ProcessingManifest, obligation_id: str
    ) -> None:
        self._save = save
        self._manifest = manifest
        self._obligation_id = obligation_id
        self._lock = asyncio.Lock()
        self._pending = 0

    async def save(self) -> None:
        self._pending += 1
        if self._lock.locked():
            return
        async with self._lock:
            while self._pending:
                self._pending = 0
                payload = self._manifest.model_dump(mode="json", by_alias=True)
                await run_blocking(self._save, self._obligation_id, payload)


def _fusion_agent() -> FusionAgent:
    """Fusion agent used to reach the deterministic fusion primitives.

    The `docstruct` functions take classified blocks, counters and tuning
    parameters; `FusionAgent.process_*` is the in-repo entry point that supplies
    them, so handlers call that instead of a primitive whose signature they would
    otherwise have to guess.
    """
    return FusionAgent()


def _target_elements(
    manifest: ProcessingManifest, obligation_id: str
) -> list[ManifestElement]:
    """Elements an obligation points at, in reading order."""
    obligation = next(
        (o for o in manifest.obligations if o.id == obligation_id), None
    )
    if obligation is None:
        return []
    targets = set(obligation.target_ids)
    return sorted(
        (el for el in manifest.elements if el.id in targets),
        key=lambda el: el.reading_order,
    )


def _missing_obligation(obligation_id: str) -> MethodResult:
    return MethodResult(
        success=False,
        validated=False,
        message=t(MSG_HANDLER_OBLIGATION_NOT_FOUND).format(
            obligation_id=obligation_id
        ),
    )


def write_atomic_artifact(
    content: bytes,
    *,
    category: str,
    scope: str,
    kind: str,
    suffix: str,
    media_type: str,
    data_dir: Path,
    id_prefix: str | None = None,
) -> Artifact:
    """Write ``content`` atomically and describe it as an ``Artifact``.

    The file is content addressed, at
    ``data_dir/artifacts/<category>/<scope>/<sha256>.<suffix>``, so equal
    content reuses one file. The record's id is
    ``artifact-<id_prefix>-<scope[:16]>-<sha256[:16]>``, with ``kind`` as the
    default prefix. A failed write removes its temporary file beside the
    target, leaving no partial artifact behind.
    """
    digest = hashlib.sha256(content).hexdigest()
    output_path = data_dir / "artifacts" / category / scope / f"{digest}.{suffix}"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=output_path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, output_path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    prefix = id_prefix if id_prefix is not None else kind
    return Artifact(
        id=f"artifact-{prefix}-{scope[:16]}-{digest[:16]}",
        kind=kind,
        path=str(output_path),
        media_type=media_type,
        sha256=digest,
    )
