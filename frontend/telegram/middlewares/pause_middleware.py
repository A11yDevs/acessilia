import sqlite3
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from acessilia_core.i18n import t
from acessilia_core.logger import logger
from frontend.telegram.messages import MSG_BOT_PAUSED
from frontend.telegram.state_store import get_state_store

_paused_chats: set[int] | None = None


def get_paused_chats() -> set[int]:
    """Return the paused-chat cache, loading it from SQLite once (#396)."""
    global _paused_chats
    if _paused_chats is None:
        try:
            _paused_chats = get_state_store().load_paused_chats()
        except sqlite3.Error as error:
            logger.warning("Telegram state store unavailable: {}", error)
            _paused_chats = set()
    return _paused_chats


def _set_paused(chat_id: int, *, paused: bool) -> None:
    """Update the memory cache and the persisted pause for ``chat_id``."""
    chats = get_paused_chats()
    if paused:
        chats.add(chat_id)
    else:
        chats.discard(chat_id)
    try:
        store = get_state_store()
        if paused:
            store.pause_chat(chat_id)
        else:
            store.resume_chat(chat_id)
    except sqlite3.Error as error:
        logger.warning("Telegram state store unavailable: {}", error)


def pause_chat(chat_id: int) -> None:
    """Pause ``chat_id`` in memory and persist it for the next process."""
    _set_paused(chat_id, paused=True)


def resume_chat(chat_id: int) -> None:
    """Resume ``chat_id`` in memory and remove the persisted pause."""
    _set_paused(chat_id, paused=False)


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
