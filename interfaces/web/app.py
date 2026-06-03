import shutil
import zipfile
import os
import uuid
import traceback
from pathlib import Path
from typing import List

from fastapi import FastAPI, File, UploadFile, Form, BackgroundTasks, Request, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, FileResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.orchestrator import process
from core.exporters.txt_exporter import export_txt
from core.exporters.docx_exporter import export_docx
from core.exporters.pdf_exporter import export_pdf
from core.exporters.audio_exporter import export_mp3
from core.utils.logger import logger
from exporters.pandoc_exporter import export_accessible_document
from config.settings import settings
from core.services.email_service import send_confirmation_email, send_result_email
from core.services.download_token_service import criar_token, consumir_token, limpar_tokens_expirados

import asyncio
import concurrent.futures
from core.services.queue_service import unified_queue, QueueItem

app = FastAPI(title="Bot Acess Web Panel")

executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)

BASE_WEB_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_WEB_DIR / "templates"))


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
        status_code=500
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    logger.warning("HTTP Exception no Painel Web: {} | Path: {}", exc.detail, request.url.path)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"error": exc.detail},
        status_code=exc.status_code
    )

OUTPUT_DIR = settings.temp_dir / "web_output"
UPLOAD_DIR = settings.temp_dir / "uploads"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request=request, name="index.html", context={}
    )


async def run_pipeline_task(email: str, file_path: Path, filename: str):
    try:
        await send_confirmation_email(email, filename)
        
        async def silent_status(msg: str):
            logger.debug("Web Pipeline Status [{}]: {}", filename, msg)
            
        canonical_doc = await process(file_path, status_callback=silent_status)
        
        base_name = file_path.stem
        task_output_dir = OUTPUT_DIR / base_name
        task_output_dir.mkdir(parents=True, exist_ok=True)
        
        txt_path = task_output_dir / f"{base_name}.txt"
        docx_path = task_output_dir / f"{base_name}.docx"
        pdf_path = task_output_dir / f"{base_name}.pdf"
        html_path = task_output_dir / f"{base_name}.html"
        mp3_path = task_output_dir / f"{base_name}.mp3"
        
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(executor, export_txt, canonical_doc, txt_path, filename)
        await loop.run_in_executor(executor, export_docx, canonical_doc, docx_path, filename)
        await loop.run_in_executor(executor, export_pdf, canonical_doc, pdf_path, filename)
        await loop.run_in_executor(
            executor, 
            lambda: export_accessible_document(
                canonical_doc, 
                html_path, 
                format_name="html", 
                title=base_name, 
                profile_name="html"
            )
        )
        
        if txt_path.exists():
            clean_text = txt_path.read_text(encoding="utf-8")
            await export_mp3(clean_text, mp3_path)
            
        zip_path = task_output_dir / f"{base_name}_acessivel.zip"
        files_to_zip = [txt_path, docx_path, pdf_path, html_path, mp3_path]
        
        def create_zip():
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for f_path in files_to_zip:
                    if f_path.exists():
                        archive.write(f_path, arcname=f_path.name)
        
        await loop.run_in_executor(executor, create_zip)

        token = await criar_token(zip_path)
        download_url = f"{settings.web_url.rstrip('/')}/download/{token}"
        await send_result_email(email, filename, download_url=download_url)

        logger.info("Web Task concluída para {}. E-mail enviado.", email)
        
    except Exception as e:
        logger.exception("Erro no processamento via Web para {}: {}", email, e)
    finally:
        if file_path.exists():
            file_path.unlink()


@app.get("/download/{token}")
async def download_file(token: str, background_tasks: BackgroundTasks):
    zip_path = await consumir_token(token)
    if zip_path is None:
        raise HTTPException(status_code=404, detail="Link inválido ou já expirado")
    background_tasks.add_task(zip_path.unlink, missing_ok=True)
    return FileResponse(
        path=zip_path,
        filename=zip_path.name,
        media_type="application/zip",
    )


@app.post("/process", response_class=HTMLResponse)
async def handle_upload(
    request: Request,
    email: str = Form(...),
    document_file: UploadFile = File(...)
):
    try:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        file_path = UPLOAD_DIR / document_file.filename
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(document_file.file, buffer)
            
        item = QueueItem(
            file_path=file_path,
            filename=document_file.filename,
            source="web",
            callback=run_pipeline_task,
            callback_args={"email": email, "file_path": file_path, "filename": document_file.filename}
        )
        pos = await unified_queue.enqueue(item)
        
        msg = f"Sucesso! Seu arquivo está na fila única (Posição: {pos}). O resultado será enviado para {email}."
        
        return templates.TemplateResponse(
            request=request, 
            name="index.html", 
            context={"message": msg}
        )
    except Exception as e:
        logger.error("Erro no upload web: {}", e)
        return templates.TemplateResponse(
            request=request, 
            name="index.html", 
            context={"error": "Ocorreu um erro ao processar o upload. Tente novamente."}
        )
