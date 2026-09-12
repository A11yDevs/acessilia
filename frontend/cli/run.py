#!/usr/bin/env python3
import asyncio
import os
import subprocess
import sys

from backend.i18n import t
from backend.tools.logger import setup_logger, logger
from backend.config.settings import settings
from backend.log_messages import (
    LOG_API_INTERFACE_ENABLED,
    LOG_BOT_ALREADY_RUNNING,
    LOG_BOT_INTERRUPTED_BY_USER,
    LOG_FATAL_ERROR_IN_BOT,
    LOG_LOCK_ACQUIRED,
    LOG_LOCK_FILE_STALE,
    LOG_LOCK_RELEASED,
    LOG_NO_INTERFACE_ENABLED,
    LOG_STARTING_INTERFACES,
    LOG_TELEGRAM_INTERFACE_ENABLED,
    LOG_TELEGRAM_INTERFACE_NO_TOKEN,
    LOG_WEB_INTERFACE_ENABLED,
)

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
                logger.critical(t(LOG_BOT_ALREADY_RUNNING).format(pid=pid))
                sys.exit(1)
            else:
                logger.warning(t(LOG_LOCK_FILE_STALE).format(pid=pid))
                os.remove(LOCK_FILE)
        except ValueError:
            os.remove(LOCK_FILE)
    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))
    logger.info(t(LOG_LOCK_ACQUIRED).format(pid=os.getpid()))


def release_lock() -> None:
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
            logger.info(t(LOG_LOCK_RELEASED))
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
            t(LOG_API_INTERFACE_ENABLED).format(port=settings.api_port)
        )

    if "telegram" in enabled and settings.bot_token_valid:
        from frontend.telegram.bot import start_polling

        tasks.append(start_polling())
        logger.info(t(LOG_TELEGRAM_INTERFACE_ENABLED))
    elif "telegram" in enabled and not settings.bot_token_valid:
        logger.warning(t(LOG_TELEGRAM_INTERFACE_NO_TOKEN))

    if "web" in enabled:
        from frontend.web.app import app
        import uvicorn

        config = uvicorn.Config(
            app,
            host="0.0.0.0",
            port=settings.web_port,
            log_level=settings.log_level.lower(),
        )
        server = uvicorn.Server(config)
        tasks.append(server.serve())
        logger.info(
            t(LOG_WEB_INTERFACE_ENABLED).format(port=settings.web_port)
        )

    if not tasks:
        logger.critical(t(LOG_NO_INTERFACE_ENABLED))
        sys.exit(1)

    logger.info(
        t(LOG_STARTING_INTERFACES).format(interfaces=settings.enabled_interfaces)
    )
    await asyncio.gather(*tasks)


def main():
    acquire_lock()
    try:
        asyncio.run(startup())
    except KeyboardInterrupt:
        logger.info(t(LOG_BOT_INTERRUPTED_BY_USER))
    except Exception:
        logger.exception(t(LOG_FATAL_ERROR_IN_BOT))
        sys.exit(1)
    finally:
        release_lock()

if __name__ == "__main__":
    main()
