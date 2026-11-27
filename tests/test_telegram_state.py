"""Telegram state survives a bot restart: paused chats and followed tasks (#396)."""

from __future__ import annotations

import asyncio
import sqlite3
from io import StringIO

import pytest

from backend.config.settings import settings
from frontend.clients.api_client import ApiError
from frontend.telegram import state_store, user_context
from frontend.telegram.handlers import document as doc_module, start as start_module
from frontend.telegram.middlewares import pause_middleware
from frontend.telegram.state_store import TelegramStateStore
from tests.test_telegram_client import _FakeBot, _FakeMessage

_STATE_STORE_WARNING = "Telegram state store unavailable: "


class _CancelClient:
    async def cancel_job(self, task_id: str) -> dict:
        return {"task_id": task_id}


def _state_store_warnings(warnings: StringIO) -> list[str]:
    return [
        line
        for line in warnings.getvalue().splitlines()
        if line.startswith(_STATE_STORE_WARNING)
    ]


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    state_store.reset_state_store(tmp_path / "data" / "telegram_state.db")
    pause_middleware.reset_paused_cache()
    user_context.user_task_ids.clear()
    yield
    user_context.user_task_ids.clear()
    state_store.reset_state_store()
    pause_middleware.reset_paused_cache()


def test_paused_chats_survive_a_cache_reset() -> None:
    pause_middleware.pause_chat(-100123)

    pause_middleware.reset_paused_cache()

    assert pause_middleware.get_paused_chats() == {-100123}

    pause_middleware.resume_chat(-100123)
    pause_middleware.reset_paused_cache()
    assert pause_middleware.get_paused_chats() == set()


def test_pause_and_resume_update_memory_when_the_store_fails(monkeypatch) -> None:
    class FailingStore:
        def load_paused_chats(self) -> set[int]:
            return set()

        def pause_chat(self, chat_id: int) -> None:
            raise sqlite3.Error("down")

        def resume_chat(self, chat_id: int) -> None:
            raise sqlite3.Error("down")

    warnings = StringIO()
    monkeypatch.setattr(pause_middleware, "get_state_store", FailingStore)
    sink = pause_middleware.logger.add(
        warnings, level="WARNING", format="{message}"
    )
    try:
        pause_middleware.pause_chat(-100123)
        assert -100123 in pause_middleware.get_paused_chats()

        pause_middleware.resume_chat(-100123)
        assert -100123 not in pause_middleware.get_paused_chats()
    finally:
        pause_middleware.logger.remove(sink)

    assert warnings.getvalue().splitlines() == [
        "Telegram state store unavailable: down",
        "Telegram state store unavailable: down",
    ]


def test_tasks_round_trip_for_top_level_and_topic_chats(tmp_path) -> None:
    store = TelegramStateStore(tmp_path / "state.db")
    store.save_task(
        (1, None, 10),
        "top-task",
        filename="top.pdf",
        job_token="top-token",
        email="reader@example.com",
    )
    store.save_task(
        (1, 7, 10),
        "topic-task",
        filename="topic.pdf",
        job_token="topic-token",
        email=None,
    )

    tasks = {task.task_id: task for task in store.load_tasks()}
    assert tasks["top-task"].state_key == (1, None, 10)
    assert tasks["top-task"].email == "reader@example.com"
    assert tasks["top-task"].job_token == "top-token"
    assert tasks["topic-task"].state_key == (1, 7, 10)

    # A second upload in the same chat/user replaces the followed task.
    store.save_task(
        (1, None, 10),
        "replacement",
        filename="new.pdf",
        job_token="new-token",
        email=None,
    )
    assert {task.task_id for task in store.load_tasks()} == {
        "replacement",
        "topic-task",
    }

    store.remove_task((1, 7, 10), "topic-task")
    assert [task.task_id for task in store.load_tasks()] == ["replacement"]

    # A finishing old task must not delete the newer task in the same key.
    store.save_task(
        (1, None, 10),
        "newer",
        filename="newer.pdf",
        job_token=None,
        email=None,
    )
    store.remove_task((1, None, 10), "replacement")
    assert [task.task_id for task in store.load_tasks()] == ["newer"]


def test_resume_delivers_the_finished_task_and_clears_it(monkeypatch) -> None:
    state_store.get_state_store().save_task(
        (123, None, 456),
        "resumed-task",
        filename="resumed.pdf",
        job_token="resumed-token",
        email=None,
    )

    class FinishedClient:
        registered: tuple[str, str] | None = None

        def remember_job_token(self, task_id: str, job_token: str) -> None:
            self.registered = (task_id, job_token)

        async def get_job_status(self, task_id: str) -> dict:
            return {
                "task_id": task_id,
                "status": "done",
                "progresso": 1.0,
                "erros": [],
                "download_url": "http://localhost:8000/api/v1/download/resumed",
            }

    finished = FinishedClient()
    monkeypatch.setattr(doc_module, "client", finished)
    monkeypatch.setattr(doc_module, "POLL_INTERVAL_SECONDS", 0)
    bot = _FakeBot(b"")

    async def run() -> None:
        await doc_module.resume_tracked_tasks(bot)
        for _ in range(50):
            if not state_store.get_state_store().load_tasks():
                return
            await asyncio.sleep(0.01)

    asyncio.run(run())

    assert finished.registered == ("resumed-task", "resumed-token")
    assert any("download/resumed" in text for text in bot.sent)
    assert state_store.get_state_store().load_tasks() == []
    assert user_context.user_task_ids[(123, None, 456)] == "resumed-task"


