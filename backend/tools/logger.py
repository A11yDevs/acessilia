import sys

from loguru import logger

from backend.config.settings import settings


def _add_trace_context(record: dict) -> None:
    """Add the active OpenTelemetry context without requiring telemetry at runtime."""
    try:
        from opentelemetry import trace

        context = trace.get_current_span().get_span_context()
        if not context.is_valid:
            return
        record["extra"].setdefault("trace_id", f"{context.trace_id:032x}")
        record["extra"].setdefault("span_id", f"{context.span_id:016x}")
    except Exception:
        return


def setup_logger() -> None:
    logs_dir = settings.logs_dir
    logs_dir.mkdir(parents=True, exist_ok=True)

    logger.remove()
    logger.configure(patcher=_add_trace_context)

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
        # Arquivo separado, em JSON, para o Alloy entregar ao Loki com os campos
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
