from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile

from backend.i18n import t
from backend.log_messages import (
    LOG_TELEGRAM_FILE_DOWNLOADING,
    LOG_TELEGRAM_FILE_DOWNLOADED,
)
from backend.tools.logger import logger


async def download_file(bot: Bot, file_id: str, destination: Path) -> Path:
    """Download an uploaded file from Telegram's file storage to the given destination.

    Args:
        bot (Bot): Aiogram Bot instance used to fetch and download the file; no default (required).
        file_id (str): Telegram file id of the uploaded file; no default (required).
        destination (Path): Local path the downloaded file is written to; no default (required).

    Returns:
        Path: The destination path the file was written to.
    """
    file = await bot.get_file(file_id)
    logger.debug(
        t(LOG_TELEGRAM_FILE_DOWNLOADING).format(
            file_path=file.file_path, filename=destination.name
        )
    )
    await bot.download_file(file.file_path, destination)
    logger.info(
        t(LOG_TELEGRAM_FILE_DOWNLOADED).format(
            filename=destination.name, size=file.file_size or 0
        )
    )
    return destination


async def send_output_file(
    bot: Bot, chat_id: int, file_path: Path, caption: str,
    message_thread_id: int | None = None,
) -> None:
    input_file = FSInputFile(file_path)
    await bot.send_document(
        chat_id=chat_id, document=input_file, caption=caption,
        message_thread_id=message_thread_id,
    )
