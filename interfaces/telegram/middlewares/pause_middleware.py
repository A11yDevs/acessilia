from aiogram import BaseMiddleware
from aiogram.types import Message
from typing import Any, Awaitable, Callable, Dict

_paused_chats: set[int] = set()


def get_paused_chats() -> set[int]:
    return _paused_chats


class PauseMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        if event.chat.id in _paused_chats:
            text = event.text or ""
            if text.strip().lower() == "/ativar":
                return await handler(event, data)

            await event.answer("Bot está desativado neste chat. Use /ativar para reativar.")
            return None

        return await handler(event, data)
