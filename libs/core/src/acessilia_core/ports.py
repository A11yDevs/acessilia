"""What a run needs from the service that hosts it (ADR-0016, step 4).

The core does not own the service's state: its caches, its job checkpoints
and its registry of remote operations live in ``backend/services``. A run
receives them as ``RunPorts``, built by its caller for that job, so the core
imports nothing from it; ``tests/test_run_ports.py`` checks that.

``RunPorts.none()`` keeps no state, for a script or a test that hosts no
service: its region cache stores nothing, and it has no job, so no
checkpoints and no registered operations.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, NewType, Protocol, TypeVar

from acessilia_core.config import VisionConfig


class RegionCache(Protocol):
    """Stored answers for a region image, keyed on its content and a variant.

    The variant names everything else the answer depends on (the prompt, the
    model, the budget, the locale); the core builds it with
    :func:`acessilia_core.cache_keys.options_cache_key`.
    """

    async def get(self, content: bytes, variant: str, *, ttl_seconds: int) -> Any | None:
        """The stored payload, or ``None`` when absent or older than ``ttl_seconds``."""

    async def put(self, content: bytes, variant: str, payload: Any) -> None:
        """Store ``payload`` (JSON-ready) for ``content`` under ``variant``."""


#: The phases of a run the core checkpoints, in order (#407). A job resumes
#: from the last phase stored for it; the service stores them by name.
PHASE_MEDIA = "media"
PHASE_MANIFEST = "manifest"
PHASE_ENRICHED = "enriched"
PHASE_PLAN = "plan"
PHASE_EXECUTION = "execution"
CHECKPOINT_PHASES: tuple[str, ...] = (
    PHASE_MEDIA, PHASE_MANIFEST, PHASE_ENRICHED, PHASE_PLAN, PHASE_EXECUTION,
)


class JobCheckpoints(Protocol):
    """The durable checkpoints of one job, by phase (ADR-0020).

    Bound to the job by the service, which names and stores them; the core
    only says which phase it writes. ``job_id`` names the job in the log.
    Methods are blocking. The core runs ``save`` off the event loop, during
    the run; it calls ``load`` and ``remove`` directly, as it did before the
    port, each once per phase.
    """

    job_id: str
    #: Optional: the service's own processing options the checkpoints depend
    #: on, by stage name (``run_identity.STAGE_FIELDS``), such as the model
    #: revision for ``enrichment`` and ``execution``. Absent means none.
    options: Mapping[str, Mapping[str, Any]]

    def load(self, phase: str) -> dict[str, Any] | None:
        """The phase's payload, ``None`` when absent; raises when it exists
        but cannot be trusted, so the phase is not resumed from it."""

    def save(self, phase: str, payload: dict[str, Any]) -> None:
        """Store the phase's JSON-ready payload, replacing the previous one."""

    def remove(self, phase: str) -> None:
        """Drop the phase's payload, if any."""


#: A normalization slot includes its immutable input/context digest, so distinct
#: batches or revisions never reuse an extraction slot or another request's id.
NormalizationOperationSlot = NewType("NormalizationOperationSlot", str)
OperationKind = Literal["upload", "primary", "secondary"] | NormalizationOperationSlot


class RemoteOperations(Protocol):
    """The registry of one job's remote operations (ADR-0019).

    Bound to the job by the service, which keeps the operation ids durable
    and cancels the job's operations. The core registers each logical call
    around it and sends its id to the Toolbox. ``job_id`` labels the calls.
    """

    job_id: str

    def begin(self, kind: OperationKind) -> str:
        """Register one call and return its operation id, the same across
        retries and a restart; raises when the job is being cancelled, so no
        new call starts."""

    def finish(self, operation_id: str) -> None:
        """Mark the call finished."""


class NoRegionCache:
    """A region cache that stores nothing: every region is described again."""

    async def get(self, content: bytes, variant: str, *, ttl_seconds: int) -> Any | None:
        return None

    async def put(self, content: bytes, variant: str, payload: Any) -> None:
        return None


_Shared = TypeVar("_Shared")


