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
from backend.i18n import t, active_locale
from backend.log_messages import (
    LOG_WEB_API_UPLOAD_ERROR,
    LOG_WEB_DOWNLOAD_QUERY_FAILED,
    LOG_WEB_GLOBAL_ERROR,
    LOG_WEB_HTTP_EXCEPTION,
    LOG_WEB_RATE_LIMIT_EXCEEDED,
    LOG_WEB_UPLOAD_ERROR,
)
from backend.tools.logger import logger
from frontend.clients.api_client import ApiClient, ApiError
from frontend.clients import default_client
from frontend.web.messages import (
    WEB_ADVANCED_BACK_LINK,
    WEB_ADVANCED_HEADLINE,
    WEB_ADVANCED_INTRO,
    WEB_ADVANCED_PROMPT_HELP,
    WEB_ADVANCED_PROMPT_LABEL,
    WEB_ADVANCED_PROMPT_PLACEHOLDER,
    WEB_ADVANCED_SUBHEAD,
    WEB_ADVANCED_THINKING_LABEL,
    WEB_ADVANCED_TITLE,
    WEB_DOWNLOAD_HEADLINE,
    WEB_DOWNLOAD_NO_FORMATS,
    WEB_DOWNLOAD_SUBHEAD,
    WEB_DOWNLOAD_TITLE,
    WEB_DOWNLOAD_VALID_NOTE,
    WEB_ERROR_API_UPLOAD,
    WEB_ERROR_DOWNLOAD_INVALID,
    WEB_ERROR_DOWNLOAD_UNAVAILABLE,
    WEB_ERROR_INTERNAL,
    WEB_ERROR_PROMPT_TOO_LONG,
    WEB_ERROR_UPLOAD_GENERIC,
    WEB_FORMAT_DOCX,
    WEB_FORMAT_HTML,
    WEB_FORMAT_MP3,
    WEB_FORMAT_PDF,
    WEB_FORMAT_TXT,
    WEB_FORMAT_ZIP,
    WEB_FOOTER,
    WEB_INDEX_ADVANCED_LINK,
    WEB_INDEX_DOC_LABEL,
    WEB_INDEX_EMAIL_HELP,
    WEB_INDEX_EMAIL_LABEL,
    WEB_INDEX_HEADLINE,
    WEB_INDEX_INTRO,
    WEB_INDEX_SUBMIT_BUTTON,
    WEB_INDEX_TITLE,
    WEB_LOGO_ALT,
    WEB_RATE_LIMIT_EXCEEDED,
    WEB_SUCCESS_QUEUED,
)

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
    """Catch-all handler for unexpected errors in the Web Panel.

    Args:
        request (Request): The in-flight HTTP request that triggered the error.
        exc (Exception): The unhandled exception raised while processing the request.

    Returns:
        TemplateResponse: The rendered index page with the localized internal-error message and HTTP status 500.
    """
    logger.error(
        t(LOG_WEB_GLOBAL_ERROR).format(error=str(exc), path=request.url.path)
    )
    logger.error(traceback.format_exc())
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={**_web_strings(), "error": t(WEB_ERROR_INTERNAL).format(error=str(exc))},
        status_code=500,
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    logger.warning(
        t(LOG_WEB_HTTP_EXCEPTION).format(error=str(exc.detail), path=request.url.path)
    )
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={**_web_strings(), "error": exc.detail},
        status_code=exc.status_code,
    )


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    logger.warning(
        t(LOG_WEB_RATE_LIMIT_EXCEEDED).format(
            ip=request.client.host if request.client else "unknown",
            path=request.url.path,
        )
    )
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={**_web_strings(), "error": t(WEB_RATE_LIMIT_EXCEEDED)},
        status_code=429,
    )


