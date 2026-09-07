from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_cached_submission_is_recorded_in_history(tmp_path, monkeypatch, request):
    from backend import service
    from backend.agents.state_manager import state_manager
    from backend.config.settings import settings
    from backend.services import history_service

    if history_service._connection is not None:
        history_service._connection.close()
    history_service._connection = None
    monkeypatch.setattr(settings, "data_dir", tmp_path)

    def close_history_connection():
        if history_service._connection is not None:
            history_service._connection.close()
            history_service._connection = None

    request.addfinalizer(close_history_connection)

    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.write_bytes(b"same content")
    second.write_bytes(b"same content")
    cached_payload = {
        "text": "Accessible content",
        "pages": [],
        "page_count": 1,
        "mode": "normal",
    }
    cache: dict[tuple[bytes, str], object] = {}

    async def get_from_memory(path: Path, extra: str):
        return cache.get((path.read_bytes(), extra))

    async def set_in_memory(path: Path, payload, extra: str):
        cache[(path.read_bytes(), extra)] = payload

    class Agent:
        calls = 0

        async def executar(self, *_args, **_kwargs):
            self.calls += 1
            return cached_payload

    agent = Agent()
    state_manager._tasks.clear()
    state_manager._cancel_events.clear()
    monkeypatch.setattr(service, "agente", agent)
    monkeypatch.setattr(service, "get_cached", get_from_memory)
    monkeypatch.setattr(service, "set_cache", set_in_memory)
    monkeypatch.setattr(service, "_salvar_json_canonico", lambda *_args: None)

    await service.process(first)
    await service.process(second)

    rows = await history_service.listar_historico(10)
    assert agent.calls == 1
    assert len(rows) == 2
    assert {row["arquivo"] for row in rows} == {"first.png", "second.png"}
    assert {row["status"] for row in rows} == {"done"}
