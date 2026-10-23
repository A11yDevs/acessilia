"""Regressions for description provenance, table certification and failed plans."""

from types import SimpleNamespace

import pytest

from backend.agents import pddl_orchestrator as pddl
from tests.pddl_support import (
    build_element as _element,
    build_manifest as _manifest,
    build_obligation as _obligation,
    build_orchestrator as _orchestrator,
)
from tests.test_pending_fixes import isolated_runtime as runtime_fixture

isolated_runtime = runtime_fixture


@pytest.mark.parametrize("text", ["Map", "Logo", "A"])
def test_completed_short_vision_description_is_valid(text):
    element = _element(
        "image", "picture", text=text, metadata={"vision_description_complete": True}
    )
    manifest = _manifest(
        [element], [_obligation("describe-image", ["image"], ["vision-description"])]
    )
    result = pddl._handle_vision_description_method(manifest, "o-1")
    assert result.success and result.validated
    element.metadata.clear()
    assert not pddl._handle_vision_description_method(manifest, "o-1").success


@pytest.mark.parametrize("text", [None, "", "   "])
def test_completed_flag_does_not_certify_empty_description(text):
    element = _element(
        "image", "picture", text=text, metadata={"vision_description_complete": True}
    )
    manifest = _manifest(
        [element], [_obligation("describe-image", ["image"], ["vision-description"])]
    )
    assert not pddl._handle_vision_description_method(manifest, "o-1").success


@pytest.mark.parametrize("ast", [
    {"rows": []}, {"body": []}, {"invalid": True},
    {"body": [{"cells": [{"text": " "}]}]},
    {"body": [{"cells": [{"text": "Tabela detectada"}]}]},
    {"body": [{"cells": [{"text": "Value", "metadata": {"column_index": 100000}}]}]},
])
def test_unusable_table_does_not_satisfy_obligation(ast):
    manifest = _manifest(
        [_element("table", "table", metadata={"table_ast": ast})],
        [_obligation("linearize-table", ["table"], ["pandoc-table", "human-review"])],
    )
    manifest.obligations[0].method_costs = {"pandoc-table": 1, "human-review": 100}
    orchestrator = _orchestrator()
    plan, _ = orchestrator._build_plan(manifest)
    updated, report = orchestrator.executor.execute(plan, manifest, dry_run=False)
    assert report.status == "replan-required"
    assert updated.obligations[0].status == "pending"
    assert updated.obligations[0].attempts[0].status == "failed"


def failed_manifest(methods):
    return _manifest(
        [_element("paragraph", "paragraph", text="A document with content."),
         _element("image", "picture")],
        [_obligation("describe-image", ["image"], methods)],
    )


@pytest.mark.parametrize("methods", [["human-review"], ["vision-description", "human-review"]])
def test_diagnostic_payload_warns_about_failed_or_pending_execution(tmp_path, methods):
    manifest = failed_manifest(methods)
    manifest.obligations[0].method_costs = {method: i + 1 for i, method in enumerate(methods)}
    orchestrator = _orchestrator()
    plan, _ = orchestrator._build_plan(manifest)
    updated, report = orchestrator.executor.execute(plan, manifest, dry_run=False)
    assert report.status in {"failed", "replan-required"}
    payload = pddl.build_pddl_structured_payload(
        file_path=tmp_path / "doc.pdf", manifest=updated, plan=plan,
        planner_backend="internal", execution_report=report, comparison=None,
    )
    assert payload["technical_warnings"]
    assert "describe-image" in payload["technical_warnings"][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("methods", [["human-review"], ["vision-description", "human-review"]])
async def test_orchestration_rejects_failed_or_exhausted_plan(monkeypatch, tmp_path, methods):
    manifest = failed_manifest(methods)
    manifest.obligations[0].method_costs = {method: i + 1 for i, method in enumerate(methods)}
    orchestrator = _orchestrator(max_replans=0)
    orchestrator.information_structural = SimpleNamespace(process=lambda *a, **k: manifest)

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(pddl, "inspect_source_media", noop)
    monkeypatch.setattr(pddl, "_enrich_picture_descriptions", noop)
    monkeypatch.setattr(pddl, "_enrich_table_structures", noop)
    with pytest.raises(RuntimeError, match="describe-image"):
        await orchestrator.executar(tmp_path / "doc.pdf", tmp_path, structured_output=True)


@pytest.mark.asyncio
async def test_failed_plan_marks_api_job_error_without_caching_or_download(
    isolated_runtime, monkeypatch, tmp_path
):
    from backend import service
    from backend.api import worker
    from backend.services import job_store

    _, manager = isolated_runtime
    manifest = failed_manifest(["human-review"])
    orchestrator = _orchestrator()
    orchestrator.information_structural = SimpleNamespace(process=lambda *a, **k: manifest)

    async def noop(*args, **kwargs):
        return None

    async def forbidden(*args, **kwargs):
        pytest.fail("A failed plan must not be cached or published")

    monkeypatch.setattr(pddl, "inspect_source_media", noop)
    monkeypatch.setattr(pddl, "_enrich_picture_descriptions", noop)
    monkeypatch.setattr(pddl, "_enrich_table_structures", noop)
    monkeypatch.setattr(service, "agente", orchestrator)
    monkeypatch.setattr(service, "get_cached", noop)
    monkeypatch.setattr(service, "set_cache", forbidden)
    monkeypatch.setattr(worker, "criar_token", forbidden)
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"%PDF")
    job_store.save_request("failed-plan", "token", {}, {"status": "queued"})
    executor = worker.JobExecutor()
    try:
        await executor.run(worker.ApiJob("failed-plan", source, "doc.pdf"))
        status = manager.obter("failed-plan")
        assert status["status"] == "error"
        assert any("describe-image" in error for error in status["erros"])
        assert not status.get("download_url")
        assert job_store.load_record("failed-plan")["status"]["status"] == "error"
        assert not source.exists()
    finally:
        executor._executor.shutdown(wait=True)
