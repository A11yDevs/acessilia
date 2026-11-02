from aiogram import Router
from aiogram.types import ErrorEvent
from aiogram.filters import ExceptionTypeFilter

from backend.i18n import t
from backend.log_messages import LOG_TELEGRAM_UNHANDLED_ERROR
from backend.tools.logger import logger

router = Router()


@router.errors(ExceptionTypeFilter(Exception))
async def handle_error(event: ErrorEvent) -> None:
    """Log any unhandled Telegram exception through the localized error message.

    Args:
        event (ErrorEvent): Aiogram error event carrying the unhandled exception; no default (required).
    """
    logger.exception(t(LOG_TELEGRAM_UNHANDLED_ERROR).format(error=event.exception))
