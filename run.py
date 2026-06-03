#!/usr/bin/env python3
import asyncio
import os
import subprocess
import sys

from bot.main import start_polling
from bot.services.opencode_launcher import ensure_opencode_running
from bot.utils.logger import setup_logger, logger
from config.settings import settings

LOCK_FILE = os.path.join(os.path.dirname(__file__), "bot.lock")
VALID_AI_CLIENTS = {"openrouter", "opencode", "browser", "ollama"}


def _is_process_running(pid: int) -> bool:
    if sys.platform == "win32":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
            capture_output=True, text=True
        )
        return str(pid) in result.stdout
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def acquire_lock() -> None:
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, "r") as f:
                pid = int(f.read().strip())
            if _is_process_running(pid):
                logger.critical(
                    "Outra instancia do bot ja esta rodando (PID={})",
                    pid,
                )
                sys.exit(1)
            else:
                logger.warning(
                    "Lock file stale (PID {} nao existe), removendo...",
                    pid,
                )
                os.remove(LOCK_FILE)
        except ValueError:
            os.remove(LOCK_FILE)
    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))
    logger.info("Lock acquired (PID={})", os.getpid())


def release_lock() -> None:
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
            logger.info("Lock released")
    except OSError:
        pass


async def startup():
    setup_logger()

    if not settings.bot_token_valid:
        logger.critical("BOT_TOKEN nao configurado")
        sys.exit(1)

    if settings.ai_client not in VALID_AI_CLIENTS:
        logger.critical(
            "AI_CLIENT invalido: '{}'. Valores aceitos: {}",
            settings.ai_client,
            ", ".join(sorted(VALID_AI_CLIENTS)),
        )
        sys.exit(1)

    logger.info("AI_CLIENT ativo: {}", settings.ai_client)

    if settings.ai_client == "opencode":
        await ensure_opencode_running()

    # Importa a app web aqui para evitar dependência circular se houver
    from web.app import app
    import uvicorn

    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=8000,
        log_level=settings.log_level.lower(),
    )
    server = uvicorn.Server(config)

    logger.info(
        "Iniciando bot e painel web acessível "
        "(http://localhost:8000)..."
    )

    # Roda ambos simultaneamente
    await asyncio.gather(
        start_polling(),
        server.serve()
    )


if __name__ == "__main__":
    acquire_lock()
    try:
        asyncio.run(startup())
    except KeyboardInterrupt:
        logger.info("Bot interrompido pelo usuario")
    except Exception:
        logger.exception("Erro fatal no bot")
        sys.exit(1)
    finally:
        release_lock()
