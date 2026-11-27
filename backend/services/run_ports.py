"""The service state a run reaches, as the core's ``RunPorts`` (ADR-0016, step 4)."""

from __future__ import annotations

from acessilia_core.ports import RunOutcome, RunPorts
from backend.config.settings import settings
from backend.services.cache import ContentCache
from backend.services.job_checkpoint import FileJobCheckpoints
from backend.services.operation_registry import JobOperations


def checkpoint_options() -> dict[str, dict[str, str]]:
    """The service's processing options a job's checkpoints depend on (#549):
    the revision of the model weights behind the configured provider, which
    the enrichment and the execution use. The orchestrator stamps its own
    planner and dry-run options; the rest are in the run's ``CoreConfig``."""
    revision = {"processing_model_revision": settings.processing_model_revision}
    return {"enrichment": revision, "execution": revision}


def service_run_ports(
    task_id: str | None = None, *, outcome: RunOutcome | None = None
) -> RunPorts:
    """The ports of a run the service hosts: the region cache on its file
    cache and, inside a job (``task_id``), that job's checkpoints and
    registry of remote operations. A run without a job (the pipeline
    scripts) has neither.

    ``outcome`` is the attempt's mutable result record (#944); a run without
    one gets a fresh object that nobody reads.
    """
    return RunPorts(
        region_cache=ContentCache(),
        checkpoints=FileJobCheckpoints(task_id, checkpoint_options()) if task_id else None,
        operations=JobOperations(task_id) if task_id else None,
        outcome=outcome or RunOutcome(),
    )


__all__ = ["service_run_ports"]
