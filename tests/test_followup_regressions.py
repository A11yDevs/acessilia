"""Regressions for content, download, cache and async cleanup failures."""
import asyncio
from pathlib import Path

import pytest

from docstruct.tables.ast import linearize_table_for_text
from docstruct.export.html import document_to_html


def test_text_export_merged_cells_have_all_headers():
    table = {"header": [{"cells": [{"text": "AB", "colspan": 2}, {"text": "C"}]}],
             "body": [{"cells": [{"text": "A"}, {"text": "BC", "colspan": 2}]}]}
    assert linearize_table_for_text({"table_ast": table}) == ["Row 1: AB: A; AB / C: BC"]


def test_text_export_multi_level_headers_and_rowspans():
    table = {"header": [
        {"cells": [{"text": "Name", "rowspan": 2}, {"text": "Values", "colspan": 2}]},
        {"cells": [{"text": "X"}, {"text": "Y"}]},
    ], "body": [
        {"cells": [{"text": "Alice", "rowspan": 2}, {"text": "1"}, {"text": "2"}]},
        {"cells": [{"text": "3"}, {"text": "4"}]},
    ]}
    assert linearize_table_for_text({"table_ast": table}) == [
        "Row 1: Name: Alice; Values - X: 1; Values - Y: 2",
        "Row 2: Name: Alice; Values - X: 3; Values - Y: 4",
    ]


@pytest.mark.parametrize("mathml,valid", [
    ('<math xmlns="http://www.w3.org/1998/Math/MathML"><mi>x</mi><mo>=</mo><mn>1</mn></math>', True),
    ('<math><mfrac><mi>x</mi><mn>2</mn></mfrac></math>', True),
    ('<math><script>alert(1)</script></math>', False),
    ('<math onclick="alert(1)"><mi>x</mi></math>', False),
    ('<math><mi href="javascript:alert(1)">x</mi></math>', False),
    ('<!DOCTYPE math [<!ENTITY x "boom">]><math>&x;</math>', False),
    ('<math><mi>unclosed', False),
    (None, False),
    ("<math>" + "<mrow>" * 150 + "<mi>x</mi>" + "</mrow>" * 150 + "</math>", False),
])
def test_mathml_is_validated_before_html_rendering(mathml, valid):
    block = {"type": "math", "id": "formula", "text": "x=1", "alt_text": "x equals one",
             "metadata": {"mathml": mathml}}
    rendered = document_to_html({"title": "Math", "sections": [{"blocks": [block]}]}, profile="html")
    assert ('<math xmlns=' in rendered) == valid
    assert 'aria-label="x equals one"' in rendered
    assert '<script' not in rendered
    assert 'onclick=' not in rendered
    assert 'javascript:' not in rendered
    if not valid:
        assert '>x=1</p>' in rendered


def test_pending_jobs_preserve_insertion_order(monkeypatch, tmp_path):
    from backend.services import job_store
    monkeypatch.setattr(job_store.settings, "data_dir", tmp_path)
    for task_id in ["z-first", "m-second", "a-last"]:
        job_store.save_request(task_id, "token", {}, {"status": "queued"})
    job_store.save_status("m-second", {"status": "processing"})
    assert [r["task_id"] for r in job_store.pending_records()] == ["z-first", "m-second", "a-last"]


@pytest.mark.parametrize("field,value", [
    ("ollama_model", "another-model"), ("ollama_base_url", "http://new.invalid"),
    ("openrouter_model", "another-model"), ("openrouter_max_tokens", 12),
    ("toolbox_provider", "another-provider"), ("fusion_mode", "dual"),
])
def test_document_cache_changes_with_model_and_provider(monkeypatch, field, value):
    from backend import service
    before = service._cache_version()
    monkeypatch.setattr(service.settings, field, value)
    assert service._cache_version() != before
    assert service._cache_version() == service._cache_version()


def test_document_cache_excludes_credentials(monkeypatch):
    from backend import service
    before = service._cache_version()
    monkeypatch.setattr(service.settings, "ollama_api_key", "private-secret")
    monkeypatch.setattr(service.settings, "toolbox_api_key", "private-secret")
    assert service._cache_version() == before


@pytest.mark.parametrize("cancel", [False, True])
def test_audio_failure_or_cancellation_joins_siblings_before_cleanup(monkeypatch, tmp_path, cancel):
    from backend.export.exporters import audio_exporter
    finished = []
    started = asyncio.Event()
    sibling_started = asyncio.Event()

    class Communicate:
        def __init__(self, text, voice):
            self.text = text

        async def save(self, path):
            Path(path).write_bytes(b"partial")
            if self.text.startswith("A"):
                started.set()
                await sibling_started.wait()
                if not cancel:
                    raise OSError("synthetic failure")
                await asyncio.Event().wait()
            else:
                sibling_started.set()
                try:
                    await asyncio.sleep(1)
                    Path(path).write_bytes(b"late result")
                finally:
                    finished.append("sibling exited")

    monkeypatch.setattr(audio_exporter.edge_tts, "Communicate", Communicate)
    progress = []

    async def report(value):
        progress.append(value)

    async def run():
        task = asyncio.create_task(audio_exporter.export_mp3("A" * 1490 + "\n" + "B" * 1490,
            tmp_path / "audio.mp3", progress_callback=report))
        await started.wait()
        await sibling_started.wait()
        if cancel:
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else OSError):
            await task
        assert finished == ["sibling exited"]
        assert not list(tmp_path.glob("*.part*.mp3"))
        assert not progress

    asyncio.run(run())


def test_drbench_markdown_remains_internal(monkeypatch, tmp_path):
    from backend.config.settings import settings
    from backend.services import download_token_service as tokens
    from backend.api.app import app
    from fastapi.testclient import TestClient
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(tokens, "_connection", None)
    output = tmp_path / "output"
    output.mkdir()
    internal_file = output / "doc.drbench.md"
    internal_file.write_text("# Example", encoding="utf-8")
    (output / "doc.txt").write_text("Example", encoding="utf-8")
    try:
        token = asyncio.run(tokens.criar_token(output, "doc", formats=["txt", "drbench_md"]))
        info = asyncio.run(tokens.obter_info_token(token))
        assert [item["ext"] for item in info["formats"]] == ["txt"]
        response = TestClient(app).get(f"/api/v1/download/{token}/drbench_md")
        assert response.status_code == 400
        assert internal_file.read_text(encoding="utf-8") == "# Example"
    finally:
        if tokens._connection is not None:
            tokens._connection.close()
