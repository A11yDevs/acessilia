"""Privileged API operations, authenticated by ``OPERATIONS_API_TOKEN``."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from acessilia_core.blocking import run_blocking
from acessilia_core.i18n import t
from acessilia_core.i18n.log_messages import API_TASK_NOT_FOUND
from backend.api.limiter import limiter
from backend.api.operations_auth import require_operations_token
from backend.services.cache import clear_cache
from backend.services.job_store import load_record

router = APIRouter(
    tags=["operations"], dependencies=[Depends(require_operations_token)]
)


@router.post("/cache/clear")
@limiter.limit("10/minute")
async def clear_processing_cache(request: Request) -> dict[str, int]:
    """Remove the published processing cache entries and report how many went."""
    return {"removed": await clear_cache()}


@router.get("/operations/jobs/{task_id}/configuration")
@limiter.limit("60/minute")
async def job_configuration(request: Request, task_id: str) -> dict[str, Any]:
    """The effective configuration the job's run used (#380, Etapa 0).

    Written once at the job's start and kept with its durable record, so a
    result can be audited after the processing cache entry is gone. It is
    privileged: the ``environment`` group names internal paths and endpoints.
    """
    record = await run_blocking(load_record, task_id)
    configuration = record.get("configuration") if record else None
    if configuration is None:
        raise HTTPException(status_code=404, detail=t(API_TASK_NOT_FOUND))
    return configuration


__all__ = ["router"]
