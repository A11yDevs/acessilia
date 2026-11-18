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

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

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


#: The remote calls of an extraction a job can cancel (ADR-0019).
OperationKind = Literal["upload", "primary", "secondary"]


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


@dataclass(frozen=True)
class RunPorts:
    """The service state one run reaches, built by its caller for that job."""

    region_cache: RegionCache
    #: ``None`` outside a job: nothing is checkpointed and nothing resumes.
    checkpoints: JobCheckpoints | None
    #: ``None`` outside a job: the remote calls are neither registered nor
    #: labelled with an operation id, as before ADR-0019.
    operations: RemoteOperations | None

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
    "OperationKind",
    "RegionCache",
    "RemoteOperations",
    "RunPorts",
    "region_cache_for",
]
