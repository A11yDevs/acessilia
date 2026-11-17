"""What a run needs from the service that hosts it (ADR-0016, step 4).

The core does not own the service's state: its caches, its job checkpoints
and its registry of remote operations live in ``backend/services``. A run
receives them as ``RunPorts``, built by its caller for that job, so the core
does not import them. The region cache and the job checkpoints are ports
now; the remote operations follow in step 4's next pull request, and
``tests/test_run_ports.py`` lists the service imports still pending.

``RunPorts.none()`` keeps no state, for a script or a test that hosts no
service: its region cache stores nothing, and it has no job, so no
checkpoints.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from backend.core.config import VisionConfig


class RegionCache(Protocol):
    """Stored answers for a region image, keyed on its content and a variant.

    The variant names everything else the answer depends on (the prompt, the
    model, the budget, the locale); the core builds it with
    :func:`backend.core.cache_keys.options_cache_key`.
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
    Methods are blocking: the core runs them off the event loop.
    """

    job_id: str

    def load(self, phase: str) -> dict[str, Any] | None:
        """The phase's payload, ``None`` when absent; raises when it exists
        but cannot be trusted, so the phase is not resumed from it."""

    def save(self, phase: str, payload: dict[str, Any]) -> None:
        """Store the phase's JSON-ready payload, replacing the previous one."""

    def remove(self, phase: str) -> None:
        """Drop the phase's payload, if any."""


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

    @classmethod
    def none(cls) -> RunPorts:
        """Ports that keep no state, for a run outside the service."""
        return cls(region_cache=NoRegionCache(), checkpoints=None)


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
    "RegionCache",
    "RunPorts",
    "region_cache_for",
]