def _web_strings() -> dict:
    """Assemble localized UI strings for the web panel templates in the active locale.

    Returns:
        dict: Mapping of template context keys to translated strings; templates merge this with per-request values.
    """
    return {
        "locale": active_locale().replace("_", "-"),
        "index_title": t(WEB_INDEX_TITLE),
        "index_headline": t(WEB_INDEX_HEADLINE),
        "index_intro": t(WEB_INDEX_INTRO),
        "index_email_label": t(WEB_INDEX_EMAIL_LABEL),
        "index_email_help": t(WEB_INDEX_EMAIL_HELP),
        "index_doc_label": t(WEB_INDEX_DOC_LABEL),
        "index_submit": t(WEB_INDEX_SUBMIT_BUTTON),
        "index_advanced_link": t(WEB_INDEX_ADVANCED_LINK),
        "footer": t(WEB_FOOTER),
        "logo_alt": t(WEB_LOGO_ALT),
        "advanced_title": t(WEB_ADVANCED_TITLE),
        "advanced_headline": t(WEB_ADVANCED_HEADLINE),
        "advanced_subhead": t(WEB_ADVANCED_SUBHEAD),
        "advanced_intro": t(WEB_ADVANCED_INTRO),
        "advanced_prompt_label": t(WEB_ADVANCED_PROMPT_LABEL),
        "advanced_prompt_placeholder": t(WEB_ADVANCED_PROMPT_PLACEHOLDER),
        "advanced_prompt_help": t(WEB_ADVANCED_PROMPT_HELP),
        "advanced_thinking_label": t(WEB_ADVANCED_THINKING_LABEL),
        "advanced_back_link": t(WEB_ADVANCED_BACK_LINK),
        "download_title": t(WEB_DOWNLOAD_TITLE),
        "download_headline": t(WEB_DOWNLOAD_HEADLINE),
        "download_subhead": t(WEB_DOWNLOAD_SUBHEAD),
        "download_no_formats": t(WEB_DOWNLOAD_NO_FORMATS),
        "download_valid_note": t(WEB_DOWNLOAD_VALID_NOTE),
        "format_txt": t(WEB_FORMAT_TXT),
        "format_docx": t(WEB_FORMAT_DOCX),
        "format_pdf": t(WEB_FORMAT_PDF),
        "format_html": t(WEB_FORMAT_HTML),
        "format_mp3": t(WEB_FORMAT_MP3),
        "format_zip": t(WEB_FORMAT_ZIP),
    }


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
    return templates.TemplateResponse(request=request, name="index.html", context=_web_strings())


@app.get("/advanced", response_class=HTMLResponse)
@limiter.limit("30/minute")
async def advanced_page(request: Request):
    return templates.TemplateResponse(request=request, name="advanced.html", context=_web_strings())


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
            t(LOG_WEB_API_UPLOAD_ERROR).format(
                status_code=e.status_code, detail=e.detail
            )
        )
        return templates.TemplateResponse(
            request=request,
            name=template_name,
            context={**_web_strings(), "error": t(WEB_ERROR_API_UPLOAD).format(status_code=e.status_code, detail=e.detail)},
        )
    except Exception as e:
        logger.error(t(LOG_WEB_UPLOAD_ERROR).format(error=str(e)))
        return templates.TemplateResponse(
            request=request,
            name=template_name,
            context={**_web_strings(), "error": t(WEB_ERROR_UPLOAD_GENERIC)}
        )
    finally:
        _remove_file(file_path)

    msg = t(WEB_SUCCESS_QUEUED).format(
        position=result["position"], email=email
    )
    return templates.TemplateResponse(
        request=request, name=template_name, context={**_web_strings(), "message": msg}
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
            context={**_web_strings(), "error": t(WEB_ERROR_PROMPT_TOO_LONG)}
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
            raise HTTPException(status_code=404, detail=t(WEB_ERROR_DOWNLOAD_INVALID))
        logger.warning(
            t(LOG_WEB_DOWNLOAD_QUERY_FAILED).format(
                status_code=e.status_code, detail=e.detail
            )
        )
        raise HTTPException(status_code=502, detail=t(WEB_ERROR_DOWNLOAD_UNAVAILABLE))
    for f in info["formats"]:
        f["url"] = f"/api/v1{f['url']}"
    return templates.TemplateResponse(
        request=request,
        name="download.html",
        context={**_web_strings(), "filename": info["filename"], "formats": info["formats"]},
    )
