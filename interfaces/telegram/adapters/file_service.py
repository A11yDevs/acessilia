from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile

from core.utils.logger import logger


async def download_file(bot: Bot, file_id: str, destination: Path) -> Path:
    file = await bot.get_file(file_id)
    logger.debug("Downloading file: {} -> {}", file.file_path, destination.name)
    await bot.download_file(file.file_path, destination)
    logger.info("File downloaded: {} ({} bytes)", destination.name, file.file_size or 0)
    return destination


async def send_output_file(
    bot: Bot, chat_id: int, file_path: Path, caption: str
) -> None:
    input_file = FSInputFile(file_path)
    await bot.send_document(chat_id=chat_id, document=input_file, caption=caption)
