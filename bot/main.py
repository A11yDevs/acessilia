import asyncio
import sys

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.handlers.start import router as start_router
from bot.handlers.document import router as document_router
from bot.handlers.errors import router as error_router
from bot.services.cleanup_service import periodic_cleanup
from bot.services.history_service import init_db
from bot.utils.logger import setup_logger, logger
from bot.middlewares.pause_middleware import PauseMiddleware
from config.settings import settings


from bot.services.queue_service import unified_queue


async def on_startup(bot: Bot) -> None:
    init_db()
    asyncio.create_task(periodic_cleanup())
    unified_queue.start_worker()
    logger.info("Bot iniciado")


async def on_shutdown(bot: Bot) -> None:
    logger.info("Bot desligando")


def create_bot() -> Bot:
    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.middleware(PauseMiddleware())
    dp.include_router(start_router)
    dp.include_router(document_router)
    dp.include_router(error_router)
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    return dp


async def start_polling() -> None:
    bot = create_bot()
    dp = create_dispatcher()
    logger.info("Iniciando polling")
    await dp.start_polling(bot)


def main() -> None:
    setup_logger()

    if not settings.bot_token_valid:
        logger.critical("BOT_TOKEN nao configurado")
        sys.exit(1)

    try:
        asyncio.run(start_polling())
    except KeyboardInterrupt:
        logger.info("Bot interrompido pelo usuario")
    except Exception:
        logger.exception("Erro fatal no bot")
        sys.exit(1)
