from __future__ import annotations

import asyncio
from pathlib import Path


def test_document_cache_key_changes_with_each_processing_option(monkeypatch):
    from backend import service

    monkeypatch.setattr(service.settings, "ai_client", "fake")
    monkeypatch.setattr(service.settings, "pipeline_engine", "legacy")

    base = service._cache_version("normal", None, False)

    assert service._cache_version("detailed", None, False) != base
    assert service._cache_version("normal", "Describe charts", False) != base
    assert service._cache_version("normal", None, True) != base
    assert service._cache_version("normal", None, False) == base


def test_page_cache_key_changes_with_prompt_and_thinking_mode(monkeypatch, tmp_path):
    from backend.agents import orchestrator as orchestrator_module
    from backend.agents.orchestrator import AccessibilityOrchestrator

    observed_keys: list[str] = []

    async def cache_miss(_path, extra, **_kwargs):
        observed_keys.append(extra)
        return None

    async def ignore_cache_write(*_args, **_kwargs):
        return None

    async def run_inline(function, *args):
        return function(*args)

    class Reader:
        structurer = type("Structurer", (), {"name": "fake"})()

        def analyse_page(self, *_args):
            return []

    class Editor:
        def consolidate_page(self, _tasks, _results):
            return "page result"

    monkeypatch.setattr(orchestrator_module, "get_cached", cache_miss)
    monkeypatch.setattr(orchestrator_module, "set_cache", ignore_cache_write)
    monkeypatch.setattr(orchestrator_module.asyncio, "to_thread", run_inline)

    orchestrator = AccessibilityOrchestrator.__new__(AccessibilityOrchestrator)
    orchestrator.mode = "medio"
    orchestrator.reader = Reader()
    orchestrator.editor = Editor()
    orchestrator._reader_lock = asyncio.Lock()

    image = tmp_path / "page.png"
    image.write_bytes(b"same image")

    async def exercise_options():
        await orchestrator.executar(image, tmp_path, custom_prompt="first")
        await orchestrator.executar(image, tmp_path, custom_prompt="second")
        await orchestrator.executar(
            image, tmp_path, custom_prompt="first", thinking_mode=True
        )

    asyncio.run(exercise_options())

    assert len(set(observed_keys)) == 3


def test_cached_payload_rebuilds_current_submission_metadata(monkeypatch, tmp_path):
    from backend import service

    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.write_bytes(b"same image")
    second.write_bytes(b"same image")
    cache: dict[tuple[bytes, str], object] = {}

    async def get_from_memory(path: Path, extra: str):
        return cache.get((path.read_bytes(), extra))

    async def set_in_memory(path: Path, payload, extra: str):
        cache[(path.read_bytes(), extra)] = payload

    class Agent:
        calls = 0

        async def executar(self, file_path, *_args, **_kwargs):
            self.calls += 1
            return {
                "text": "Accessible content",
                "pages": [
                    {
                        "page_number": 1,
                        "file_path": str(file_path),
                        "text": "Accessible content",
                        "blocks": [],
                    }
                ],
                "page_count": 1,
                "mode": "normal",
                "source_path": str(file_path),
                "canonical_metadata": {"preserved": True},
                "technical_warnings": ["warning"],
            }

    agent = Agent()
    monkeypatch.setattr(service, "agente", agent)
    monkeypatch.setattr(service, "get_cached", get_from_memory)
    monkeypatch.setattr(service, "set_cache", set_in_memory)
    monkeypatch.setattr(service, "registrar_conversao", _async_noop)
    monkeypatch.setattr(service, "_salvar_json_canonico", lambda *_args: None)
    monkeypatch.setattr(service.state_manager, "criar_tarefa", lambda *_args, **_kwargs: "task")
    monkeypatch.setattr(service.state_manager, "atualizar", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        service.state_manager, "verificar_cancelamento", lambda *_args: None
    )

    async def process_both():
        first_result = await service.process(first, task_id="first-task")
        second_result = await service.process(second, task_id="second-task")
        return first_result, second_result

    first_result, second_result = asyncio.run(process_both())

    assert agent.calls == 1
    assert first_result["source"]["name"] == "first.png"
    assert second_result["source"]["name"] == "second.png"
    assert second_result["source"]["path"] == str(second)
    assert second_result["metadata"]["pages"][0]["file_path"] == str(second)
    assert second_result["metadata"]["preserved"] is True
    assert second_result["technical_warnings"] == ["warning"]
    assert first_result["id"] != second_result["id"]


async def _async_noop(*_args, **_kwargs):
    return None
