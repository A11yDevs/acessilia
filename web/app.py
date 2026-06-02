import shutil
import zipfile
import os
import traceback
from pathlib import Path
from typing import List

from fastapi import FastAPI, File, UploadFile, Form, BackgroundTasks, Request, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from bot.agente_mestre import process
from bot.exporters.txt_exporter import export_txt
from bot.exporters.docx_exporter import export_docx
from bot.exporters.pdf_exporter import export_pdf
from bot.exporters.audio_exporter import export_mp3
from bot.utils.logger import logger
from exporters.pandoc_exporter import export_accessible_document
from config.settings import settings
from web.services.email_service import send_confirmation_email, send_result_email

import asyncio
import concurrent.futures
from bot.services.queue_service import unified_queue, QueueItem

app = FastAPI(title="Bot Acess Web Panel")

executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)

# Garante caminho absoluto para os templates para evitar erros de localização
BASE_WEB_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_WEB_DIR / "templates"))

@app.on_event("startup")
async def startup_event():
    """Inicia o worker da fila unificada no startup do app."""
    unified_queue.start_worker()

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

# Garante que os diretórios existam
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request=request, name="index.html", context={}
    )

async def run_pipeline_task(email: str, file_path: Path, filename: str):
    """Lógica de processamento para a Web executada pelo Worker da Fila."""
    try:
        # 1. Envia confirmação
        await send_confirmation_email(email, filename)
        
        # 2. Processa o arquivo (IA)
        async def silent_status(msg: str):
            logger.debug("Web Pipeline Status [{}]: {}", filename, msg)
            
        canonical_doc = await process(file_path, status_callback=silent_status)
        
        # 3. Gera exportações (Rodar em thread para não travar o loop de eventos)
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
        
        # Gera áudio
        if txt_path.exists():
            clean_text = txt_path.read_text(encoding="utf-8")
            await export_mp3(clean_text, mp3_path)
            
        # 4. Cria o ZIP
        zip_path = task_output_dir / f"{base_name}_acessivel.zip"
        files_to_zip = [txt_path, docx_path, pdf_path, html_path, mp3_path]
        
        def create_zip():
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for f_path in files_to_zip:
                    if f_path.exists():
                        archive.write(f_path, arcname=f_path.name)
        
        await loop.run_in_executor(executor, create_zip)
                    
        # 5. Envia resultado por e-mail
        await send_result_email(email, filename, zip_path)
        
        logger.info("Web Task concluída para {}. E-mail enviado.", email)
        
    except Exception as e:
        logger.exception("Erro no processamento via Web para {}: {}", email, e)
    finally:
        if file_path.exists():
            file_path.unlink()

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
            
        # Adiciona na Fila Unificada
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
