import shutil
import zipfile
import uuid
import traceback
from pathlib import Path

from fastapi import (
    FastAPI,
    File,
    UploadFile,
    Form,
    Request,
    HTTPException,
)
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from core.orchestrator import process
from core.exporters.txt_exporter import export_txt
from core.exporters.docx_exporter import export_docx
from core.exporters.pdf_exporter import export_pdf
from core.exporters.audio_exporter import export_mp3
from adapters.exporters import export_txt, export_docx, export_pdf, export_mp3
from core.utils.logger import logger
from exporters.pandoc_exporter import export_accessible_document
from config.settings import settings
from core.services.email_service import send_confirmation_email, send_result_email
from core.services.download_token_service import (
    criar_token,
    obter_info_token,
    limpar_tokens_expirados,
)

import asyncio
import concurrent.futures
from core.services.queue_service import unified_queue, QueueItem

app = FastAPI(title="Bot Acess Web Panel")

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
app.state.limiter = limiter

executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)

BASE_WEB_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_WEB_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_WEB_DIR / "static")), name="static")


@app.on_event("startup")
async def startup_event():
    unified_queue.start_worker()
    await limpar_tokens_expirados()


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Erro Global no Painel Web: {} | Path: {}", exc, request.url.path)
    logger.error(traceback.format_exc())
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"error": f"Erro interno no servidor: {str(exc)}"},
        status_code=500,
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    logger.warning(
        "HTTP Exception no Painel Web: {} | Path: {}", exc.detail, request.url.path
    )
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"error": exc.detail},
        status_code=exc.status_code,
    )


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    logger.warning(
        "Rate limit excedido | IP: {} | Path: {}",
        request.client.host if request.client else "unknown",
        request.url.path,
    )
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"error": "Muitas requisições. Aguarde um momento antes de tentar novamente."},
        status_code=429,
    )


OUTPUT_DIR = settings.temp_dir / "web_output"
UPLOAD_DIR = settings.temp_dir / "uploads"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/", response_class=HTMLResponse)
@limiter.limit("30/minute")
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={})


@app.get("/advanced", response_class=HTMLResponse)
@limiter.limit("30/minute")
async def advanced_page(request: Request):
    return templates.TemplateResponse(request=request, name="advanced.html", context={})


