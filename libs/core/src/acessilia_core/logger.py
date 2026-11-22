import sys
from pathlib import Path

from loguru import logger

from acessilia_core.i18n import t
from acessilia_core.i18n.log_messages import LOG_LOGGER_CONFIGURED


def setup_logger(*, level: str, logs_dir: Path) -> None:
    """Send the log to stderr at ``level`` and to a daily file under ``logs_dir``.

    Process setup, not part of a run: the service passes ``LOG_LEVEL`` and
    ``LOGS_DIR`` at startup (``backend/config/process_setup.py``; ADR-0016,
    step 3), so the core reads no settings.
    """
    logs_dir.mkdir(parents=True, exist_ok=True)

    logger.remove()

    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level=level,
        colorize=True,
    )

    logger.add(
        logs_dir / "bot_{time:YYYY-MM-DD}.log",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        level="DEBUG",
        rotation="1 day",
        retention="30 days",
        compression="zip",
    )

    logger.info(t(LOG_LOGGER_CONFIGURED).format(level=level))
