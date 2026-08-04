import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.limiter import limiter
from backend.config.settings import settings

pytest.importorskip("fastapi.testclient")

from backend.api.app import app  # noqa: E402


@pytest.fixture(scope="session")
def api_paths(tmp_path_factory):
    return tmp_path_factory.mktemp("api_paths")


@pytest.fixture(autouse=True)
def _isolate_paths(api_paths, monkeypatch):
    import backend.services.download_token_service as dts
    import backend.services.history_service as hs

    temp_dir = api_paths / "temp"
    data_dir = api_paths / "data"
    temp_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(settings, "temp_dir", temp_dir)
    monkeypatch.setattr(settings, "data_dir", data_dir)
    monkeypatch.setattr(settings, "logs_dir", api_paths / "logs")

    dts._connection = None
    hs._connection = None
    limiter.enabled = False


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


class _FakeExecutor:
    def __init__(self):
        self.calls = []

    async def run(self, job):
        self.calls.append(job)


def _fake_pdf_bytes() -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n%%EOF\n"


def test_health(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["model_client"] == settings.ai_client
    assert "queue_size" in body


def test_stats_empty(client):
    resp = client.get("/api/v1/stats")
    assert resp.status_code == 200
    assert resp.json() == {
        "total": 0,
        "sucesso": 0,
        "erros": 0,
        "tempo_medio_segundos": 0.0,
    }


def test_history_empty(client):
    resp = client.get("/api/v1/history")
    assert resp.status_code == 200
    assert resp.json() == []


def test_upload_invalid_extension(client):
    resp = client.post(
        "/api/v1/jobs",
        files={"document_file": ("script.exe", b"MZ...", "application/octet-stream")},
        data={"email": "test@example.com"},
    )
    assert resp.status_code == 400
    assert "não suportado" in resp.json()["detail"]


def test_upload_oversized_prompt(client):
    resp = client.post(
        "/api/v1/jobs",
        files={"document_file": ("doc.pdf", _fake_pdf_bytes(), "application/pdf")},
        data={"custom_prompt": "x" * 6001},
    )
    assert resp.status_code == 400
    assert "6000" in resp.json()["detail"]


def test_upload_oversized_file(client, monkeypatch):
    monkeypatch.setattr(settings, "max_file_size_mb", 0.000001)
    resp = client.post(
        "/api/v1/jobs",
        files={"document_file": ("doc.pdf", b"a" * 1024, "application/pdf")},
    )
    assert resp.status_code == 413
    assert "muito grande" in resp.json()["detail"]


def test_upload_ok_and_status_queued(client, monkeypatch):
    fake = _FakeExecutor()
    monkeypatch.setattr("backend.api.routes.jobs.job_executor", fake)

    resp = client.post(
        "/api/v1/jobs",
        files={"document_file": ("doc.pdf", _fake_pdf_bytes(), "application/pdf")},
        data={
            "mode": "normal",
            "custom_prompt": "",
            "thinking_mode": "false",
            "email": "test@example.com",
            "source": "pytest",
        },
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["position"] == 1
    task_id = body["task_id"]
    assert len(task_id) == 8

    status = client.get(f"/api/v1/jobs/{task_id}")
    assert status.status_code == 200
    assert status.json()["status"] == "queued"
    assert status.json()["arquivo"] == "doc.pdf"


def test_status_unknown(client):
    resp = client.get("/api/v1/jobs/unknown1")
    assert resp.status_code == 404


def test_cancel_unknown(client):
    resp = client.post("/api/v1/jobs/unknown1/cancel")
    assert resp.status_code == 404


def test_download_info_invalid_token(client):
    resp = client.get("/api/v1/download/not-a-token")
    assert resp.status_code == 404


def test_download_file_invalid_format(client):
    resp = client.get("/api/v1/download/not-a-token/txt")
    assert resp.status_code == 404


def test_download_full_flow(client, api_paths):
    from backend.services.download_token_service import criar_token

    out_dir = api_paths / "output" / "task1"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "doc.txt").write_text("conteudo de teste", encoding="utf-8")

    token = asyncio.run(criar_token(out_dir, "doc"))

    info = client.get(f"/api/v1/download/{token}")
    assert info.status_code == 200
    assert info.json()["stem"] == "doc"
    assert len(info.json()["formats"]) == 1
    assert info.json()["formats"][0]["ext"] == "txt"

    resp = client.get(f"/api/v1/download/{token}/txt")
    assert resp.status_code == 200
    assert resp.text == "conteudo de teste"

    resp = client.get(f"/api/v1/download/{token}/pdf")
    assert resp.status_code == 404


def test_job_executor_records_job(client, monkeypatch):
    fake = _FakeExecutor()
    monkeypatch.setattr("backend.api.routes.jobs.job_executor", fake)

    client.post(
        "/api/v1/jobs",
        files={"document_file": ("doc.pdf", _fake_pdf_bytes(), "application/pdf")},
        data={},
    )

    for _ in range(20):
        if fake.calls:
            break
        import time

        time.sleep(0.1)

    assert len(fake.calls) >= 1
    assert fake.calls[0].filename == "doc.pdf"
