#!/usr/bin/env python3
import asyncio
import os
import subprocess
import sys

from core.utils.logger import setup_logger, logger
from config.settings import settings

LOCK_FILE = os.path.join(os.path.dirname(__file__), "bot.lock")


def _is_process_running(pid: int) -> bool:
    if sys.platform == "win32":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
            capture_output=True,
            text=True,
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

    enabled = [i.strip() for i in settings.enabled_interfaces.split(",")]
    tasks = []

    if "telegram" in enabled and settings.bot_token_valid:
        from interfaces.telegram.bot import start_polling

        tasks.append(start_polling())
        logger.info("Interface Telegram habilitada")
    elif "telegram" in enabled and not settings.bot_token_valid:
        logger.warning("Interface Telegram habilitada mas BOT_TOKEN nao configurado")

    if "web" in enabled:
        from interfaces.web.app import app
        import uvicorn

        config = uvicorn.Config(
            app, host="0.0.0.0", port=8000, log_level=settings.log_level.lower()
        )
        server = uvicorn.Server(config)
        tasks.append(server.serve())
        logger.info("Interface Web habilitada (http://localhost:8000)")

    if not tasks:
        logger.critical(
            "Nenhuma interface habilitada. Configure ENABLED_INTERFACES no .env"
        )
        sys.exit(1)

    logger.info("Iniciando com interfaces: {}", settings.enabled_interfaces)
    await asyncio.gather(*tasks)


async def _cleanup_http_clients():
    from core.ai.ollama import client as ollama_cli
    from core.ai.openrouter import client as or_cli

    try:
        await ollama_cli.close()
    except Exception:
        pass
    try:
        await or_cli.close()
    except Exception:
        pass


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
        try:
            asyncio.run(_cleanup_http_clients())
        except Exception:
            pass
