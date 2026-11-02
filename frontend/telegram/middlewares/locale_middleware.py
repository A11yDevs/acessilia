"""Per-user locale middleware: detects the remote Telegram user's locale and
overrides the i18n lookup locale for that task so bot replies render in the
user's own language when it is one of the offered locales, and otherwise in
the server-side locale the software logs in locally.
"""

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from backend.i18n import locale_for_user, set_request_locale


class LocaleMiddleware(BaseMiddleware):
    """Set the per-task i18n locale from the message sender's Telegram language code."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        sender_language = ""
        if isinstance(event, Message):
            user = event.from_user
            if user is not None:
                sender_language = user.language_code or ""
        set_request_locale(locale_for_user(sender_language or None))
        return await handler(event, data)
