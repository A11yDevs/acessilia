"""Native process isolation, reuse and lifecycle checks for document crops."""
import asyncio
import multiprocessing
import os
from types import SimpleNamespace

import pymupdf
import pytest

from backend.agents import pddl_orchestrator as pipeline
from backend.tools import region_extractor as regions
from tests.test_pddl_crop_contract import element, manifest, pixels, source


_opens = 0


def _initialize_counted_worker(path):
    global _opens
    _opens = 0
    regions._initialize_crop_worker(path)
    original = regions.fitz.open

    def open_document(*args, **kwargs):
        global _opens
        _opens += 1
        return original(*args, **kwargs)

    regions.fitz.open = open_document


def _worker_state():
    return os.getpid(), _opens, regions._crop_document.name


async def _state(reader):
    return await asyncio.wrap_future(reader._pool.submit(_worker_state))


@pytest.mark.asyncio
async def test_source_opened_once_and_crop_errors_do_not_discard_session(source, monkeypatch):
    monkeypatch.setattr(regions, "_initialize_crop_worker", _initialize_counted_worker)
    async with regions.PdfRegionReader(source) as reader:
        first = await reader.crop(element(1), None)
        pid, opens, name = await _state(reader)
        assert pid != os.getpid() and opens == 1 and name == str(source)
        assert await reader.crop(element(2, page=99), None) == (None, 99)
        assert await reader.crop(element(3), None) == first
        assert await _state(reader) == (pid, 1, str(source))
    assert pid not in {child.pid for child in multiprocessing.active_children()}


@pytest.mark.asyncio
async def test_missing_source_propagates_and_worker_is_reaped(tmp_path):
    children = {child.pid for child in multiprocessing.active_children()}
    with pytest.raises(RuntimeError, match="no such file"):
        async with regions.PdfRegionReader(tmp_path / "missing.pdf") as reader:
            await reader.crop(element(1), None)
    assert {child.pid for child in multiprocessing.active_children()} == children


@pytest.mark.asyncio
async def test_no_source_or_worker_needed_for_elements_without_page(tmp_path):
    async with regions.PdfRegionReader(tmp_path / "missing.pdf") as reader:
        assert await reader.crop(element(1, page=None), None) == (None, 0)
        assert reader._pool is None


@pytest.mark.asyncio
async def test_parallel_documents_keep_their_own_native_handles(source, tmp_path):
    other = tmp_path / "other.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page(width=40, height=80)
        pdf.save(other)
    async with regions.PdfRegionReader(source) as first, regions.PdfRegionReader(other) as second:
        crops = await asyncio.gather(first.crop(element(1), None), second.crop(element(1), None))
        states = await asyncio.gather(_state(first), _state(second))
        assert states[0][0] != states[1][0]
        assert states[0][2] == str(source) and states[1][2] == str(other)
        assert pixels(crops[0][0])[:2] != pixels(crops[1][0])[:2]
    assert not {state[0] for state in states} & {child.pid for child in multiprocessing.active_children()}


@pytest.mark.asyncio
@pytest.mark.parametrize("dry_run", [True, False])
async def test_orchestrator_reuses_reader_across_phases_and_preserves_dry_run(source, monkeypatch, dry_run):
    from backend.agents.output_schemas import DataOutput, VisionOutput
    from backend.core.execution.models import ExecutionReport
    from tests.test_pddl_orchestrator import _sample_plan

    monkeypatch.setattr(regions, "_initialize_crop_worker", _initialize_counted_worker)
    document = manifest(source, [element(1), element(2, kind="table")])
    calls = []
    states = []
    original_crop = regions.PdfRegionReader.crop

    async def crop(reader, item, fallback):
        result = await original_crop(reader, item, fallback)
        states.append((reader, await _state(reader)))
        return result

    class Vision:
        def __init__(self, **kwargs):
            pass

        async def describe_region(self, **kwargs):
            calls.append("vision")
            return VisionOutput(kind="description", description="A green rectangle", language="en", confidence=0.9)

    class Data:
        async def process_region(self, **kwargs):
            calls.append("data")
            return DataOutput(kind="table", language="en", confidence=0.8, rows=[{"cells": [{"text": "value"}]}])

    plan = _sample_plan().model_copy(update={"manifest_id": document.manifest_id, "selected_obligations": []})

    def build_plan(result):
        assert result is document and result.elements[0].text == "A green rectangle"
        assert result.elements[1].metadata["table_ast"]["body"]
        assert all(reader._pool is None for reader, _ in states)
        calls.append("plan")
        return plan, None

    def execute(*args, **kwargs):
        assert kwargs == {"dry_run": True}
        calls.append("dry-run")
        return document, ExecutionReport(plan_id=plan.plan_id, manifest_id=document.manifest_id,
                                         started_at=document.created_at, completed_at=document.created_at,
                                         execution_id="crop-execution", manifest_revision_before=1,
                                         manifest_revision_after=1, mode="dry-run", status="dry-run-completed",
                                         replan_required=False, steps=[])

    # Keep the real coordinator and rendering; replace only extraction, AI and planner/executor boundaries.
    orchestrator = object.__new__(pipeline.PddlAccessibilityOrchestrator)
    orchestrator.information_structural = SimpleNamespace(process=lambda *a, **k: document)
    orchestrator._build_plan = build_plan
    orchestrator.executor = SimpleNamespace(execute=execute)
    orchestrator.execute_dry_run = dry_run
    orchestrator.planner_backend = "internal"
    monkeypatch.setattr(regions.PdfRegionReader, "crop", crop)
    monkeypatch.setattr(pipeline, "VisionAgent", Vision)
    monkeypatch.setattr(pipeline, "DataAgent", Data)
    statuses = []

    async def status(value):
        statuses.append(value)

    output = await orchestrator.executar(source, source.parent, status_callback=status, structured_output=True)
    assert "A green rectangle" in output["text"]
    assert calls == ["vision", "data", "plan"] + (["dry-run"] if dry_run else [])
    assert len(statuses) == (5 if dry_run else 4)
    assert states[0][0] is states[1][0]
    assert states[0][1] == states[1][1]
    assert states[0][1][1] == 1


@pytest.mark.asyncio
async def test_cancellation_during_render_reaps_worker(source):
    # Cancel after submission, before waiting for the PNG, rather than at the AI boundary.
    children = {child.pid for child in multiprocessing.active_children()}

    async def render():
        async with regions.PdfRegionReader(source) as reader:
            task = asyncio.create_task(reader.crop(element(1), None))
            await asyncio.sleep(0)
            task.cancel()
            await task

    with pytest.raises(asyncio.CancelledError):
        await render()
    assert {child.pid for child in multiprocessing.active_children()} == children
