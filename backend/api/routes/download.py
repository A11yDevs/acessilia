from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from backend.api.limiter import limiter
from backend.api.schemas import DownloadFormat, DownloadInfo
from backend.services.download_token_service import obter_info_token

router = APIRouter(prefix="/download", tags=["download"])

MEDIA_TYPES = {
    "txt": "text/plain; charset=utf-8",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "html": "text/html; charset=utf-8",
    "mp3": "audio/mpeg",
    "zip": "application/zip",
}


@router.get("/{token}", response_model=DownloadInfo)
@limiter.limit("10/minute")
async def download_info(request: Request, token: str):
    info = await obter_info_token(token)
    if info is None:
        raise HTTPException(status_code=404, detail="Link inválido ou expirado")
    return DownloadInfo(
        filename=info["filename"],
        stem=info["stem"],
        criado_em=info["criado_em"],
        formats=[DownloadFormat(**f) for f in info["formats"]],
    )


@router.get("/{token}/{format}")
@limiter.limit("20/minute")
async def download_file(request: Request, token: str, format: str):
    if format not in MEDIA_TYPES:
        raise HTTPException(status_code=400, detail="Formato inválido")
    info = await obter_info_token(token)
    if info is None:
        raise HTTPException(status_code=404, detail="Link inválido ou expirado")
    file_path = None
    for f in info["formats"]:
        if f["ext"] == format:
            file_path = Path(f["file_path"])
            break
    if file_path is None or not file_path.exists():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    return FileResponse(
        path=file_path,
        filename=file_path.name,
        media_type=MEDIA_TYPES[format],
    )
