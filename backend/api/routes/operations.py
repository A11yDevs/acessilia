"""Privileged API operations, authenticated by ``OPERATIONS_API_TOKEN``.

The read-only audit routes live in ``backend/api/routes/audit.py`` with their
own token (#946); this router keeps only the write-capable operations.
"""

from fastapi import APIRouter, Depends, Request

from backend.api.limiter import limiter
from backend.api.operations_auth import require_operations_token
from backend.services.cache import clear_cache

router = APIRouter(
    tags=["operations"], dependencies=[Depends(require_operations_token)]
)


@router.post("/cache/clear")
@limiter.limit("10/minute")
async def clear_processing_cache(request: Request) -> dict[str, int]:
    """Remove the published processing cache entries and report how many went."""
    return {"removed": await clear_cache()}


__all__ = ["router"]