def test_resume_treats_a_missing_job_as_final(monkeypatch) -> None:
    """A 404 removes the persisted row instead of retrying for the full deadline (#396)."""
    state_store.get_state_store().save_task(
        (123, None, 456),
        "gone-task",
        filename="gone.pdf",
        job_token=None,
        email=None,
    )

    class MissingClient:
        async def get_job_status(self, task_id: str) -> dict:
            raise ApiError(404, "Job not found")

    monkeypatch.setattr(doc_module, "client", MissingClient())
    monkeypatch.setattr(doc_module, "POLL_INTERVAL_SECONDS", 0)
    bot = _FakeBot(b"")

    async def run() -> None:
        await doc_module.resume_tracked_tasks(bot)
        for _ in range(50):
            if not state_store.get_state_store().load_tasks():
                return
            await asyncio.sleep(0.01)

    asyncio.run(run())

    assert state_store.get_state_store().load_tasks() == []
    assert bot.sent


def test_cancel_removes_the_persisted_task(monkeypatch) -> None:
    """A successful /cancel must not leave a row that is resumed later (#396)."""
    state_key = (123, None, 456)
    state_store.get_state_store().save_task(
        state_key,
        "cancelled-task",
        filename="cancel.pdf",
        job_token=None,
        email=None,
    )
    user_context.user_task_ids[state_key] = "cancelled-task"

    monkeypatch.setattr(start_module, "client", _CancelClient())
    message = _FakeMessage(_FakeBot(b""), chat_id=123, user_id=456)

    asyncio.run(start_module.cmd_cancel(message))

    assert state_store.get_state_store().load_tasks() == []
    assert state_key not in user_context.user_task_ids


def test_cancel_warns_with_the_store_error(monkeypatch) -> None:
    """The /cancel warning formats the SQLite error with loguru (#759)."""
    state_key = (123, None, 456)
    user_context.user_task_ids[state_key] = "cancelled-task"

    class FailingStore:
        def remove_task(self, state_key: tuple[int, int | None, int], task_id: str) -> None:
            raise sqlite3.Error("down")

    monkeypatch.setattr(start_module, "get_state_store", FailingStore)
    monkeypatch.setattr(start_module, "client", _CancelClient())
    message = _FakeMessage(_FakeBot(b""), chat_id=123, user_id=456)

    warnings = StringIO()
    sink = start_module.logger.add(warnings, level="WARNING", format="{message}")
    try:
        asyncio.run(start_module.cmd_cancel(message))
    finally:
        start_module.logger.remove(sink)

    assert _state_store_warnings(warnings) == [
        "Telegram state store unavailable: down"
    ]


def test_resume_warns_with_the_store_error(monkeypatch) -> None:
    """Restoring followed tasks formats the SQLite error with loguru (#759)."""

    class FailingStore:
        def load_tasks(self) -> list:
            raise sqlite3.Error("down")

    monkeypatch.setattr(doc_module, "get_state_store", FailingStore)

    warnings = StringIO()
    sink = doc_module.logger.add(warnings, level="WARNING", format="{message}")
    try:
        asyncio.run(doc_module.resume_tracked_tasks(_FakeBot(b"")))
    finally:
        doc_module.logger.remove(sink)

    assert _state_store_warnings(warnings) == [
        "Telegram state store unavailable: down"
    ]


def test_process_file_warns_when_saving_and_clearing_the_row_fail(
    monkeypatch, tmp_path
) -> None:
    """Saving a new task and clearing it after polling both log the SQLite error (#759)."""

    class FailingStore:
        def save_task(self, *args, **kwargs) -> None:
            raise sqlite3.Error("down")

        def remove_task(self, *args, **kwargs) -> None:
            raise sqlite3.Error("down")

    class SubmitClient:
        async def submit_job(self, input_path, filename, **kwargs) -> dict:
            return {"task_id": "task-1", "job_token": "token"}

    async def finished(*args, **kwargs) -> str:
        return "done"

    monkeypatch.setattr(settings, "temp_dir", tmp_path / "tmp")
    monkeypatch.setattr(doc_module, "get_state_store", FailingStore)
    monkeypatch.setattr(doc_module, "client", SubmitClient())
    monkeypatch.setattr(doc_module, "_poll_job", finished)
    message = _FakeMessage(_FakeBot(b"content"), chat_id=123, user_id=456)

    warnings = StringIO()
    sink = doc_module.logger.add(warnings, level="WARNING", format="{message}")
    try:
        asyncio.run(doc_module.process_file(message, "file1", "doc.pdf"))
    finally:
        doc_module.logger.remove(sink)

    assert _state_store_warnings(warnings) == [
        "Telegram state store unavailable: down",
        "Telegram state store unavailable: down",
    ]


def test_resume_task_warns_when_clearing_the_row_fails(monkeypatch) -> None:
    """Resuming a finished task formats the SQLite error with loguru (#759)."""

    class FailingStore:
        def remove_task(self, *args, **kwargs) -> None:
            raise sqlite3.Error("down")

    async def finished(*args, **kwargs) -> str:
        return "done"

    monkeypatch.setattr(doc_module, "get_state_store", FailingStore)
    monkeypatch.setattr(doc_module, "_poll_job", finished)
    task = state_store.TrackedTask(
        chat_id=123,
        message_thread_id=None,
        user_id=456,
        task_id="task-1",
        filename="doc.pdf",
    )

    warnings = StringIO()
    sink = doc_module.logger.add(warnings, level="WARNING", format="{message}")
    try:
        asyncio.run(doc_module._resume_task(_FakeBot(b""), task))
    finally:
        doc_module.logger.remove(sink)

    assert _state_store_warnings(warnings) == [
        "Telegram state store unavailable: down"
    ]
