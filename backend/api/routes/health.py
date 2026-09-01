from __future__ import annotations

import json
import socket
from pathlib import Path

import httpx
from fastapi import APIRouter, Request

from backend.api.limiter import limiter
from backend.api.schemas import HealthResponse
from backend.config.settings import settings
from backend.services.queue_service import unified_queue

router = APIRouter(tags=["health"])


def _get_container_id() -> str:
    """Em Docker, o hostname do container e o container ID."""
    try:
        return socket.gethostname()
    except Exception:
        return ""


def _read_staging_status() -> dict:
    """Le o arquivo de status escrito pelo staging-update.sh (se existir)."""
    status_file = settings.data_dir / "staging-status.json"
    try:
        if status_file.exists():
            return json.loads(status_file.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


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
    staging = _read_staging_status()
    ghcr_latest = staging.get("latest_sha", "")
    last_update = staging.get("last_update", "")
    # update_available: ha imagem nova no GHCR em relacao ao que roda agora.
    # Compara a ultima checagem (ghcr_latest) com o commit da imagem em execucao.
    update_available = bool(ghcr_latest and settings.git_commit and ghcr_latest != settings.git_commit)
    return HealthResponse(
        status="ok",
        model_client=settings.ai_client,
        model_name=model_name,
        model_reachable=await _check_model_reachable(),
        queue_size=unified_queue.qsize(),
        git_commit=settings.git_commit,
        image_tag=settings.image_tag,
        container_id=_get_container_id(),
        image_digest=settings.image_digest,
        ghcr_latest_sha=ghcr_latest,
        last_check=staging.get("last_check", ""),
        last_update=last_update,
        update_available=update_available,
        up_to_date=not update_available and bool(ghcr_latest),
    )
