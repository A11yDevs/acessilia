import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from backend.api.limiter import limiter
from backend.api.schemas import CancelResponse, JobStatus, UploadResponse
from backend.api.worker import (
    ApiJob,
    JobExecutor,
    cancel_job_status,
    get_job_status,
    register_queued_job,
)
from backend.config.settings import settings
from backend.services.queue_service import QueueItem, unified_queue
from backend.tools.logger import logger
from backend.tools.validators import validate_file

router = APIRouter(prefix="/jobs", tags=["jobs"])

job_executor = JobExecutor()

MAX_CUSTOM_PROMPT_CHARS = 6000
_UPLOAD_CHUNK = 1024 * 1024


def _save_upload(upload: UploadFile) -> Path:
    upload_dir = settings.temp_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex}{Path(upload.filename or '').suffix.lower()}"
    file_path = upload_dir / safe_name
    total = 0
    try:
        with open(file_path, "wb") as buffer:
            while chunk := upload.file.read(_UPLOAD_CHUNK):
                total += len(chunk)
                if total > settings.max_file_size_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Arquivo muito grande. Limite: {settings.max_file_size_mb} MB.",
                    )
                buffer.write(chunk)
    except Exception:
        file_path.unlink(missing_ok=True)
        raise
    return file_path


@router.post("", response_model=UploadResponse, status_code=202)
@limiter.limit("5/minute")
async def submit_job(
    request: Request,
    document_file: UploadFile = File(...),
    mode: str = Form("normal"),
    custom_prompt: str = Form(""),
    thinking_mode: bool = Form(False),
    email: str = Form(""),
    source: str = Form("api"),
):
    filename = Path(document_file.filename or "documento").name
    valid, error_msg = validate_file(filename, settings.max_file_size_bytes)
    if not valid:
        raise HTTPException(status_code=400, detail=error_msg)

    prompt = custom_prompt.strip()
    if len(prompt) > MAX_CUSTOM_PROMPT_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"Prompt personalizado excede o limite de {MAX_CUSTOM_PROMPT_CHARS} caracteres.",
        )

    file_path = _save_upload(document_file)
    task_id = uuid.uuid4().hex[:8]
    job = ApiJob(
        task_id=task_id,
        file_path=file_path,
        filename=filename,
        mode=mode,
        custom_prompt=prompt or None,
        thinking_mode=thinking_mode,
        email=email or None,
        source=source,
    )
    item = QueueItem(
        file_path=file_path,
        filename=filename,
        source=source,
        task_id=task_id,
        callback=job_executor.run,
        callback_args={"job": job},
    )
    position = await unified_queue.enqueue(item)
    register_queued_job(task_id, filename, position, source, mode)
    logger.info("API: job {} enfileirado (source={})", task_id, source)
    return UploadResponse(
        task_id=task_id,
        position=position,
        message=f"Arquivo na fila (Posição: {position}).",
    )


@router.get("/{task_id}", response_model=JobStatus)
@limiter.limit("60/minute")
async def job_status(request: Request, task_id: str):
    job = get_job_status(task_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return JobStatus(
        task_id=job["task_id"],
        arquivo=job.get("arquivo", ""),
        status=job.get("status", "unknown"),
        progresso=job.get("progresso", 0.0),
        etapa_atual=job.get("etapa_atual", ""),
        erros=job.get("erros", []),
        download_url=job.get("download_url"),
        criado_em=job.get("inicio"),
        fim=job.get("fim"),
    )


@router.post("/{task_id}/cancel", response_model=CancelResponse)
@limiter.limit("10/minute")
async def cancel_job(request: Request, task_id: str):
    if not cancel_job_status(task_id):
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return CancelResponse(task_id=task_id, status="cancelled")
