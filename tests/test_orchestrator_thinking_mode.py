from __future__ import annotations

import asyncio
from pathlib import Path

from backend.agents.orchestrator import AccessibilityOrchestrator
from backend.agents.types import RegionTask


class _FakeStructurer:
    name = "fake"


class _FakeReader:
    structurer = _FakeStructurer()

    def analyse_page(
        self,
        _page_path: Path,
        page_num: int,
        _total_pages: int,
        _is_pdf: bool,
    ) -> list[RegionTask]:
        return [
            RegionTask(
                agent_target="vision",
                classification="full_page_image",
                image_bytes=b"image",
                page_num=page_num,
            )
        ]


class _FakeEditor:
    def consolidate_page(self, _tasks, results) -> str:
        return results[0]


def test_thinking_mode_changes_dispatched_prompt(monkeypatch, tmp_path):
    from backend.agents import orchestrator as orchestrator_module

    async def no_cache(*args, **kwargs):
        return None

    async def ignore_cache_write(*args, **kwargs):
        return None

    async def run_inline(function, *args):
        return function(*args)

    monkeypatch.setattr(orchestrator_module, "get_cached", no_cache)
    monkeypatch.setattr(orchestrator_module, "set_cache", ignore_cache_write)
    monkeypatch.setattr(orchestrator_module.asyncio, "to_thread", run_inline)

    orchestrator = AccessibilityOrchestrator.__new__(AccessibilityOrchestrator)
    orchestrator.mode = "medio"
    orchestrator.reader = _FakeReader()
    orchestrator.editor = _FakeEditor()
    orchestrator._reader_lock = asyncio.Lock()
    dispatched_prompts: list[str | None] = []

    async def capture_dispatch(_tasks, _page_num, _total_pages, _mode, custom_prompt):
        dispatched_prompts.append(custom_prompt)
        return {0: "description"}

    orchestrator._dispatch_tasks = capture_dispatch
    image = tmp_path / "document.png"
    image.write_bytes(b"image")

    async def run_both_modes():
        await orchestrator.executar(image, tmp_path, thinking_mode=False)
        await orchestrator.executar(image, tmp_path, thinking_mode=True)

    asyncio.run(run_both_modes())

    assert dispatched_prompts[0] is None
    assert dispatched_prompts[1] is not None
    assert dispatched_prompts[1].startswith("<|think|>\n")
