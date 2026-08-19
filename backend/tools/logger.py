import sys

from loguru import logger

from backend.config.settings import settings


def setup_logger() -> None:
    logs_dir = settings.logs_dir
    logs_dir.mkdir(parents=True, exist_ok=True)

    logger.remove()

    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level=settings.log_level,
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

    if settings.log_json:
        # Arquivo separado, em JSON, para o Promtail entregar ao Loki com os campos
        # já estruturados (nível, módulo, linha) em vez de regex sobre texto. Fica à
        # parte do .log humano de propósito: quem abre log no terminal continua
        # lendo o formato legível.
        logger.add(
            logs_dir / "acessilia_{time:YYYY-MM-DD}.json.log",
            level="DEBUG",
            rotation="1 day",
            retention="30 days",
            serialize=True,
        )

    logger.info("Logger configured - level: {}", settings.log_level)
