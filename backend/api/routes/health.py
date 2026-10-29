from __future__ import annotations

import json
import socket
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Request

from acessilia_sdk.toolbox import vlm_provider_healthy
from backend.ai.models.ai_client import active_model_name
from backend.api.limiter import limiter
from backend.api.schemas import HealthResponse
from backend.config.settings import settings
from backend.services.queue_service import unified_queue
from backend.tools.toolbox_client import toolbox_vlm_endpoint

router = APIRouter(tags=["health"])

#: The auto-update timer runs every 300 s (UPDATE_INTERVAL in scripts/ops.sh);
#: like `ops.sh auto-update check`, a last check older than three intervals means
#: the updater stopped, so its view of GHCR can no longer vouch for the image.
#: If UPDATE_INTERVAL changes in ops.sh, update this too, or /health reports
#: false staleness between legitimate checks.
UPDATE_CHECK_STALE_SECONDS = 3 * 300

#: The Toolbox gives the VLM server 10 s to answer its own health probe, so the
#: 3 s of the other clients would report a slow but healthy model as down. The
#: container's healthcheck gives this whole route 10 s (docker-compose*.yml),
#: which caps the wait below the Toolbox's.
TOOLBOX_VLM_HEALTH_TIMEOUT_SECONDS = 8.0


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
            status = json.loads(status_file.read_text(encoding="utf-8"))
            if isinstance(status, dict):
                return status
    except Exception:
        pass
    return {}


def _staging_str(staging: dict, key: str) -> str:
    """A string field of the status file; any other value (a malformed writer)
    becomes its text, so /health reports it instead of failing on it."""
    value = staging.get(key)
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def _update_check_is_stale(last_check: str, now: datetime | None = None) -> bool:
    """Whether the updater's last check is too old (or unreadable) to trust.

    An empty ``last_check`` means no updater reports here at all (local runs,
    deployments without the timer), which is not a stale check.
    """
    if not last_check:
        return False
    try:
        checked = datetime.fromisoformat(last_check)
    except ValueError:
        return True
    if checked.tzinfo is None:
        return True
    age = ((now or datetime.now(UTC)) - checked).total_seconds()
    return age > UPDATE_CHECK_STALE_SECONDS


async def _check_model_reachable() -> bool:
    if settings.ai_client == "toolbox":
        return await vlm_provider_healthy(
            toolbox_vlm_endpoint(),
            settings.toolbox_vlm_provider,
            api_key=settings.toolbox_api_key,
            timeout_seconds=TOOLBOX_VLM_HEALTH_TIMEOUT_SECONDS,
        )
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
    model_name = active_model_name()
    staging = _read_staging_status()
    ghcr_latest = _staging_str(staging, "latest_digest")
    running_digest = _staging_str(staging, "running_digest") or settings.image_digest
    last_update = _staging_str(staging, "last_update")
    last_check = _staging_str(staging, "last_check")
    # update_available: there is a newer image on GHCR than the one currently running.
    # Compares the last check (ghcr_latest) with the commit of the running image.
    update_available = bool(ghcr_latest and running_digest and ghcr_latest != running_digest)
    # ghcr_latest is only as fresh as last_check: with the updater failing, it kept
    # the digest seen before the failure and up_to_date stayed true for hours
    # while a newer image waited on GHCR.
    update_check_stale = _update_check_is_stale(last_check)
    return HealthResponse(
        status="ok",
        model_client=settings.ai_client,
        model_name=model_name,
        model_reachable=await _check_model_reachable(),
        queue_size=unified_queue.qsize(),
        git_commit=settings.git_commit,
        image_tag=settings.image_tag,
        container_id=_get_container_id(),
        image_digest=running_digest,
        ghcr_latest_sha=ghcr_latest,
        last_check=last_check,
        last_update=last_update,
        update_available=update_available,
        update_check_stale=update_check_stale,
        up_to_date=not update_available and bool(ghcr_latest) and not update_check_stale,
    )
