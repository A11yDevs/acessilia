"""A run's checkpoints, and whether a resumed run may reuse them (#407, #549).

Each phase's checkpoint records the identity of the run's config for the
stages it holds (``run_identity.STAGE_FIELDS``): the extraction depends on
the fusion and Toolbox options, the enrichment on the models and the vision
options, the plan on the availability gate. A resumed run whose config
changed redoes the first phase holding a changed stage and every phase after
it: the earlier phases, and the paid model calls they hold, are kept.

A checkpoint written before these identities existed is reused, with a
warning, as it was before.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from acessilia_core.blocking import run_blocking
from acessilia_core.config import CoreConfig
from acessilia_core.logger import logger
from acessilia_core.manifest.models import ProcessingManifest
from acessilia_core.planning import toolbox_gate
from acessilia_core.planning.models import NominalPlan, PlanningComparison
from acessilia_core.ports import (
    PHASE_ENRICHED,
    PHASE_EXECUTION,
    PHASE_MANIFEST,
    PHASE_MEDIA,
    PHASE_PLAN,
    JobCheckpoints,
)
from acessilia_core.run_identity import STAGE_FIELDS, stage_identity

#: The stages each phase's checkpoint holds, in the order a run produces them.
PHASE_STAGES: dict[str, tuple[str, ...]] = {
    PHASE_MEDIA: ("media",),
    PHASE_MANIFEST: ("media", "extraction"),
    PHASE_ENRICHED: ("media", "extraction", "enrichment"),
    PHASE_PLAN: ("media", "extraction", "enrichment", "planning"),
    PHASE_EXECUTION: ("media", "extraction", "enrichment", "planning", "execution"),
}

#: The manifest checkpoint written during enrichment also holds its progress
#: (each finished object), so it depends on the enrichment's stage too.
ENRICHING_STAGES: tuple[str, ...] = ("media", "extraction", "enrichment")

#: Where a checkpoint payload records its stages' identities.
IDENTITY_KEY = "config_identity"


def manifest_payload(manifest: ProcessingManifest) -> dict[str, Any]:
    return manifest.model_dump(mode="json", by_alias=True)


class RunCheckpoints:
    """The checkpoints of one run, against that run's ``config``.

    Without a job (``checkpoints`` is ``None``) nothing is read or written,
    and no payload is even serialized.
    """

    def __init__(
        self,
        checkpoints: JobCheckpoints | None,
        config: CoreConfig,
        *,
        options: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        """``options`` are the run's own options outside ``config``, by stage
        (the orchestrator's planner and dry run); the port's ``options``
        add the service's (its model revision). Both enter the identities."""
        self._checkpoints = checkpoints
        self._identity: dict[str, str] = {}
        if checkpoints is not None:
            port_options = getattr(checkpoints, "options", None) or {}
            for stage in STAGE_FIELDS:
                merged = {**(options or {}).get(stage, {}), **port_options.get(stage, {})}
                self._identity[stage] = stage_identity(config, stage, merged)
        # Set once a phase is redone: the phases after it were built on the
        # old one, so none of them is reused either.
        self._stale = False

    @property
    def active(self) -> bool:
        return self._checkpoints is not None

    def load(self, phase: str) -> dict[str, Any] | None:
        """The phase's payload, or ``None`` when it is absent or was written
        under another config (or follows one that was)."""
        if self._checkpoints is None or self._stale:
            return None
        payload = self._checkpoints.load(phase)
        if payload is None:
            return None
        if IDENTITY_KEY not in payload:
            logger.warning(
                "Job {}: the {} checkpoint predates config identities; reused as before",
                self._checkpoints.job_id, phase,
            )
            return payload
        stored = payload[IDENTITY_KEY]
        if not isinstance(stored, Mapping):
            # Unreadable identity: never taken as a match (review of #578).
            changed = ["unreadable identity"]
        else:
            # Every stage the phase holds must be recorded and equal: a
            # partial identity is not a match (review of #578).
            changed = sorted(
                stage for stage in PHASE_STAGES[phase]
                if stored.get(stage) != self._identity.get(stage)
            ) + sorted(
                stage for stage, digest in stored.items()
                if stage not in PHASE_STAGES[phase] and self._identity.get(stage) != digest
            )
        if changed:
            self._stale = True
            logger.warning(
                "Job {}: the {} checkpoint was written under another configuration "
                "({}); that phase and the ones after it run again",
                self._checkpoints.job_id, phase, ", ".join(changed),
            )
            return None
        return payload

    def _stamp(self, payload: dict[str, Any], stages: Iterable[str]) -> dict[str, Any]:
        payload[IDENTITY_KEY] = {stage: self._identity[stage] for stage in stages}
        return payload

    async def save(
        self, phase: str, build: Callable[[], dict[str, Any]],
        *, stages: Iterable[str] | None = None,
    ) -> None:
        """Persist one phase off the event loop (``build`` runs only inside a
        job); a failed write never fails the job."""
        if self._checkpoints is None:
            return
        payload = self._stamp(build(), stages or PHASE_STAGES[phase])
        try:
            await run_blocking(self._checkpoints.save, phase, payload)
        except Exception as exc:  # noqa: BLE001 - a checkpoint must not fail the job
            logger.warning(
                "Job {}: {} checkpoint not written: {}", self._checkpoints.job_id, phase, exc
            )

    async def save_manifest(self, manifest: ProcessingManifest, *, enriching: bool) -> None:
        """The manifest checkpoint: after the extraction, or with the
        enrichment's progress (``enriching``)."""
        await self.save(
            PHASE_MANIFEST, lambda: {"manifest": manifest_payload(manifest)},
            stages=ENRICHING_STAGES if enriching else PHASE_STAGES[PHASE_MANIFEST],
        )

    async def save_plan(
        self,
        plan: NominalPlan,
        comparison: PlanningComparison | None,
        manifest: ProcessingManifest,
        availability: toolbox_gate.AvailabilityDecision,
        gated: Iterable[str],
        replans: int,
    ) -> None:
        await self.save(
            PHASE_PLAN,
            lambda: {
                "plan": plan.model_dump(mode="json", by_alias=True),
                "comparison": (
                    comparison.model_dump(mode="json", by_alias=True)
                    if comparison is not None
                    else None
                ),
                "manifest": manifest_payload(manifest),
                "availability": availability.to_metadata(),
                "gated": sorted(gated),
                "replans": replans,
            },
        )

    def remove(self, phase: str) -> None:
        if self._checkpoints is not None:
            self._checkpoints.remove(phase)

    def enrichment_progress(self, manifest: ProcessingManifest) -> Callable[[], Any]:
        """The ``on_progress`` callback of the enrichment steps (#407)."""
        return _EnrichmentCheckpoint(self, manifest).save

    def execution_saver(self, plan: NominalPlan) -> Callable[[dict[str, Any]], None]:
        """A callback the executor calls after each step, writing the checkpoint."""
        checkpoints = self._checkpoints
        if checkpoints is None:
            raise RuntimeError("an execution checkpoint needs the job's checkpoints")

        def save(snapshot: dict[str, Any]) -> None:
            if snapshot.get("plan_id") != plan.plan_id:
                # A snapshot from another plan must never overwrite this one.
                return
            try:
                checkpoints.save(
                    PHASE_EXECUTION, self._stamp(dict(snapshot), PHASE_STAGES[PHASE_EXECUTION])
                )
            except Exception as exc:  # noqa: BLE001 - a checkpoint must not fail a step
                logger.warning(
                    "Job {}: execution checkpoint not written: {}", checkpoints.job_id, exc
                )

        return save


class _EnrichmentCheckpoint:
    """Coalesced manifest checkpoints during one enrichment stage (#407).

    Each completed object calls :meth:`save`. One write runs at a time and a
    burst of completions during a write produces one more write with the latest
    manifest, so every object becomes durable without one full checkpoint per
    object. The manifest snapshot is taken synchronously before the write is
    handed to a thread, so concurrent folds never race with serialization.
    """

    def __init__(self, checkpoints: RunCheckpoints, manifest: ProcessingManifest) -> None:
        self._checkpoints = checkpoints
        self._manifest = manifest
        self._lock = asyncio.Lock()
        self._pending = 0

    async def save(self) -> None:
        if not self._checkpoints.active:
            return
        self._pending += 1
        if self._lock.locked():
            # The running writer sees the increment and writes again.
            return
        async with self._lock:
            while self._pending:
                self._pending = 0
                await self._checkpoints.save_manifest(self._manifest, enriching=True)


__all__ = [
    "ENRICHING_STAGES",
    "IDENTITY_KEY",
    "PHASE_STAGES",
    "RunCheckpoints",
    "manifest_payload",
]
