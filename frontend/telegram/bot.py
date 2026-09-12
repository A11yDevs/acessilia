import asyncio
import sys

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from frontend.telegram.handlers.start import router as start_router
from frontend.telegram.handlers.document import router as document_router
from frontend.telegram.handlers.errors import router as error_router
from backend.tools.logger import setup_logger, logger
from frontend.telegram.middlewares.locale_middleware import LocaleMiddleware
from frontend.telegram.middlewares.pause_middleware import PauseMiddleware
from backend.i18n import t
from backend.log_messages import (
    LOG_BOT_INTERRUPTED_BY_USER,
    LOG_BOT_SHUTTING_DOWN,
    LOG_BOT_STARTING_POLLING,
    LOG_BOT_STARTED,
    LOG_BOT_TOKEN_NOT_CONFIGURED,
    LOG_FATAL_ERROR_IN_BOT,
)
from backend.config.settings import settings


async def on_startup(bot: Bot) -> None:
    """Log a startup notice marking the bot as an Acessilia API client.

    Args:
        bot (Bot): Aiogram Bot instance that finished starting up; no default (required).
    """
    logger.info(t(LOG_BOT_STARTED))


async def on_shutdown(bot: Bot) -> None:
    """Log a shutdown notice while the dispatcher tears down.

    Args:
        bot (Bot): Aiogram Bot instance being shut down; no default (required).
    """
    logger.info(t(LOG_BOT_SHUTTING_DOWN))


def create_bot() -> Bot:
    """Create the aiogram Bot with the configured token and HTML parse-mode defaults.

    Returns:
        Bot: Configured aiogram Bot instance; no default (required return).
    """
    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher() -> Dispatcher:
    """Build the aiogram dispatcher with locale and pause middlewares plus all message routers.

    Returns:
        Dispatcher: Configured aiogram Dispatcher ready for polling, with LocaleMiddleware applied before PauseMiddleware so localized replies are available even while a chat is paused.
    """
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.middleware(LocaleMiddleware())
    dp.message.middleware(PauseMiddleware())
    dp.include_router(start_router)
    dp.include_router(document_router)
    dp.include_router(error_router)
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    return dp


async def start_polling() -> None:
    """Create the bot and dispatcher then run long-polling until interrupted.

    Args:
        (none)

    Returns:
        None
    """
    bot = create_bot()
    dp = create_dispatcher()
    logger.info(t(LOG_BOT_STARTING_POLLING))
    await dp.start_polling(bot)


def main() -> None:
    """Entry point: configure logging, validate the token and run the polling loop.

    Args:
        (none)

    Returns:
        None
    """
    setup_logger()

    if not settings.bot_token_valid:
        logger.critical(t(LOG_BOT_TOKEN_NOT_CONFIGURED))
        sys.exit(1)

    try:
        asyncio.run(start_polling())
    except KeyboardInterrupt:
        logger.info(t(LOG_BOT_INTERRUPTED_BY_USER))
    except Exception:
        logger.exception(t(LOG_FATAL_ERROR_IN_BOT))
        sys.exit(1)


if __name__ == "__main__":
    main()
