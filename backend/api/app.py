from __future__ import annotations

import asyncio

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.api.limiter import limiter
from backend.api.routes import download, health, history, jobs
from backend.services.cleanup_service import periodic_cleanup
from backend.services.database import init_db
from backend.services.download_token_service import limpar_tokens_expirados
from backend.services.queue_service import unified_queue
from backend.tools.logger import logger, setup_logger


@asynccontextmanager
async def _lifespan(app: FastAPI):
    setup_logger()
    init_db()
    unified_queue.start_worker()
    await limpar_tokens_expirados()
    cleanup_task = asyncio.create_task(periodic_cleanup())
    logger.info("API Acessilia iniciada (worker da fila + cleanup ativos)")
    yield
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass


def create_app() -> FastAPI:
    app = FastAPI(title="Acessilia API", version="1.0.0", lifespan=_lifespan)
    app.state.limiter = limiter

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
        return JSONResponse(
            status_code=429,
            content={"detail": "Muitas requisições. Aguarde um momento antes de tentar novamente."},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(request: Request, exc: StarletteHTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(Exception)
    async def _global_exception_handler(request: Request, exc: Exception):
        logger.exception("Erro na API: {} | Path: {}", exc, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "Erro interno no servidor"},
        )

    app.include_router(jobs.router, prefix="/api/v1")
    app.include_router(download.router, prefix="/api/v1")
    app.include_router(history.router, prefix="/api/v1")
    app.include_router(health.router, prefix="/api/v1")
    return app


app = create_app()
