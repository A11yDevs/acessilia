import shutil
import traceback
import uuid
from pathlib import Path

from fastapi import (
    FastAPI,
    File,
    Form,
    Request,
    UploadFile,
    HTTPException,
)
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from backend.config.settings import settings
from backend.tools.logger import logger
from frontend.clients.api_client import ApiClient, ApiError
from frontend.clients import default_client

app = FastAPI(title="Bot Acess Web Panel")

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
app.state.limiter = limiter

BASE_WEB_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_WEB_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_WEB_DIR / "static")), name="static")

client = default_client

WEB_UPLOAD_DIR = settings.temp_dir / "web_uploads"
WEB_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_CUSTOM_PROMPT_CHARS = 6000


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


def _save_upload(upload: UploadFile) -> Path:
    WEB_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex}{Path(upload.filename or '').suffix.lower()}"
    file_path = WEB_UPLOAD_DIR / safe_name
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(upload.file, buffer)
    return file_path


def _remove_file(file_path: Path) -> None:
    try:
        file_path.unlink(missing_ok=True)
    except OSError:
        pass


@app.get("/", response_class=HTMLResponse)
@limiter.limit("30/minute")
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={})


@app.get("/advanced", response_class=HTMLResponse)
@limiter.limit("30/minute")
async def advanced_page(request: Request):
    return templates.TemplateResponse(request=request, name="advanced.html", context={})


async def _submit_via_api(
    request: Request,
    template_name: str,
    document_file: UploadFile,
    email: str,
    mode: str,
    custom_prompt: str | None = None,
    thinking_mode: bool = False,
):
    file_path = _save_upload(document_file)
    try:
        result = await client.submit_job(
            file_path,
            document_file.filename or "documento",
            mode=mode,
            custom_prompt=custom_prompt,
            thinking_mode=thinking_mode,
            email=email,
            source="web",
        )
    except ApiError as e:
        logger.warning(
            "API retornou erro no upload web: {} - {}", e.status_code, e.detail
        )
        return templates.TemplateResponse(
            request=request,
            name=template_name,
            context={"error": f"Erro da API ({e.status_code}): {e.detail}"},
        )
    except Exception as e:
        logger.error("Erro no upload via web: {}", e)
        return templates.TemplateResponse(
            request=request,
            name=template_name,
            context={
                "error": "Ocorreu um erro ao enviar o arquivo para a API. Tente novamente."
            },
        )
    finally:
        _remove_file(file_path)

    msg = (
        f"Sucesso! Seu arquivo entrou na fila (Posição: {result['position']}). "
        f"O resultado será enviado para {email}."
    )
    return templates.TemplateResponse(
        request=request, name=template_name, context={"message": msg}
    )


@app.post("/process", response_class=HTMLResponse)
@limiter.limit("5/minute")
async def handle_upload(
    request: Request, email: str = Form(...), document_file: UploadFile = File(...)
):
    return await _submit_via_api(
        request,
        template_name="index.html",
        document_file=document_file,
        email=email,
        mode="normal",
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
    prompt = custom_prompt.strip()
    if len(prompt) > MAX_CUSTOM_PROMPT_CHARS:
        return templates.TemplateResponse(
            request=request,
            name="advanced.html",
            context={
                "error": "Prompt personalizado excede o limite de 6000 caracteres."
            },
        )
    return await _submit_via_api(
        request,
        template_name="advanced.html",
        document_file=document_file,
        email=email,
        mode="normal",
        custom_prompt=prompt or None,
        thinking_mode=thinking_mode,
    )


@app.get("/download/{token}")
@limiter.limit("10/minute")
async def download_page(request: Request, token: str):
    try:
        info = await client.get_download_info(token)
    except ApiError as e:
        if e.status_code == 404:
            raise HTTPException(status_code=404, detail="Link inválido ou expirado")
        logger.warning("Falha ao consultar download na API: {} - {}", e.status_code, e.detail)
        raise HTTPException(status_code=502, detail="Serviço de download indisponível")
    for f in info["formats"]:
        f["url"] = f"/api/v1{f['url']}"
    return templates.TemplateResponse(
        request=request,
        name="download.html",
        context={"filename": info["filename"], "formats": info["formats"]},
    )