class RunServices:
    """Infrastructure one run shares between its stages and its plan's methods.

    What belongs here (ADR-0029: infrastructure, not planning facts): the
    vision provider breaker, the text-span reader and the progress reporter.
    They serve the enrichment before planning and the methods that run it
    inside the plan (#640, M2), so a provider outage, a fetched page or a
    progress message counts for the whole document.

    What does not: planning decisions, managers, or any dependency a method
    could take as a parameter. Their lifetime is one run of one document: a
    caller builds one ``RunPorts`` per job (``backend/services/run_ports.py``),
    and reusing it for another document would give that document the first
    one's text-span reader.

    ``shared`` builds an object the first time its key is asked for, and
    returns that same object afterwards, whatever arguments the caller's
    factory closes over: the first call wins. The run's plan executes one step
    at a time, so the objects are not shared across threads concurrently.
    """

    def __init__(self) -> None:
        self._items: dict[str, Any] = {}
        #: Reports a progress message from a method running on the executor's
        #: worker thread; set by the orchestrator once it has its event loop,
        #: ``None`` outside a run with a status callback.
        self.progress: Callable[[str], None] | None = None
        #: The run's media inspection, the bootstrap's result, which the
        #: orchestrator loads or computes on every run. The
        #: ``picture-description`` method annotates the text ownership with
        #: it again after it retypes elements (#640, M1), as the stage did
        #: before planning. Not a planning fact: the planner never reads it.
        self.media_inspection: dict[str, Any] | None = None
        #: Persists the manifest a composite method is enriching, mid-step, as
        #: ``step_checkpoint(obligation_id, manifest_payload)`` (#836): set by
        #: the orchestrator to its execution checkpoint, ``None`` outside a job.
        #: Blocking, so a method calls it off its event loop.
        self.step_checkpoint: Callable[[str, dict[str, Any]], None] | None = None

    def shared(self, key: str, build: Callable[[], _Shared]) -> _Shared:
        """The run's object under ``key``, built by ``build`` the first time."""
        if key not in self._items:
            self._items[key] = build()
        return self._items[key]


@dataclass
class RunOutcome:
    """What one run reused or produced, for the service's audit record (#944).

    Mutable and per run: the core records a phase when a checkpoint is reused,
    and the service reads the object after ``execute`` to store the attempt's
    result. ``unknown`` until evidence exists; a caller never infers an origin
    without it. ``producer`` carries the original attempt when the service can
    identify it (a cache hit or a resumed checkpoint may not).
    """

    result_origin: Literal["produced", "cache", "resumed", "unknown"] = "unknown"
    reused_phases: list[str] = field(default_factory=list)
    producer: dict[str, Any] | None = None

    def mark_reused(self, phase: str) -> None:
        """Record that ``phase`` came from a checkpoint of this job."""
        if phase not in self.reused_phases:
            self.reused_phases.append(phase)


@dataclass(frozen=True)
class RunPorts:
    """The service state one run reaches, built by its caller for that job."""

    region_cache: RegionCache
    #: ``None`` outside a job: nothing is checkpointed and nothing resumes.
    checkpoints: JobCheckpoints | None
    #: ``None`` outside a job: the remote calls are neither registered nor
    #: labelled with an operation id, as before ADR-0019.
    operations: RemoteOperations | None
    #: What the run's stages and methods share; a new run gets its own.
    services: RunServices = field(default_factory=RunServices)
    #: What the run reused or produced; the service reads it after the run.
    outcome: RunOutcome = field(default_factory=RunOutcome)

    @classmethod
    def none(cls) -> RunPorts:
        """Ports that keep no state, for a run outside the service."""
        return cls(region_cache=NoRegionCache(), checkpoints=None, operations=None)


def region_cache_for(ports: RunPorts, vision: VisionConfig) -> RegionCache | None:
    """The run's region cache, or ``None`` when the run turns it off
    (``VisionConfig.region_cache_enabled``)."""
    return ports.region_cache if vision.region_cache_enabled else None


__all__ = [
    "CHECKPOINT_PHASES",
    "PHASE_ENRICHED",
    "PHASE_EXECUTION",
    "PHASE_MANIFEST",
    "PHASE_MEDIA",
    "PHASE_PLAN",
    "JobCheckpoints",
    "NoRegionCache",
    "NormalizationOperationSlot",
    "OperationKind",
    "RegionCache",
    "RemoteOperations",
    "RunOutcome",
    "RunPorts",
    "RunServices",
    "region_cache_for",
]
