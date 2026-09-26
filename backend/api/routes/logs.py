from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from backend.api.limiter import limiter
from backend.api.observability_auth import require_observability_token
from backend.config.settings import settings


router = APIRouter(tags=["logs"], dependencies=[Depends(require_observability_token)])


def _log_files() -> list[Path]:
    return sorted(
        (
            path for path in settings.logs_dir.glob("bot_*")
            if path.is_file() and not path.is_symlink()
            and path.name.endswith((".log", ".zip"))
        ),
        key=lambda path: path.name,
        reverse=True,
    )


@router.get("/logs")
@limiter.limit("30/minute")
def list_logs(request: Request):
    return {"files": [
        {"name": path.name, "size_bytes": path.stat().st_size}
        for path in _log_files()
    ]}


@router.get("/logs/{filename}")
@limiter.limit("30/minute")
def download_log(request: Request, filename: str):
    path = next((path for path in _log_files() if path.name == filename), None)
    if path is None:
        raise HTTPException(status_code=404, detail="Log não encontrado")
    return FileResponse(path, filename=path.name)
