import asyncio
import sys

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from frontend.telegram.handlers.start import router as start_router
from frontend.telegram.handlers.document import (
    resume_tracked_tasks,
    router as document_router,
)
from frontend.telegram.handlers.errors import router as error_router
from backend.config.process_setup import setup_process
from acessilia_core.logger import logger
from frontend.telegram.middlewares.locale_middleware import LocaleMiddleware
from frontend.telegram.middlewares.pause_middleware import PauseMiddleware
from frontend.telegram.commands import bot_commands, telegram_language
from acessilia_core.i18n import active_locale, active_locales, t
from acessilia_core.i18n.log_messages import (
    LOG_BOT_INTERRUPTED_BY_USER,
    LOG_BOT_SHUTTING_DOWN,
    LOG_BOT_STARTING_POLLING,
    LOG_BOT_STARTED,
    LOG_TELEGRAM_BOT_CONNECTED,
    LOG_TELEGRAM_GETME_FAILED,
    LOG_TELEGRAM_PRIVACY_MODE,
    LOG_TELEGRAM_SET_COMMANDS_FAILED,
    LOG_BOT_TOKEN_NOT_CONFIGURED,
    LOG_FATAL_ERROR_IN_BOT,
)
from backend.config.settings import settings


async def _announce_identity(bot: Bot) -> None:
    """Log the bot username and warn when privacy mode withholds group files."""
    me = await bot.get_me()
    logger.info(t(LOG_TELEGRAM_BOT_CONNECTED).format(username=me.username))
    if not getattr(me, "can_read_all_group_messages", True):
        logger.warning(t(LOG_TELEGRAM_PRIVACY_MODE).format(username=me.username))


async def _set_commands(bot: Bot, commands, scope: str | None) -> None:
    """Publish one command list; a failure is logged without skipping the rest."""
    try:
        await bot.set_my_commands(commands, language_code=scope)
    except Exception as error:
        logger.warning(
            t(LOG_TELEGRAM_SET_COMMANDS_FAILED).format(
                scope=scope or "default", error=error
            )
        )


async def _register_commands(bot: Bot) -> None:
    """Publish `/help` commands through the Bot API for every active locale."""
    active = active_locales()
    server_locale = active_locale()
    default_locale = server_locale if server_locale in active else active[0]
    await _set_commands(bot, bot_commands(default_locale), None)
    registered = {telegram_language(default_locale)}
    for locale in active:
        language = telegram_language(locale)
        if language in registered:
            continue
        await _set_commands(bot, bot_commands(locale), language)
        registered.add(language)


async def on_startup(bot: Bot) -> None:
    """Log startup, announce the bot, publish commands and resume tracked tasks.

    Args:
        bot (Bot): Aiogram Bot instance that finished starting up; no default (required).
    """
    logger.info(t(LOG_BOT_STARTED))
    try:
        await _announce_identity(bot)
    except Exception as error:
        logger.warning(t(LOG_TELEGRAM_GETME_FAILED).format(error=error))
    try:
        await _register_commands(bot)
    except Exception as error:
        logger.warning(t(LOG_TELEGRAM_SET_COMMANDS_FAILED).format(scope="default", error=error))
    await resume_tracked_tasks(bot)


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
    setup_process()

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
