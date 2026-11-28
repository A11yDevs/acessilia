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
    RunOutcome,
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
        outcome: RunOutcome | None = None,
    ) -> None:
        """``options`` are the run's own options outside ``config``, by stage
        (the orchestrator's planner and dry run); the port's ``options``
        add the service's (its model revision). Both enter the identities.

        ``outcome`` records the phases a resumed run actually reused (#944)."""
        self._checkpoints = checkpoints
        self._outcome = outcome
        self._identity: dict[str, str] = {}
        if checkpoints is not None:
            port_options = getattr(checkpoints, "options", None) or {}
            for stage in STAGE_FIELDS:
                merged = {**(options or {}).get(stage, {}), **port_options.get(stage, {})}
                self._identity[stage] = stage_identity(config, stage, merged)
        # Set once a phase is redone: the phases after it were built on the
        # old one, so none of them is reused either.
        self._stale = False
        # The plan run's execution checkpoint, once it starts (#836).
        self._execution: _ExecutionCheckpoint | None = None

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

    def accept(self, phase: str) -> None:
        """Record that the caller adopted the checkpoint of ``phase`` (#944).

        ``load`` only returns the payload: a phase can still be discarded by
        the caller's content checks (an execution checkpoint from another
        plan, for example). Only an accepted phase is provenance.
        """
        if self._outcome is None:
            return
        self._outcome.mark_reused(phase)

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
        *,
        discoveries: int = 0,
        previous_signature: str | None = None,
        admission_deferred_ids: Iterable[str] = (),
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
                "discoveries": discoveries,
                "previous_signature": previous_signature,
                # A deterministic, ordered record of the admission deferrals
                # the recovery budget must keep across a plan replacement and
                # a resume (#828 review).
                "admission_deferred_ids": sorted(set(admission_deferred_ids)),
            },
        )

    def remove(self, phase: str) -> None:
        if self._checkpoints is not None:
            self._checkpoints.remove(phase)

    def enrichment_progress(self, manifest: ProcessingManifest) -> Callable[[], Any]:
        """The ``on_progress`` callback of the enrichment steps (#407)."""
        return _EnrichmentCheckpoint(self, manifest).save

    def execution_saver(
        self, plan: NominalPlan, *, resumed: dict[str, Any] | None = None
    ) -> _ExecutionCheckpoint:
        """A callback the executor calls after each step, writing the checkpoint.

        It also takes the progress of the step running (:meth:`step_progress`,
        #836), so it becomes the run's current execution checkpoint.
        ``resumed`` is the execution checkpoint a resumed run starts from: its
        last finished step is the snapshot the step's progress extends, so a
        second crash in the same step keeps what the resumed run did (#857
        review)."""
        if self._checkpoints is None:
            raise RuntimeError("an execution checkpoint needs the job's checkpoints")
        self._execution = _ExecutionCheckpoint(self, plan, resumed=resumed)
        return self._execution

    def step_progress(self, obligation_id: str, manifest: dict[str, Any]) -> None:
        """Persist the manifest a composite method is enriching, mid-step (#836).

        A no-op outside a plan run with checkpoints. Blocking: a method calls
        it off its event loop, with the manifest already serialized."""
        if self._execution is not None:
            self._execution.step_progress(obligation_id, manifest)


#: The key of the execution checkpoint that holds the step running (#836).
STEP_PROGRESS_KEY = "step_progress"


def restored_admission_deferred_ids(payload: dict[str, Any]) -> tuple[str, ...]:
    """The admission deferrals a plan checkpoint recorded, safely.

    A checkpoint from before the field, or with a malformed value, restores
    no deferrals: the current execution report still contributes the
    deferrals of the run in progress (#828 review).
    """
    raw = payload.get("admission_deferred_ids")
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in raw if isinstance(item, str))


def load_execution_state(
    checkpoints: RunCheckpoints, plan: NominalPlan
) -> dict[str, Any] | None:
    """The execution checkpoint of ``plan``, ``None`` when it belongs to another plan.

    A checkpoint from another plan is loaded but not accepted as provenance:
    its progress does not apply to the new plan and it is not reused.
    """
    execution_state = checkpoints.load(PHASE_EXECUTION)
    if execution_state is not None and execution_state.get("plan_id") != plan.plan_id:
        return None
    # Matching the plan is only a precondition: _run_plan validates the manifest
    # and results and accepts this payload after constructing ExecutionResume.
    return execution_state


