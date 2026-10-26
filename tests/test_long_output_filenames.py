"""Long upload names must survive export, ZIP packaging and download."""

import io
import zipfile
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.api import worker
from backend.api.app import create_app
from backend.api.limiter import limiter
from backend.api.routes import jobs
from backend.config.settings import settings
from backend.services import download_token_service, queue_service


@pytest.mark.asyncio
@pytest.mark.parametrize("stem", ["report", "a" * 250, "α" * 250, "中" * 250], ids=["short", "long-ascii", "long-greek", "long-cjk"])
async def test_long_filename_can_be_exported_and_downloaded(tmp_path, monkeypatch, stem):
    from backend import service
    from backend.agents.state_manager import StateManager

    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "temp_dir", tmp_path / "temp")
    monkeypatch.setattr(settings, "toolbox_docx_enabled", True)
    monkeypatch.setattr(settings, "toolbox_pdf_ua_enabled", True)
    monkeypatch.setattr(limiter, "enabled", False)
    monkeypatch.setattr(worker, "queued_jobs", {})
    monkeypatch.setattr(worker, "state_manager", StateManager())
    monkeypatch.setattr(download_token_service, "_connection", None)
    queue = queue_service.UnifiedQueue()
    monkeypatch.setattr(queue_service, "unified_queue", queue)
    monkeypatch.setattr(jobs, "unified_queue", queue)
    executor = worker.JobExecutor()
    monkeypatch.setattr(jobs, "job_executor", executor)
    monkeypatch.setattr(service, "process", AsyncMock(return_value={"title": "Audit"}))
    monkeypatch.setattr(worker, "registrar_conversao", AsyncMock())
    monkeypatch.setattr(worker, "finalizar_conversao", AsyncMock())

    def export(document, path, *args, **kwargs):
        path.write_bytes(b"audit output")
        return path

    async def audio(text, path, **kwargs):
        return export(None, path)

    for name in ("export_txt", "export_accessible_document", "export_drbench_md", "export_docx", "export_pdf_ua"):
        monkeypatch.setattr(worker, name, export)
    monkeypatch.setattr(worker, "export_mp3", audio)
    monkeypatch.setattr(worker, "audit_pdf_ua", AsyncMock(return_value={
        "compliant": True, "profile": "ua1", "failures": [],
    }))
    filename = stem + ".pdf"
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(create_app()), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/jobs", files={"document_file": (filename, b"%PDF", "application/pdf")}
            )
            assert response.status_code == 202
            receipt = response.json()
            item = queue._queue.popleft()
            await item.callback(**item.callback_args)
            status = await client.get(
                f"/api/v1/jobs/{receipt['task_id']}",
                headers={"X-Job-Token": receipt["job_token"]},
            )
            assert status.json()["status"] == "done", status.json()
            assert status.json()["arquivo"] == filename
            token = status.json()["download_url"].rsplit("/", 1)[-1]
            info = await client.get(f"/api/v1/download/{token}")
            assert info.status_code == 200
            formats = {entry["ext"]: entry for entry in info.json()["formats"]}
            assert set(formats) == {"txt", "html", "docx", "pdf_ua", "mp3", "zip"}
            for entry in formats.values():
                result = await client.get("/api/v1" + entry["url"])
                assert result.status_code == 200
                assert result.content
                if entry["ext"] == "zip":
                    with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
                        assert archive.testzip() is None
                        assert len(archive.namelist()) == 6
                        assert all(len(name.encode("utf-8")) <= 255 for name in archive.namelist())
    finally:
        executor._executor.shutdown(wait=True)
        if download_token_service._connection is not None:
            download_token_service._connection.close()


def test_output_stem_preserves_short_names_and_distinguishes_long_names():
    from backend.tools.filenames import MAX_OUTPUT_STEM_BYTES, output_stem

    assert output_stem("report-final.pdf") == "report-final"
    assert output_stem("report-α.pdf") == "report-α"
    first = output_stem("α" * 250 + "a.pdf")
    second = output_stem("α" * 250 + "b.pdf")
    assert first != second
    assert first == output_stem("α" * 250 + "a.pdf")
    assert len(first.encode("utf-8")) <= MAX_OUTPUT_STEM_BYTES
    assert len(second.encode("utf-8")) <= MAX_OUTPUT_STEM_BYTES


@pytest.mark.parametrize("stem", [" " * 250, "." * 250, " ." * 125])
def test_empty_shortened_prefix_uses_document(stem):
    from backend.tools.filenames import MAX_OUTPUT_STEM_BYTES, output_stem

    result = output_stem(stem + ".pdf")
    assert result.startswith("document-")
    assert len(result.encode("utf-8")) <= MAX_OUTPUT_STEM_BYTES