async def run_pipeline_task(
    email: str,
    file_path: Path,
    filename: str,
    custom_prompt: str | None = None,
    thinking_mode: bool = False,
):
    try:
        await send_confirmation_email(email, filename)

        async def silent_status(msg: str):
            logger.debug("Web Pipeline Status [{}]: {}", filename, msg)

        canonical_doc = await process(
            file_path,
            status_callback=silent_status,
            custom_prompt=custom_prompt,
            thinking_mode=thinking_mode,
        )

        base_name = file_path.stem
        task_output_dir = OUTPUT_DIR / base_name
        task_output_dir.mkdir(parents=True, exist_ok=True)

        txt_path = task_output_dir / f"{base_name}.txt"
        docx_path = task_output_dir / f"{base_name}.docx"
        pdf_path = task_output_dir / f"{base_name}.pdf"
        html_path = task_output_dir / f"{base_name}.html"
        mp3_path = task_output_dir / f"{base_name}.mp3"

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            executor, export_txt, canonical_doc, txt_path, filename
        )
        await loop.run_in_executor(
            executor, export_docx, canonical_doc, docx_path, filename
        )
        await loop.run_in_executor(
            executor, export_pdf, canonical_doc, pdf_path, filename
        )
        await loop.run_in_executor(
            executor,
            lambda: export_accessible_document(
                canonical_doc,
                html_path,
                format_name="html",
                title=base_name,
                profile_name="html",
            ),
        )

        if txt_path.exists():
            clean_text = txt_path.read_text(encoding="utf-8")
            await export_mp3(clean_text, mp3_path)

        zip_path = task_output_dir / f"{base_name}_acessivel.zip"
        files_to_zip = [txt_path, docx_path, pdf_path, html_path, mp3_path]

        def create_zip():
            with zipfile.ZipFile(
                zip_path, "w", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                for f_path in files_to_zip:
                    if f_path.exists():
                        archive.write(f_path, arcname=f_path.name)

        await loop.run_in_executor(executor, create_zip)

        token = await criar_token(task_output_dir, filename)
        download_url = f"{settings.web_url.rstrip('/')}/download/{token}"
        await send_result_email(email, filename, download_url=download_url)

        logger.info("Web Task concluída para {}. E-mail enviado.", email)

    except Exception as e:
        logger.exception("Erro no processamento via Web para {}: {}", email, e)
    finally:
        if file_path.exists():
            file_path.unlink()


@app.get("/download/{token}")
@limiter.limit("10/minute")
async def download_page(request: Request, token: str):
    info = await obter_info_token(token)
    if info is None:
        raise HTTPException(status_code=404, detail="Link inválido ou expirado")
    return templates.TemplateResponse(
        request=request,
        name="download.html",
        context={"filename": info["filename"], "formats": info["formats"]},
    )


@app.get("/download/{token}/{format}")
@limiter.limit("20/minute")
async def download_file(request: Request, token: str, format: str):
    if format not in ("txt", "docx", "pdf", "html", "mp3", "zip"):
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
    media_types = {
        "txt": "text/plain; charset=utf-8",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pdf": "application/pdf",
        "html": "text/html; charset=utf-8",
        "mp3": "audio/mpeg",
        "zip": "application/zip",
    }
    return FileResponse(
        path=file_path,
        filename=file_path.name,
        media_type=media_types.get(format, "application/octet-stream"),
    )


@app.post("/process", response_class=HTMLResponse)
@limiter.limit("5/minute")
async def handle_upload(
    request: Request, email: str = Form(...), document_file: UploadFile = File(...)
):
    try:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        original_filename = document_file.filename
        # Preserve only the basename to avoid directory traversal
        safe_name = f"{uuid.uuid4().hex}{Path(original_filename).suffix}"
        file_path = UPLOAD_DIR / safe_name

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(document_file.file, buffer)

        item = QueueItem(
            file_path=file_path,
            filename=document_file.filename,
            source="web",
            callback=run_pipeline_task,
            callback_args={
                "email": email,
                "file_path": file_path,
                "filename": document_file.filename,
            },
        )
        pos = await unified_queue.enqueue(item)

        msg = f"Sucesso! Seu arquivo está na fila única (Posição: {pos}). O resultado será enviado para {email}."

        return templates.TemplateResponse(
            request=request, name="index.html", context={"message": msg}
        )
    except Exception as e:
        logger.error("Erro no upload web: {}", e)
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "error": "Ocorreu um erro ao processar o upload. Tente novamente."
            },
        )


@app.post("/advanced/process", response_class=HTMLResponse)
@limiter.limit("5/minute")
async def handle_advanced_upload(
    request: Request,
    email: str = Form(...),
    document_file: UploadFile = File(...),
    custom_prompt: str = Form(""),
    thinking_mode: bool = Form(False),
):
    try:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        original_filename = document_file.filename
        # Preserve only the basename to avoid directory traversal
        safe_name = f"{uuid.uuid4().hex}{Path(original_filename).suffix}"
        file_path = UPLOAD_DIR / safe_name

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(document_file.file, buffer)

        prompt = custom_prompt.strip()
        if len(prompt) > 6000:
            return templates.TemplateResponse(
                request=request,
                name="advanced.html",
                context={
                    "error": "Prompt personalizado excede o limite de 6000 caracteres."
                },
            )

        item = QueueItem(
            file_path=file_path,
            filename=document_file.filename,
            source="web",
            callback=run_pipeline_task,
            callback_args={
                "email": email,
                "file_path": file_path,
                "filename": document_file.filename,
                "custom_prompt": prompt or None,
                "thinking_mode": thinking_mode,
            },
        )
        pos = await unified_queue.enqueue(item)

        msg = f"Sucesso! Seu arquivo está na fila única (Posição: {pos}). O resultado será enviado para {email}."

        return templates.TemplateResponse(
            request=request, name="advanced.html", context={"message": msg}
        )
    except Exception as e:
        logger.error("Erro no upload advanced web: {}", e)
        return templates.TemplateResponse(
            request=request,
            name="advanced.html",
            context={
                "error": "Ocorreu um erro ao processar o upload. Tente novamente."
            },
        )
