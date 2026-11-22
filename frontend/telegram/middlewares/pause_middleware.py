from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject
from typing import Any, Awaitable, Callable, Dict

from acessilia_core.i18n import t
from frontend.telegram.messages import MSG_BOT_PAUSED
from frontend.telegram.state_store import get_state_store

_paused_chats: set[int] | None = None


def get_paused_chats() -> set[int]:
    """Return the paused-chat cache, loading it from SQLite once (#396)."""
    global _paused_chats
    if _paused_chats is None:
        _paused_chats = get_state_store().load_paused_chats()
    return _paused_chats


def pause_chat(chat_id: int) -> None:
    """Pause ``chat_id`` in memory and persist it for the next process."""
    get_paused_chats().add(chat_id)
    get_state_store().pause_chat(chat_id)


def resume_chat(chat_id: int) -> None:
    """Resume ``chat_id`` in memory and remove the persisted pause."""
    get_paused_chats().discard(chat_id)
    get_state_store().resume_chat(chat_id)


def reset_paused_cache() -> None:
    """Drop the in-memory pause cache, for tests and process re-initialization."""
    global _paused_chats
    _paused_chats = None


class PauseMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        if event.chat.id in get_paused_chats():
            text = event.text or ""
            # Allow the resume command (Portuguese and English aliases) to
            # reach its handler so a paused chat can un-pause itself.
            first_token = text.split(maxsplit=1)[0].strip().lower() if text.strip() else ""
            if first_token in {"/ativar", "/activate"}:
                return await handler(event, data)

            await event.answer(t(MSG_BOT_PAUSED))
            return None

        return await handler(event, data)
