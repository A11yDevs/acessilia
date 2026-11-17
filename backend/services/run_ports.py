"""The service state a run reaches, as the core's ``RunPorts`` (ADR-0016, step 4)."""

from __future__ import annotations

from backend.core.ports import RunPorts
from backend.services.cache import ContentCache
from backend.services.job_checkpoint import FileJobCheckpoints
from backend.services.operation_registry import JobOperations


def service_run_ports(task_id: str | None = None) -> RunPorts:
    """The ports of a run the service hosts: the region cache on its file
    cache and, inside a job (``task_id``), that job's checkpoints and
    registry of remote operations. A run without a job (the pipeline
    scripts) has neither."""
    return RunPorts(
        region_cache=ContentCache(),
        checkpoints=FileJobCheckpoints(task_id) if task_id else None,
        operations=JobOperations(task_id) if task_id else None,
    )


__all__ = ["service_run_ports"]
