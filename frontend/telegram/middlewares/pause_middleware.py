from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject
from typing import Any, Awaitable, Callable, Dict

from backend.i18n import t
from frontend.telegram.messages import MSG_BOT_PAUSED

_paused_chats: set[int] = set()


def get_paused_chats() -> set[int]:
    return _paused_chats


class PauseMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        if event.chat.id in _paused_chats:
            text = event.text or ""
            # Allow the resume command (Portuguese and English aliases) to
            # reach its handler so a paused chat can un-pause itself.
            first_token = text.split(maxsplit=1)[0].strip().lower() if text.strip() else ""
            if first_token in {"/ativar", "/activate"}:
                return await handler(event, data)

            await event.answer(t(MSG_BOT_PAUSED))
            return None

        return await handler(event, data)
