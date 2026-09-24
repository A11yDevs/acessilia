from pathlib import Path
from secrets import compare_digest

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse

from backend.api.limiter import limiter
from backend.config.settings import settings


def _require_token(authorization: str | None = Header(default=None)) -> None:
    if not settings.logs_api_token:
        raise HTTPException(status_code=503, detail="Consulta de logs não configurada")

    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not compare_digest(token, settings.logs_api_token):
        raise HTTPException(status_code=401, detail="Token inválido")


router = APIRouter(tags=["logs"], dependencies=[Depends(_require_token)])


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
