#!/usr/bin/env python3
import asyncio
import os
import subprocess
import sys

from backend.tools.logger import setup_logger, logger
from backend.config.settings import settings

LOCK_FILE = str(settings.data_dir / "bot.lock")


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
    settings.data_dir.mkdir(parents=True, exist_ok=True)
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

    if "api" in enabled:
        from backend.api.app import app as api_app
        import uvicorn

        api_config = uvicorn.Config(
            api_app,
            host=settings.api_host,
            port=settings.api_port,
            log_level=settings.log_level.lower(),
        )
        api_server = uvicorn.Server(api_config)
        tasks.append(api_server.serve())
        logger.info(
            "Interface API habilitada (http://localhost:{})",
            settings.api_port,
        )

    if "telegram" in enabled and settings.bot_token_valid:
        from frontend.telegram.bot import start_polling

        tasks.append(start_polling())
        logger.info("Interface Telegram habilitada")
    elif "telegram" in enabled and not settings.bot_token_valid:
        logger.warning("Interface Telegram habilitada mas BOT_TOKEN nao configurado")

    if "web" in enabled:
        from frontend.web.app import app
        import uvicorn

        config = uvicorn.Config(
            app, host="0.0.0.0", port=settings.web_port, log_level=settings.log_level.lower()
        )
        server = uvicorn.Server(config)
        tasks.append(server.serve())
        logger.info(
            "Interface Web habilitada (http://localhost:{})",
            settings.web_port,
        )

    if not tasks:
        logger.critical(
            "Nenhuma interface habilitada. Configure ENABLED_INTERFACES no .env"
        )
        sys.exit(1)

    logger.info("Iniciando com interfaces: {}", settings.enabled_interfaces)
    await asyncio.gather(*tasks)


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
