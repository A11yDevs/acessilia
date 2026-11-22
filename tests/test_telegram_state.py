"""Telegram state survives a bot restart: paused chats and followed tasks (#396)."""

from __future__ import annotations

import asyncio

import pytest

from backend.config.settings import settings
from frontend.telegram import state_store, user_context
from frontend.telegram.handlers import document as doc_module
from frontend.telegram.middlewares import pause_middleware
from frontend.telegram.state_store import TelegramStateStore
from tests.test_telegram_client import _FakeBot


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
        reply_to_message_id=5,
    )
    store.save_task(
        (1, 7, 10),
        "topic-task",
        filename="topic.pdf",
        job_token="topic-token",
        email=None,
        reply_to_message_id=8,
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
        reply_to_message_id=9,
    )
    assert {task.task_id for task in store.load_tasks()} == {
        "replacement",
        "topic-task",
    }

    store.remove_task((1, 7, 10))
    assert [task.task_id for task in store.load_tasks()] == ["replacement"]


def test_resume_delivers_the_finished_task_and_clears_it(monkeypatch) -> None:
    state_store.get_state_store().save_task(
        (123, None, 456),
        "resumed-task",
        filename="resumed.pdf",
        job_token="resumed-token",
        email=None,
        reply_to_message_id=999,
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