def resumed_manifest(execution_state: dict[str, Any], plan: NominalPlan) -> dict[str, Any]:
    """The manifest a resumed execution starts from (#836).

    The one after the last finished step, unless the checkpoint also holds
    the progress of the step after it: a composite method (picture
    descriptions, formula LaTeX, tables) saves the manifest it is enriching
    after each object, and its step starts again from that manifest, so its
    per-object gates skip what was already done. The progress of a step the
    plan does not run next is never used.
    """
    progress = execution_state.get(STEP_PROGRESS_KEY)
    results = execution_state.get("results") or []
    if isinstance(progress, dict) and len(results) < len(plan.steps):
        if plan.steps[len(results)].obligation_id == progress.get("obligation_id"):
            return _with_discoveries_selected(progress["manifest"], execution_state["manifest"])
    return execution_state["manifest"]


def _with_discoveries_selected(progress: dict[str, Any], before: dict[str, Any]) -> dict[str, Any]:
    """``progress`` with the obligations the interrupted step added selected.

    The step's finished objects may have added obligations (a picture read
    as a formula gets ``verbalize-formula``). In a run that is not
    interrupted, ``_select_discovered`` selects them once the handler
    returns; the crash came first, so the resumed step would see them as
    known and never select them, and the job would finish without them (#857
    review). They are selected here, as the executor would have done; one
    still open then asks for the replan (``_sync_goals``).
    """
    known = {item["id"] for item in before.get("obligations") or []}
    manifest = dict(progress)
    manifest["obligations"] = [
        item if item["id"] in known else {**item, "selected": True}
        for item in progress.get("obligations") or []
    ]
    return manifest


class _ExecutionCheckpoint:
    """The execution checkpoint of one plan: one write after each step, and
    the progress of the step running in between (#836).

    The progress is the last finished snapshot plus ``step_progress``: the
    step's obligation and the manifest its method is enriching. The next
    finished step writes a snapshot without it, so it never outlives its
    step. A resumed run starts from the snapshot it resumed (``resumed``), so
    its first step's progress is written too. Before the plan's first
    finished step there is no snapshot to extend, and the progress is not
    written.
    """

    def __init__(
        self, run: RunCheckpoints, plan: NominalPlan, *, resumed: dict[str, Any] | None = None
    ) -> None:
        self._run = run
        self._plan = plan
        self._last: dict[str, Any] | None = None
        if resumed is not None and resumed.get("plan_id") == plan.plan_id:
            # The last finished step of the run this one resumes; its own
            # progress and identity are rewritten with the next write.
            self._last = {
                key: value for key, value in resumed.items()
                if key not in (STEP_PROGRESS_KEY, IDENTITY_KEY)
            }

    def __call__(self, snapshot: dict[str, Any]) -> None:
        if snapshot.get("plan_id") != self._plan.plan_id:
            # A snapshot from another plan must never overwrite this one.
            return
        self._last = dict(snapshot)
        self._write(self._last)

    def step_progress(self, obligation_id: str, manifest: dict[str, Any]) -> None:
        if self._last is None:
            return
        self._write({**self._last, STEP_PROGRESS_KEY: {"obligation_id": obligation_id, "manifest": manifest}})

    def _write(self, snapshot: dict[str, Any]) -> None:
        checkpoints = self._run._checkpoints
        if checkpoints is None:
            return
        try:
            checkpoints.save(
                PHASE_EXECUTION, self._run._stamp(dict(snapshot), PHASE_STAGES[PHASE_EXECUTION])
            )
        except Exception as exc:  # noqa: BLE001 - a checkpoint must not fail a step
            logger.warning(
                "Job {}: execution checkpoint not written: {}", checkpoints.job_id, exc
            )


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
    "STEP_PROGRESS_KEY",
    "IDENTITY_KEY",
    "PHASE_STAGES",
    "RunCheckpoints",
    "manifest_payload",
    "load_execution_state",
    "restored_admission_deferred_ids",
    "resumed_manifest",
]
