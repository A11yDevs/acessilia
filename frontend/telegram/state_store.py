"""Small SQLite store for the Telegram bot state that must survive restarts (#396).

Only state that outlives a single interaction lives here: paused chats and the
tasks the bot follows until they finish. Per-file choices (mode and e-mail) are
intentionally kept in memory in :mod:`frontend.telegram.user_context`.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from backend.config.settings import settings

#: ``message_thread_id`` uses ``0`` for a top-level chat because SQLite treats
#: NULLs as distinct in a primary key.
_NO_THREAD = 0


@dataclass(frozen=True)
class TrackedTask:
    """One task the bot follows in a chat/topic, enough to resume its polling."""

    chat_id: int
    message_thread_id: int | None
    user_id: int
    task_id: str
    filename: str
    job_token: str | None = None
    email: str | None = None
    reply_to_message_id: int | None = None

    @property
    def state_key(self) -> tuple[int, int | None, int]:
        return (self.chat_id, self.message_thread_id, self.user_id)


class TelegramStateStore:
    """SQLite persistence for bot pauses and followed tasks."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or settings.data_dir / "telegram_state.db"

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS paused_chats (
                chat_id INTEGER PRIMARY KEY,
                paused_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS followed_tasks (
                chat_id INTEGER NOT NULL,
                message_thread_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                task_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                job_token TEXT,
                email TEXT,
                reply_to_message_id INTEGER,
                created_at TEXT NOT NULL,
                PRIMARY KEY (chat_id, message_thread_id, user_id)
            )
            """
        )
        connection.commit()
        return connection

    def load_paused_chats(self) -> set[int]:
        with closing(self._connect()) as connection, connection:
            rows = connection.execute("SELECT chat_id FROM paused_chats").fetchall()
        return {int(row[0]) for row in rows}

    def pause_chat(self, chat_id: int) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT OR REPLACE INTO paused_chats (chat_id, paused_at) VALUES (?, ?)",
                (chat_id, datetime.now(timezone.utc).isoformat()),
            )
            connection.commit()

    def resume_chat(self, chat_id: int) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM paused_chats WHERE chat_id = ?", (chat_id,))
            connection.commit()

    def save_task(
        self,
        state_key: tuple[int, int | None, int],
        task_id: str,
        *,
        filename: str,
        job_token: str | None,
        email: str | None,
        reply_to_message_id: int | None,
    ) -> None:
        chat_id, message_thread_id, user_id = state_key
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO followed_tasks (
                    chat_id, message_thread_id, user_id, task_id, filename,
                    job_token, email, reply_to_message_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (chat_id, message_thread_id, user_id) DO UPDATE SET
                    task_id = excluded.task_id,
                    filename = excluded.filename,
                    job_token = excluded.job_token,
                    email = excluded.email,
                    reply_to_message_id = excluded.reply_to_message_id,
                    created_at = excluded.created_at
                """,
                (
                    chat_id,
                    message_thread_id if message_thread_id is not None else _NO_THREAD,
                    user_id,
                    task_id,
                    filename,
                    job_token,
                    email,
                    reply_to_message_id,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            connection.commit()

    def remove_task(self, state_key: tuple[int, int | None, int]) -> None:
        chat_id, message_thread_id, user_id = state_key
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                DELETE FROM followed_tasks
                WHERE chat_id = ? AND message_thread_id = ? AND user_id = ?
                """,
                (
                    chat_id,
                    message_thread_id if message_thread_id is not None else _NO_THREAD,
                    user_id,
                ),
            )
            connection.commit()

    def load_tasks(self) -> list[TrackedTask]:
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT chat_id, message_thread_id, user_id, task_id, filename,
                       job_token, email, reply_to_message_id
                FROM followed_tasks
                ORDER BY created_at
                """
            ).fetchall()
        return [
            TrackedTask(
                chat_id=int(row[0]),
                message_thread_id=int(row[1]) or None,
                user_id=int(row[2]),
                task_id=str(row[3]),
                filename=str(row[4]),
                job_token=str(row[5]) if row[5] is not None else None,
                email=str(row[6]) if row[6] is not None else None,
                reply_to_message_id=int(row[7]) if row[7] is not None else None,
            )
            for row in rows
        ]


_store: TelegramStateStore | None = None


def get_state_store() -> TelegramStateStore:
    """Return the process-wide store, created from ``DATA_DIR`` on first use."""
    global _store
    if _store is None:
        _store = TelegramStateStore()
    return _store


def reset_state_store(path: Path | None = None) -> None:
    """Replace the process-wide store, for tests and process re-initialization."""
    global _store
    _store = TelegramStateStore(path)
