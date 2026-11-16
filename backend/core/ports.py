"""What a run needs from the service that hosts it (ADR-0016, step 4).

The core does not own the service's state: its caches, its job checkpoints
and its registry of remote operations live in ``backend/services``. A run
receives them as ``RunPorts``, built by its caller for that job, so the core
does not import them. The region cache is a port now; the checkpoints and
the remote operations follow in step 4's next pull requests, and
``tests/test_run_ports.py`` lists the service imports still pending.

Every port has a no-op implementation here, which ``RunPorts.none()``
gathers: a script or a test that hosts no service state runs with it.
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

    @classmethod
    def none(cls) -> RunPorts:
        """Ports that keep no state, for a run outside the service."""
        return cls(region_cache=NoRegionCache())


def region_cache_for(ports: RunPorts, vision: VisionConfig) -> RegionCache | None:
    """The run's region cache, or ``None`` when the run turns it off
    (``VisionConfig.region_cache_enabled``)."""
    return ports.region_cache if vision.region_cache_enabled else None


__all__ = ["NoRegionCache", "RegionCache", "RunPorts", "region_cache_for"]
