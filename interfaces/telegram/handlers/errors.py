from aiogram import Router
from aiogram.types import ErrorEvent
from aiogram.filters import ExceptionTypeFilter

from core.utils.logger import logger

router = Router()


@router.errors(ExceptionTypeFilter(Exception))
async def handle_error(event: ErrorEvent) -> None:
    logger.exception("Erro não tratado: {}", event.exception)
