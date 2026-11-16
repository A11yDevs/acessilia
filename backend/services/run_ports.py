"""The service state a run reaches, as the core's ``RunPorts`` (ADR-0016, step 4)."""

from __future__ import annotations

from backend.core.ports import RunPorts
from backend.services.cache import ContentCache


def service_run_ports() -> RunPorts:
    """The ports of a run the service hosts: the region cache on its file cache."""
    return RunPorts(region_cache=ContentCache())


__all__ = ["service_run_ports"]
