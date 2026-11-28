"""Read-only audit routes for the effective configuration and its attempts (#946).

The routes are separate from the operations API on purpose: ``AUDIT_API_TOKEN``
can read, while ``OPERATIONS_API_TOKEN`` keeps its write-capable routes (cache
clearing). The audit record is minimised and stored per attempt (#944); these
routes only read it and never rewrite the immutable configuration snapshot.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from acessilia_core.blocking import run_blocking
from acessilia_core.i18n import t
from acessilia_core.i18n.log_messages import API_TASK_NOT_FOUND
from backend.api.audit_auth import require_audit_token
from backend.api.limiter import limiter
from backend.services.job_store import load_audit_view

router = APIRouter(tags=["audit"], dependencies=[Depends(require_audit_token)])


@router.get("/audit/jobs/{task_id}/configuration")
@limiter.limit("60/minute")
async def job_configuration(
    request: Request, response: Response, task_id: str
) -> dict[str, Any]:
    """The latest attempt of a job, with its result provenance (#944).

    ``current`` is true when the latest persisted attempt is the job's current
    one, false when a later attempt started but its snapshot could not be
    written, and null for a legacy record written before attempts existed.
    """
    record, attempts = await run_blocking(load_audit_view, task_id)
    if record is None:
        raise HTTPException(status_code=404, detail=t(API_TASK_NOT_FOUND))
    latest = attempts[-1] if attempts else None
    if latest is None:
        configuration = record.get("configuration")
        if configuration is None:
            raise HTTPException(status_code=404, detail=t(API_TASK_NOT_FOUND))
        # A record from the version before per-attempt snapshots (#942).
        response.headers["Cache-Control"] = "no-store"
        return _legacy_response(configuration)
    response.headers["Cache-Control"] = "no-store"
    return _attempt_response(record, latest, latest)


@router.get("/audit/jobs/{task_id}/configuration/attempts")
@limiter.limit("30/minute")
async def job_attempts(
    request: Request, response: Response, task_id: str
) -> dict[str, Any]:
    """Every attempt of a job, oldest first, with its immutable configuration."""
    record, attempts = await run_blocking(load_audit_view, task_id)
    if record is None:
        raise HTTPException(status_code=404, detail=t(API_TASK_NOT_FOUND))
    latest = attempts[-1] if attempts else None
    response.headers["Cache-Control"] = "no-store"
    if latest is None:
        return {
            "current_attempt_id": _current_attempt_id(record, None),
            "attempts": [],
        }
    return {
        "current_attempt_id": _current_attempt_id(record, latest),
        "attempts": [
            _attempt_response(record, attempt, latest) for attempt in attempts
        ],
    }


def _attempt_response(
    record: dict[str, Any],
    attempt: dict[str, Any],
    latest: dict[str, Any],
) -> dict[str, Any]:
    """The stored configuration with the attempt's result merged in for reading.

    The merge is a copy: the persisted snapshot is immutable. ``current`` is
    computed from the job's marker, falling back to the status written at the
    attempt's start when the atomic pointer update was the one that failed.
    """
    configuration = dict(attempt["configuration"])
    attempt_meta = dict(configuration.get("attempt") or {})
    attempt_meta.update(
        {
            "id": attempt["attempt_id"],
            "captured_at": attempt["captured_at"],
            "resumed": attempt["resumed"],
            "state": attempt["state"],
            "finished_at": attempt["finished_at"],
        }
    )
    configuration["attempt"] = attempt_meta
    provenance = dict(configuration.get("provenance") or {})
    provenance["result_origin"] = attempt["origin"]
    provenance["reused_phases"] = attempt["reused_phases"]
    configuration["provenance"] = provenance
    current = _current_attempt_id(record, latest)
    configuration["current"] = None if current is None else current == attempt["attempt_id"]
    return configuration


def _legacy_response(configuration: dict[str, Any]) -> dict[str, Any]:
    """A #942 record, filled with the documented fields that did not exist yet."""
    response = dict(configuration)
    attempt = dict(response.get("attempt") or {})
    attempt.setdefault("state", None)
    attempt.setdefault("finished_at", None)
    response["attempt"] = attempt
    provenance = dict(response.get("provenance") or {})
    provenance.setdefault("result_origin", "unknown")
    provenance.setdefault("reused_phases", [])
    response["provenance"] = provenance
    response["current"] = None
    return response


def _current_attempt_id(
    record: dict[str, Any], latest: dict[str, Any] | None
) -> str | None:
    """The job's current attempt, preferring a status marker newer than ``latest``.

    The worker writes the status marker before the atomic snapshot + column
    update. If the snapshot write failed, the status names an attempt newer
    than the latest persisted snapshot; that is the stale case. If the status
    write failed but the snapshot succeeded, the column points at ``latest``.
    """
    status = record.get("status") or {}
    status_id = status.get("current_attempt_id")
    status_at = status.get("current_attempt_captured_at")
    if (
        status_id
        and status_at
        and latest is not None
        and str(status_at) >= str(latest["captured_at"])
    ):
        return str(status_id)
    current = record.get("current_attempt_id")
    if current:
        return str(current)
    return str(status_id) if status_id else None


__all__ = ["router"]
