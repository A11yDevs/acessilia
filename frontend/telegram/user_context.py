from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram.types import Message


UserStateKey = tuple[int, int | None, int]

user_modes: dict[UserStateKey, str] = {}
user_emails: dict[UserStateKey, str] = {}
user_task_ids: dict[UserStateKey, str] = {}


def get_user_state_key(message: Message) -> UserStateKey:
    """Return the chat, topic and user identity used to isolate bot state."""
    if message.from_user is None:
        raise ValueError("Message does not have an identified user")

    return (
        message.chat.id,
        message.message_thread_id,
        message.from_user.id,
    )
