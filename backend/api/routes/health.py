from __future__ import annotations

import httpx
from fastapi import APIRouter, Request

from backend.api.limiter import limiter
from backend.api.schemas import HealthResponse
from backend.config.settings import settings
from backend.services.queue_service import unified_queue

router = APIRouter(tags=["health"])


async def _check_model_reachable() -> bool:
    try:
        async with httpx.AsyncClient(timeout=3.0) as http:
            if settings.ai_client == "ollama":
                url = settings.ollama_base_url.replace("/api/chat", "/api/tags")
                response = await http.get(url)
                return response.status_code == 200
            url = settings.openrouter_base_url.replace("/chat/completions", "")
            response = await http.get(url)
            return response.status_code < 500
    except Exception:
        return False


@router.get("/health", response_model=HealthResponse)
@limiter.limit("30/minute")
async def health(request: Request):
    model_name = (
        settings.ollama_model
        if settings.ai_client == "ollama"
        else settings.openrouter_model
    )
    return HealthResponse(
        status="ok",
        model_client=settings.ai_client,
        model_name=model_name,
        model_reachable=await _check_model_reachable(),
        queue_size=unified_queue.qsize(),
        git_commit=settings.git_commit,
        image_tag=settings.image_tag,
    )
