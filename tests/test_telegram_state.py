"""Telegram state survives a bot restart: paused chats and followed tasks (#396)."""

from __future__ import annotations

import asyncio

import pytest

from backend.config.settings import settings
from frontend.telegram import state_store, user_context
from frontend.telegram.handlers import document as doc_module
from frontend.telegram.handlers import start as start_module
from frontend.clients.api_client import ApiError
from frontend.telegram.middlewares import pause_middleware
from frontend.telegram.state_store import TelegramStateStore
from tests.test_telegram_client import _FakeBot, _FakeMessage


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

    class CancelClient:
        async def cancel_job(self, task_id: str) -> dict:
            return {"task_id": task_id}

    monkeypatch.setattr(start_module, "client", CancelClient())
    message = _FakeMessage(_FakeBot(b""), chat_id=123, user_id=456)

    asyncio.run(start_module.cmd_cancel(message))

    assert state_store.get_state_store().load_tasks() == []
    assert state_key not in user_context.user_task_ids
