"""Unit and integration tests for AccessibilityWorkflow in backend/agents/workflow.py."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

import backend.agents.workflow as wf_module
from backend.agents.types import RegionTask
from backend.agents.workflow import (
    AccessibilityOrchestrator,
    AccessibilityWorkflow,
    DocumentWorkflow,
)
from backend.i18n import t
from backend.services.cache import options_cache_key
from backend.stage_messages import (
    STAGE_PREPARING_IMAGE,
    STAGE_PROCESSING_PAGE,
    STAGE_SPLITTING_PDF_PAGES,
)


# ── Test Fakes & Helpers ──

class FakeStructurer:
    name = "pymupdf_test"


class FakeReader:
    def __init__(self, page_count: int = 1, tasks_per_page: list[RegionTask] | None = None):
        self.structurer = FakeStructurer()
        self.page_count = page_count
        self.tasks_per_page = tasks_per_page
        self.split_called = 0
        self.analyse_called = 0

    def split_file(self, file_path: Path, tmpdir: Path) -> list[Path]:
        self.split_called += 1
        if self.page_count == 0:
            return []
        pages = []
        for i in range(1, self.page_count + 1):
            p = tmpdir / f"page_{i}.png"
            p.write_bytes(b"page content")
            pages.append(p)
        return pages

    def analyse_page(
        self,
        page_path: Path,
        page_num: int,
        total_pages: int,
        is_pdf: bool,
    ) -> list[RegionTask]:
        self.analyse_called += 1
        if self.tasks_per_page is not None:
            return self.tasks_per_page
        return [
            RegionTask(
                agent_target="editor",
                classification="heading",
                text=f"Page {page_num} heading",
                page_num=page_num,
            ),
            RegionTask(
                agent_target="vision",
                classification="figure",
                image_bytes=b"figure_bytes",
                page_num=page_num,
            ),
        ]


class FakeVisionAgent:
    def __init__(self, mode: str = "medio"):
        self.mode = mode
        self.dispatched_prompts: list[str | None] = []
        self.calls: list[dict[str, Any]] = []

    async def describe_region(
        self,
        image_bytes: bytes,
        classification: str,
        page_num: int,
        total_pages: int,
        mode: str,
        custom_prompt: str | None,
    ) -> str:
        self.dispatched_prompts.append(custom_prompt)
        self.calls.append({
            "image_bytes": image_bytes,
            "classification": classification,
            "page_num": page_num,
            "total_pages": total_pages,
            "mode": mode,
            "custom_prompt": custom_prompt,
        })
        return f"[Vision: {classification} on page {page_num} mode={mode}]"


class FakeDataAgent:
    def __init__(self):
        self.calls: list[dict[str, Any]] = []

    async def process_region(
        self,
        image_bytes: bytes,
        classification: str,
        page_num: int,
        fallback_text: str = "",
    ) -> str:
        self.calls.append({
            "image_bytes": image_bytes,
            "classification": classification,
            "page_num": page_num,
            "fallback_text": fallback_text,
        })
        return f"[Data: {classification} table on page {page_num}]"


class FakeEditorAgent:
    def __init__(self, return_text: str | None = None):
        self.return_text = return_text
        self.consolidate_called = 0

    def consolidate_page(self, tasks: list[RegionTask], results: dict[int, str]) -> str:
        self.consolidate_called += 1
        if self.return_text is not None:
            return self.return_text
        lines = []
        for idx, t in enumerate(tasks):
            if idx in results:
                lines.append(results[idx])
            elif t.text:
                lines.append(t.text)
        return "\n".join(lines)


def build_test_workflow(
    mode: str = "medio",
    page_count: int = 1,
    tasks_per_page: list[RegionTask] | None = None,
    editor_text: str | None = None,
) -> AccessibilityWorkflow:
    """Builds a test workflow instance with injected fakes."""
    wf = AccessibilityWorkflow(mode=mode)
    wf.reader = FakeReader(page_count=page_count, tasks_per_page=tasks_per_page)
    wf.vision = FakeVisionAgent(mode=mode)
    wf.data = FakeDataAgent()
    wf.editor = FakeEditorAgent(return_text=editor_text)
    return wf


# ── Workflow Tests ──

@pytest.mark.asyncio
async def test_single_page_raster_image_plain_text(tmp_path, monkeypatch):
    """Scenario: PNG image processed with plain text (structured_output=False)."""
    wf = build_test_workflow(mode="medio")

    async def no_cache(*args, **kwargs):
        return None

    cache_writes: list[tuple[str, str, str]] = []

    async def wf_set_cache(path, text, key):
        cache_writes.append((str(path), text, key))

    monkeypatch.setattr(wf_module, "get_cached", no_cache)
    monkeypatch.setattr(wf_module, "set_cache", wf_set_cache)

    img_wf = tmp_path / "wf_doc.png"
    img_wf.write_bytes(b"image data")
    tmp_wf = tmp_path / "tmp_wf"
    tmp_wf.mkdir()

    res_wf = await wf.executar(img_wf, tmp_wf, structured_output=False, mode="medio")

    assert res_wf.startswith("=== Pagina 1 ===")
    assert "Page 1 heading" in res_wf
    assert "[Vision: figure on page 1 mode=medio]" in res_wf

    wf_file = tmp_wf / "imagen001.txt"
    assert wf_file.exists()
    assert wf_file.read_text(encoding="utf-8") == "Page 1 heading\n[Vision: figure on page 1 mode=medio]"
    assert len(cache_writes) == 1


@pytest.mark.asyncio
async def test_single_page_raster_image_jpg(tmp_path, monkeypatch):
    """Scenario: JPG image processed without PDF splitting."""
    wf = build_test_workflow(mode="detalhado")

    async def no_cache(*args, **kwargs):
        return None

    monkeypatch.setattr(wf_module, "get_cached", no_cache)
    monkeypatch.setattr(wf_module, "set_cache", AsyncMock())

    img = tmp_path / "photo.jpg"
    img.write_bytes(b"jpg bytes")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    res = await wf.executar(img, out_dir, mode="detalhado")

    assert wf.reader.split_called == 0
    assert wf.reader.analyse_called == 1
    assert "mode=detalhado" in res


@pytest.mark.asyncio
async def test_multipage_pdf_splitting(tmp_path, monkeypatch):
    """Scenario: 3-page PDF document splitting, per-page processing, and join."""
    wf = build_test_workflow(mode="medio", page_count=3)

    async def no_cache(*args, **kwargs):
        return None

    monkeypatch.setattr(wf_module, "get_cached", no_cache)
    monkeypatch.setattr(wf_module, "set_cache", AsyncMock())

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 mock")
    out_dir = tmp_path / "out_pdf"
    out_dir.mkdir()

    res = await wf.executar(pdf, out_dir, structured_output=False)

    assert wf.reader.split_called == 1
    assert wf.reader.analyse_called == 3
    assert wf.editor.consolidate_called == 3

    assert "=== Pagina 1 ===" in res
    assert "=== Pagina 2 ===" in res
    assert "=== Pagina 3 ===" in res

    for p in range(1, 4):
        f = out_dir / f"imagen{p:03d}.txt"
        assert f.exists()


@pytest.mark.asyncio
async def test_empty_pages_error(tmp_path, monkeypatch):
    """Scenario: Source file yields zero pages, raises RuntimeError."""
    wf = build_test_workflow(page_count=0)

    pdf = tmp_path / "corrupt.pdf"
    pdf.write_bytes(b"bad")

    with pytest.raises(RuntimeError, match="No pages could be generated"):
        await wf.executar(pdf, tmp_path)


@pytest.mark.asyncio
async def test_structured_output_dictionary(tmp_path, monkeypatch):
    """Scenario: structured_output=True returns dict with text, pages, page_count, mode, source_path."""
    wf = build_test_workflow(mode="medio", page_count=2)

    async def no_cache(*args, **kwargs):
        return None

    monkeypatch.setattr(wf_module, "get_cached", no_cache)
    monkeypatch.setattr(wf_module, "set_cache", AsyncMock())

    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF")
    out_dir = tmp_path / "out_struct"
    out_dir.mkdir()

    res = await wf.executar(pdf, out_dir, structured_output=True, mode="medio")

    assert isinstance(res, dict)
    assert "text" in res
    assert "pages" in res
    assert "page_count" in res
    assert "mode" in res
    assert "source_path" in res
    assert res["page_count"] == 2
    assert res["mode"] == "medio"
    assert len(res["pages"]) == 2
    assert res["pages"][0]["page_number"] == 1
    assert res["pages"][1]["page_number"] == 2
    assert res["pages"][0]["cached"] is False


@pytest.mark.asyncio
async def test_cache_hit_skips_reader_and_dispatch(tmp_path, monkeypatch):
    """Scenario: Cache hit returns cached page text, skips Reader analyse and Vision dispatch."""
    wf = build_test_workflow(mode="medio", page_count=2)

    cached_p1 = "Cached accessible content for page 1"

    async def fake_get_cached(path, extra, **_kwargs):
        if "page_1" in extra:
            return cached_p1
        return None

    set_cache_calls = []

    async def record_set_cache(path, text, key):
        set_cache_calls.append((str(path), text, key))

    monkeypatch.setattr(wf_module, "get_cached", fake_get_cached)
    monkeypatch.setattr(wf_module, "set_cache", record_set_cache)

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF")
    out_dir = tmp_path / "out_cache"
    out_dir.mkdir()

    res = await wf.executar(pdf, out_dir, structured_output=True, mode="medio")

    assert wf.reader.split_called == 1
    assert wf.reader.analyse_called == 1  # Only page 2
    assert len(wf.vision.calls) == 1      # Only page 2
    assert wf.editor.consolidate_called == 1  # Only page 2

    assert res["pages"][0]["cached"] is True
    assert res["pages"][0]["text"] == cached_p1
    assert res["pages"][1]["cached"] is False

    # Page 1 should not write intermediate file, Page 2 should
    assert not (out_dir / "imagen001.txt").exists()
    assert (out_dir / "imagen002.txt").exists()


@pytest.mark.asyncio
async def test_cache_miss_stores_page_response(tmp_path, monkeypatch):
    """Scenario: Cache miss writes response to cache with exact options_cache_key."""
    wf = build_test_workflow(mode="rapido")

    async def no_cache(*args, **kwargs):
        return None

    wf_saved = {}

    async def save_wf(_p, text, key):
        wf_saved[key] = text

    monkeypatch.setattr(wf_module, "get_cached", no_cache)
    monkeypatch.setattr(wf_module, "set_cache", save_wf)

    img = tmp_path / "page.png"
    img.write_bytes(b"data")

    await wf.executar(img, tmp_path, mode="rapido", custom_prompt="custom prompt", thinking_mode=True)

    expected_key = options_cache_key("page_1_v2", mode="rapido", custom_prompt="custom prompt", thinking_mode=True)
    assert expected_key in wf_saved


@pytest.mark.asyncio
async def test_thinking_mode_with_default_and_custom_prompts(tmp_path, monkeypatch):
    """Scenario: thinking_mode prepends <|think|> to prompt."""
    wf = build_test_workflow(mode="medio")

    async def no_cache(*args, **kwargs):
        return None

    monkeypatch.setattr(wf_module, "get_cached", no_cache)
    monkeypatch.setattr(wf_module, "set_cache", AsyncMock())

    img = tmp_path / "img.png"
    img.write_bytes(b"img")

    await wf.executar(img, tmp_path, thinking_mode=False)
    assert wf.vision.dispatched_prompts[0] is None

    await wf.executar(img, tmp_path, thinking_mode=True)
    assert wf.vision.dispatched_prompts[1].startswith("<|think|>\n")

    await wf.executar(img, tmp_path, custom_prompt="Focus on labels", thinking_mode=True)
    assert wf.vision.dispatched_prompts[2] == "<|think|>\nFocus on labels"


@pytest.mark.asyncio
async def test_intermediate_file_generation_utf8(tmp_path, monkeypatch):
    """Scenario: intermediate files written with UTF-8 characters."""
    special_text = "Seção 1: Parâmetro π ≈ 3.14159 — Álgebra & Geometria"
    wf = build_test_workflow(editor_text=special_text)

    async def no_cache(*args, **kwargs):
        return None

    monkeypatch.setattr(wf_module, "get_cached", no_cache)
    monkeypatch.setattr(wf_module, "set_cache", AsyncMock())

    img = tmp_path / "math.png"
    img.write_bytes(b"math")
    out_dir = tmp_path / "out_utf8"
    out_dir.mkdir()

    await wf.executar(img, out_dir)

    out_file = out_dir / "imagen001.txt"
    assert out_file.exists()
    assert out_file.read_text(encoding="utf-8") == special_text


@pytest.mark.asyncio
async def test_empty_page_fallback(tmp_path, monkeypatch):
    """Scenario: consolidated page text is empty, applies fallback label."""
    wf = build_test_workflow(editor_text="   \n  ")

    async def no_cache(*args, **kwargs):
        return None

    monkeypatch.setattr(wf_module, "get_cached", no_cache)
    monkeypatch.setattr(wf_module, "set_cache", AsyncMock())

    img = tmp_path / "blank.png"
    img.write_bytes(b"blank")

    res = await wf.executar(img, tmp_path)

    expected_fallback = "[Pagina 1: resposta vazia do modelo]"
    assert expected_fallback in res


@pytest.mark.asyncio
async def test_resilient_task_dispatch_exception_handling(tmp_path, monkeypatch):
    """Scenario: Exception in vision task falls back to region task text without failing page."""
    tasks = [
        RegionTask(agent_target="editor", classification="text", text="Safe text", page_num=1),
        RegionTask(
            agent_target="vision",
            classification="figure",
            text="Original figure caption fallback",
            image_bytes=b"bad_image",
            page_num=1,
        ),
    ]
    wf = build_test_workflow(tasks_per_page=tasks)

    async def failing_describe(*args, **kwargs):
        raise ConnectionError("AI model service unavailable")

    wf.vision.describe_region = failing_describe

    async def no_cache(*args, **kwargs):
        return None

    monkeypatch.setattr(wf_module, "get_cached", no_cache)
    monkeypatch.setattr(wf_module, "set_cache", AsyncMock())

    img = tmp_path / "fail.png"
    img.write_bytes(b"img")

    res = await wf.executar(img, tmp_path)

    assert "Safe text" in res
    assert "Original figure caption fallback" in res


@pytest.mark.asyncio
async def test_concurrency_reader_lock_protection(tmp_path, monkeypatch):
    """Scenario: _reader_lock ensures sequential execution of reader calls."""
    wf = build_test_workflow(page_count=3)

    lock_entered = 0
    max_concurrent = 0
    current_concurrent = 0

    original_lock = wf._reader_lock

    class InstrumentLock:
        async def __aenter__(self):
            nonlocal lock_entered, max_concurrent, current_concurrent
            await original_lock.acquire()
            lock_entered += 1
            current_concurrent += 1
            max_concurrent = max(max_concurrent, current_concurrent)
            await asyncio.sleep(0.005)
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            nonlocal current_concurrent
            current_concurrent -= 1
            original_lock.release()

    wf._reader_lock = InstrumentLock()

    async def no_cache(*args, **kwargs):
        return None

    monkeypatch.setattr(wf_module, "get_cached", no_cache)
    monkeypatch.setattr(wf_module, "set_cache", AsyncMock())

    pdf = tmp_path / "lock.pdf"
    pdf.write_bytes(b"%PDF")

    await wf.executar(pdf, tmp_path)

    assert max_concurrent == 1
    assert lock_entered == 4  # 1 for split_file + 3 for analyse_page


@pytest.mark.asyncio
async def test_multimodal_dispatch_data_and_vision(tmp_path, monkeypatch):
    """Scenario: Page contains both vision figure and data table tasks."""
    tasks = [
        RegionTask(
            agent_target="vision",
            classification="figure",
            image_bytes=b"fig_bytes",
            page_num=1,
        ),
        RegionTask(
            agent_target="data",
            classification="table",
            image_bytes=b"table_bytes",
            text="| Col A | Col B |",
            page_num=1,
        ),
    ]
    wf = build_test_workflow(tasks_per_page=tasks)

    async def no_cache(*args, **kwargs):
        return None

    monkeypatch.setattr(wf_module, "get_cached", no_cache)
    monkeypatch.setattr(wf_module, "set_cache", AsyncMock())

    img = tmp_path / "mixed.png"
    img.write_bytes(b"mixed")

    res = await wf.executar(img, tmp_path)

    assert len(wf.vision.calls) == 1
    assert len(wf.data.calls) == 1
    assert "[Vision: figure on page 1 mode=medio]" in res
    assert "[Data: table table on page 1]" in res


def test_document_workflow_alias():
    """Verifies that DocumentWorkflow and AccessibilityOrchestrator alias AccessibilityWorkflow."""
    assert DocumentWorkflow is AccessibilityWorkflow
    assert AccessibilityOrchestrator is AccessibilityWorkflow
