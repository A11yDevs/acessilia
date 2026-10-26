import asyncio
import secrets
import sqlite3
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from starlette.concurrency import run_in_threadpool

from backend.api import worker
from backend.api.job_auth import require_job_access
from backend.api.limiter import limiter
from backend.api.schemas import CancelResponse, JobStatus, UploadResponse
from backend.api.worker import (
    ApiJob,
    JobExecutor,
    cancel_job_status,
    get_job_status,
    get_job_status_async,
    register_queued_job,
)
from backend.config.settings import settings
from backend.i18n import t
from backend.stage_messages import STAGE_QUEUE_WAITING_POSITION
from backend.log_messages import (
    API_CANCEL_STATE_INVALID,
    API_JOB_QUEUED,
    API_PROMPT_TOO_LONG,
    API_TASK_NOT_FOUND,
    LOG_API_JOB_ENQUEUED,
)
from backend.services.job_store import delete_request, save_request, save_status
from backend.services.blocking import run_blocking
from backend.services.queue_service import QueueItem, unified_queue
from backend.tools.logger import logger
from backend.tools.validators import MSG_FILE_TOO_LARGE, is_email_address_allowed, validate_file

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
                        detail=t(MSG_FILE_TOO_LARGE).format(
                            limit=settings.max_file_size_mb
                        ),
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
            detail=t(API_PROMPT_TOO_LONG).format(limit=MAX_CUSTOM_PROMPT_CHARS),
        )

    if prompt or thinking_mode:
        raise HTTPException(
            status_code=422,
            detail="Custom instructions and thinking mode are unavailable for this pipeline",
        )

    email = (email or "").strip()
    if email and not is_email_address_allowed(email):
        raise HTTPException(status_code=422, detail="Invalid email address")

    file_path = await run_in_threadpool(_save_upload, document_file)
    task_id = uuid.uuid4().hex
    job_token = secrets.token_urlsafe(32)
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
    register_queued_job(task_id, filename, unified_queue.qsize() + 1, source)
    payload = asdict(job)
    payload["file_path"] = str(file_path)
    payload["output_dir"] = str(job.output_dir) if job.output_dir else None
    try:
        await run_blocking(save_request, task_id, job_token, payload, get_job_status(task_id))
        position = await unified_queue.enqueue(item)
    except (Exception, asyncio.CancelledError):
        worker.queued_jobs.pop(task_id, None)
        try:
            await run_blocking(delete_request, task_id)
        finally:
            file_path.unlink(missing_ok=True)
        raise
    status = worker.queued_jobs.get(task_id)
    if status is not None and status.get("status") == "queued":
        status["etapa_atual"] = t(STAGE_QUEUE_WAITING_POSITION).format(position=position)
        try:
            await run_blocking(save_status, task_id, status)
        except sqlite3.Error as exc:
            # Acceptance is already durable and the job is in the queue. An
            # auxiliary position update must not prevent returning its token.
            logger.warning("Could not persist queue position for job {}: {}", task_id, exc)
    logger.info(t(LOG_API_JOB_ENQUEUED).format(task_id=task_id, source=source))
    return UploadResponse(
        task_id=task_id,
        job_token=job_token,
        position=position,
        message=t(API_JOB_QUEUED).format(position=position),
    )


@router.get(
    "/{task_id}", response_model=JobStatus, dependencies=[Depends(require_job_access)]
)
@limiter.limit("60/minute")
async def job_status(request: Request, task_id: str):
    job = await get_job_status_async(task_id)
    if job is None:
        raise HTTPException(status_code=404, detail=t(API_TASK_NOT_FOUND))
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
        email_delivery=job.get("email_delivery"),
    )


@router.post(
    "/{task_id}/cancel",
    response_model=CancelResponse,
    dependencies=[Depends(require_job_access)],
)
@limiter.limit("10/minute")
async def cancel_job(request: Request, task_id: str):
    if not cancel_job_status(task_id):
        job = await get_job_status_async(task_id)
        if job is None:
            raise HTTPException(status_code=404, detail=t(API_TASK_NOT_FOUND))
        raise HTTPException(
            status_code=409,
            detail=t(API_CANCEL_STATE_INVALID).format(status=job["status"]),
        )
    status = await get_job_status_async(task_id)
    await run_blocking(save_status, task_id, status)
    return CancelResponse(task_id=task_id, status=status["status"])
