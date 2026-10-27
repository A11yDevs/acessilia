"""Object markers in the delivered formats (OBJECT_MARKERS_ENABLED)."""

from __future__ import annotations

import json

import httpx
import pytest

from backend.api import worker
from backend.api.app import create_app
from backend.config.settings import settings
from backend.export.markers import (
    MSG_OBJECT_MARKER_FORMULA,
    MSG_OBJECT_MARKER_IMAGE,
    MSG_OBJECT_MARKER_TABLE,
    with_object_markers,
)
from backend.export.pandoc_exporter import export_accessible_document
from backend.i18n import t
from backend.services import job_store
from backend.services.job_store import load_record
from tests.test_pending_fixes import isolated_runtime  # noqa: F401  (fixture)
from tests.test_v2_security import isolated  # noqa: F401  (fixture)


def _canonical():
    return {
        "schema_version": "1.0.0",
        "id": "doc-deck",
        "title": "Deck",
        "language": "pt-BR",
        "sections": [
            {
                "id": "s-1",
                "title": "Slide 1",
                "level": 1,
                "blocks": [
                    {"id": "h-1", "type": "heading", "level": 1, "text": "Slide 1"},
                    {"id": "p-1", "type": "paragraph", "text": "Intro."},
                    {"id": "i-1", "type": "image", "alt_text": "A scale from 1nm to 10nm."},
                    {
                        "id": "t-1",
                        "type": "table",
                        "table_ast": {
                            "header": [{"cells": [{"text": "Isotope", "scope": "col"}, {"text": "Mass", "scope": "col"}]}],
                            "body": [{"cells": [{"text": "35Cl"}, {"text": "34.97"}]}],
                        },
                    },
                ],
                "children": [],
            }
        ],
    }


def _in_order(text: str, *parts: str) -> bool:
    position = 0
    for part in parts:
        position = text.find(part, position)
        if position < 0:
            return False
        position += len(part)
    return True


@pytest.mark.parametrize("format_name", ["html", "txt"])
def test_a_delivered_format_carries_the_markers_around_each_object(tmp_path, format_name):
    image, table = t(MSG_OBJECT_MARKER_IMAGE), t(MSG_OBJECT_MARKER_TABLE)
    marked = with_object_markers(_canonical(), True)

    path = export_accessible_document(
        marked, tmp_path / f"deck.{format_name}", format_name=format_name, title="Deck"
    )

    text = path.read_text(encoding="utf-8")
    assert _in_order(
        text, f"[{image}]", "A scale from 1nm to 10nm.", f"[/{image}]",
        f"[{table}]", "35Cl", f"[/{table}]",
    )


def test_the_pandoc_document_of_docx_and_pdf_ua_carries_them_too():
    from docstruct.export.pandoc_ast import build_pandoc_ast

    image = t(MSG_OBJECT_MARKER_IMAGE)
    ast = build_pandoc_ast(with_object_markers(_canonical(), True))

    assert f"[{image}]" in str(ast) and f"[/{image}]" in str(ast)


def test_a_formula_is_marked_as_a_formula():
    document = _canonical()
    document["sections"][0]["blocks"].append({"id": "m-1", "type": "math", "text": "x = y"})

    blocks = with_object_markers(document, True)["sections"][0]["blocks"]

    formula = t(MSG_OBJECT_MARKER_FORMULA)
    assert [b.get("text") for b in blocks[-3:]] == [f"[{formula}]", "x = y", f"[/{formula}]"]


@pytest.mark.parametrize(
    "setting, job, marked",
    [(False, None, False), (True, None, True), (True, False, False), (False, True, True)],
    ids=["off", "on-by-setting", "job-turns-off", "job-turns-on"],
)
def test_the_job_choice_wins_over_the_setting(monkeypatch, setting, job, marked):
    monkeypatch.setattr(settings, "object_markers_enabled", setting)
    document = _canonical()

    result = with_object_markers(document, job)

    assert (result is not document) is marked
    assert (len(result["sections"][0]["blocks"]) == 8) is marked


def test_markers_are_off_by_default(monkeypatch):
    monkeypatch.delenv("OBJECT_MARKERS_ENABLED", raising=False)

    assert settings.__class__().object_markers_enabled is False


@pytest.mark.asyncio
async def test_the_worker_marks_what_a_reader_gets_and_stores_the_document_unmarked(
    isolated_runtime, monkeypatch, tmp_path, fake_pdf_ua_audit  # noqa: F811
):
    _, manager = isolated_runtime
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"%PDF")
    job_store.save_request("marked", "capability", {}, {"status": "queued"})
    exported: dict[str, dict] = {}

    async def process(*a, **kw):
        return _canonical()

    def recorder(name):
        def export(document, destination, *a, **kw):
            exported[kw.get("format_name", name)] = document
            destination.write_text("output")

        return export

    async def audio(text, destination, **kw):
        destination.write_bytes(b"audio")

    async def no_email(*a, **kw):
        return False

    monkeypatch.setattr("backend.service.process", process)
    for name in ["export_txt", "export_docx", "export_pdf_ua", "export_drbench_md", "export_accessible_document"]:
        monkeypatch.setattr(worker, name, recorder(name))
    monkeypatch.setattr(worker, "export_mp3", audio)
    monkeypatch.setattr(worker, "send_confirmation_email", no_email)
    monkeypatch.setattr(worker, "send_result_email", no_email)
    monkeypatch.setattr(settings, "toolbox_docx_enabled", True)
    monkeypatch.setattr(settings, "toolbox_pdf_ua_enabled", True)
    executor = worker.JobExecutor()
    try:
        await executor.run(worker.ApiJob("marked", source, "doc.pdf", object_markers=True))
    finally:
        executor._executor.shutdown(wait=True)

    def markers(document):
        return [block["text"] for block in document["sections"][0]["blocks"] if block.get("metadata", {}).get("object_marker")]

    image, table = t(MSG_OBJECT_MARKER_IMAGE), t(MSG_OBJECT_MARKER_TABLE)
    expected = [f"[{image}]", f"[/{image}]", f"[{table}]", f"[/{table}]"]
    assert manager.obter("marked")["status"] == "done"
    for name in ["export_txt", "html", "export_docx", "export_pdf_ua"]:
        assert markers(exported[name]) == expected, name
    assert markers(exported["export_drbench_md"]) == []
    stored = json.loads(manager.obter("marked")["resultado"])
    assert markers(stored) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("sent, stored", [(None, None), ("true", True), ("false", False)])
async def test_a_job_can_ask_for_markers_through_the_api(isolated, sent, stored):  # noqa: F811
    data = {} if sent is None else {"object_markers": sent}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(create_app()), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/jobs",
            files={"document_file": ("doc.pdf", b"%PDF", "application/pdf")},
            data=data,
        )

    assert response.status_code == 202
    assert load_record(response.json()["task_id"])["request"]["object_markers"] is stored
