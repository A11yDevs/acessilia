import asyncio
import zipfile
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


def test_queued_position_is_recalculated(client, monkeypatch):
    from backend.api import worker
    from backend.services import queue_service

    queue = queue_service.UnifiedQueue()
    monkeypatch.setattr(queue_service, "unified_queue", queue)
    monkeypatch.setattr(worker, "queued_jobs", {})

    async def process():
        return None

    first = queue_service.QueueItem(
        file_path=Path("first.pdf"),
        filename="first.pdf",
        source="pytest",
        task_id="queuedfirst",
        callback=process,
    )
    second = queue_service.QueueItem(
        file_path=Path("second.pdf"),
        filename="second.pdf",
        source="pytest",
        task_id="queuedsecond",
        callback=process,
    )

    asyncio.run(queue.enqueue(first))
    asyncio.run(queue.enqueue(second))
    worker.register_queued_job("queuedfirst", "first.pdf", 1, "pytest")
    worker.register_queued_job("queuedsecond", "second.pdf", 2, "pytest")

    assert queue.cancel("queuedfirst")

    status = client.get("/api/v1/jobs/queuedsecond")
    assert status.status_code == 200
    assert status.json()["etapa_atual"] == "Aguardando na fila (Posicao: 1)"


def test_status_unknown(client):
    resp = client.get("/api/v1/jobs/unknown1")
    assert resp.status_code == 404


def test_cancel_unknown(client):
    resp = client.post("/api/v1/jobs/unknown1/cancel")
    assert resp.status_code == 404


@pytest.mark.parametrize("status", ["processing", "done", "error", "cancelled"])
def test_cancel_respects_task_state(client, monkeypatch, status):
    from backend.agents.state_manager import StateManager
    from backend.api import worker

    manager = StateManager()
    monkeypatch.setattr(worker, "state_manager", manager)
    task_id = manager.criar_tarefa(Path("doc.pdf"))
    if status == "cancelled":
        assert manager.cancelar(task_id) is True
    else:
        manager.atualizar(task_id, status=status)
    before = dict(manager.obter(task_id))

    response = client.post(f"/api/v1/jobs/{task_id}/cancel")
    actual = client.get(f"/api/v1/jobs/{task_id}").json()

    if status == "processing":
        assert response.status_code == 200
        assert response.json()["status"] == actual["status"] == "cancelled"
        assert manager.foi_cancelada(task_id)
    else:
        assert response.status_code == 409
        assert status in response.json()["detail"]
        assert actual["status"] == status
        assert manager.obter(task_id) == before
        assert manager.foi_cancelada(task_id) == (status == "cancelled")


@pytest.mark.parametrize("in_queue", [True, False])
def test_cancel_queued_job_requires_queue_removal(client, monkeypatch, in_queue):
    from backend.agents.state_manager import StateManager
    from backend.api import worker
    from backend.services import queue_service

    queue = queue_service.UnifiedQueue()
    monkeypatch.setattr(queue_service, "unified_queue", queue)
    monkeypatch.setattr(worker, "state_manager", StateManager())
    monkeypatch.setattr(worker, "queued_jobs", {})
    task_id = "cancelqueued26"
    worker.register_queued_job(task_id, "doc.pdf", 1, "pytest")
    if in_queue:
        queue._queue.append(queue_service.QueueItem(
            file_path=Path("doc.pdf"), filename="doc.pdf", source="pytest",
            callback=None, task_id=task_id,
        ))
    before = worker.get_job_status(task_id)

    response = client.post(f"/api/v1/jobs/{task_id}/cancel")
    actual = client.get(f"/api/v1/jobs/{task_id}").json()

    if in_queue:
        assert response.status_code == 200
        assert response.json()["status"] == actual["status"] == "cancelled"
        assert queue.qsize() == 0
        cancelled = worker.get_job_status(task_id)
        assert client.post(f"/api/v1/jobs/{task_id}/cancel").status_code == 409
        assert worker.get_job_status(task_id) == cancelled
    else:
        assert response.status_code == 409
        assert actual["status"] == "queued"
        assert worker.get_job_status(task_id) == before


def test_download_info_invalid_token(client):
    resp = client.get("/api/v1/download/not-a-token")
    assert resp.status_code == 404


def test_download_file_invalid_format(client):
    resp = client.get("/api/v1/download/not-a-token/txt")
    assert resp.status_code == 404


def test_download_url_uses_public_api_prefix(monkeypatch):
    from backend.api.worker import build_download_url

    monkeypatch.setattr(settings, "web_base_url", "https://acessilia.example/")

    assert (
        build_download_url("tok123")
        == "https://acessilia.example/download/tok123"
    )


def test_download_full_flow(client, api_paths):
    import backend.services.download_token_service as dts

    out_dir = api_paths / "output" / "task1"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "doc.txt").write_text("conteudo de teste", encoding="utf-8")
    (out_dir / "doc_acessivel.zip").write_bytes(b"zip")

    token = asyncio.run(dts.criar_token(out_dir, "doc"))

    # Simula reinicio da aplicacao: o token deve sobreviver em history.db.
    dts._connection.close()
    dts._connection = None

    info = client.get(f"/api/v1/download/{token}")
    assert info.status_code == 200
    assert info.json()["stem"] == "doc"
    formats = {item["ext"] for item in info.json()["formats"]}
    assert formats == {"txt", "zip"}

    resp = client.get(f"/api/v1/download/{token}/txt")
    assert resp.status_code == 200
    assert resp.text == "conteudo de teste"

    resp = client.get(f"/api/v1/download/{token}/pdf")
    assert resp.status_code == 404


def test_download_info_keeps_dotted_base_name(client, api_paths):
    import backend.services.download_token_service as dts

    out_dir = api_paths / "output" / "task-dotted"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "relatorio.v2.txt").write_text("conteudo", encoding="utf-8")
    (out_dir / "relatorio.v2_acessivel.zip").write_bytes(b"zip")

    token = asyncio.run(dts.criar_token(out_dir, "relatorio.v2"))

    info = client.get(f"/api/v1/download/{token}")
    assert info.status_code == 200
    assert info.json()["stem"] == "relatorio.v2"
    formats = {item["ext"] for item in info.json()["formats"]}
    assert formats == {"txt", "zip"}


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


@pytest.mark.asyncio
async def test_job_executor_marks_history_error_when_export_fails(
    api_paths, monkeypatch
):
    import backend.services.history_service as hs
    from backend.agents.state_manager import state_manager
    from backend.api.worker import ApiJob, JobExecutor
    from backend.services.history_service import registrar_conversao

    task_id = "bug0001"
    input_path = api_paths / "input.pdf"
    input_path.write_bytes(_fake_pdf_bytes())
    state_manager._tasks.clear()
    state_manager._cancel_events.clear()

    async def fake_process(*args, **kwargs):
        state_manager.criar_tarefa(input_path, task_id=task_id)
        return {"title": "Documento", "sections": []}

    def fail_export_txt(*args, **kwargs):
        output_path = args[1]
        output_path.write_text("parcial", encoding="utf-8")
        raise OSError("disk full")

    monkeypatch.setattr("backend.service.process", fake_process)
    monkeypatch.setattr("backend.api.worker.export_txt", fail_export_txt)

    await registrar_conversao(
        task_id=task_id,
        arquivo=input_path.name,
        extensao=input_path.suffix,
        tamanho_bytes=input_path.stat().st_size,
        modo="normal",
    )

    await JobExecutor().run(
        ApiJob(
            task_id=task_id,
            file_path=input_path,
            filename=input_path.name,
            output_dir=api_paths / "output" / task_id,
        )
    )

    task = state_manager.obter(task_id)
    assert task is not None
    assert task["status"] == "error"
    assert not (api_paths / "output" / task_id).exists()

    rows = await hs.listar_historico(10)
    [row] = [row for row in rows if row["task_id"] == task_id]
    assert row["status"] == "error"
    assert "disk full" in row["erro"]


@pytest.mark.asyncio
async def test_job_executor_stops_exports_after_cancellation(api_paths, monkeypatch):
    from backend.agents.state_manager import state_manager
    from backend.api.worker import ApiJob, JobExecutor
    from backend.services import history_service as hs

    task_id = "bug0003"
    input_path = api_paths / "cancel.pdf"
    output_dir = api_paths / "output" / task_id
    input_path.write_bytes(_fake_pdf_bytes())
    state_manager._tasks.clear()
    state_manager._cancel_events.clear()

    async def fake_process(*args, **kwargs):
        state_manager.criar_tarefa(input_path, task_id=task_id)
        await hs.registrar_conversao(
            task_id=task_id,
            arquivo=input_path.name,
            extensao=input_path.suffix,
            tamanho_bytes=input_path.stat().st_size,
            modo="normal",
        )
        return {"title": "Documento", "sections": []}

    def export_txt_and_cancel(canonical, destination, filename):
        destination.write_text("conteudo", encoding="utf-8")
        state_manager.cancelar(task_id)

    async def fail_if_token_created(*args, **kwargs):
        raise AssertionError("token should not be created after cancellation")

    monkeypatch.setattr("backend.service.process", fake_process)
    monkeypatch.setattr("backend.api.worker.export_txt", export_txt_and_cancel)
    monkeypatch.setattr("backend.api.worker.criar_token", fail_if_token_created)

    executor = JobExecutor()

    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(executor, "_run_in_executor", run_inline)
    await executor.run(
        ApiJob(
            task_id=task_id,
            file_path=input_path,
            filename=input_path.name,
            output_dir=output_dir,
        )
    )

    task = state_manager.obter(task_id)
    assert task is not None
    assert task["status"] == "cancelled"
    assert not (output_dir / "cancel_acessivel.zip").exists()
    rows = await hs.listar_historico(10)
    [row] = [row for row in rows if row["task_id"] == task_id]
    assert row["status"] == "cancelled"
    assert row["concluido_em"] is not None


@pytest.mark.asyncio
async def test_job_executor_keeps_original_filename_in_status(api_paths, monkeypatch):
    from backend.agents.state_manager import state_manager
    from backend.api.worker import ApiJob, JobExecutor

    task_id = "bug0034"
    input_path = api_paths / "8ab9f21d.pdf"
    output_dir = api_paths / "output" / task_id
    input_path.write_bytes(_fake_pdf_bytes())
    state_manager._tasks.clear()
    state_manager._cancel_events.clear()

    async def fake_process(*args, **kwargs):
        state_manager.criar_tarefa(input_path, task_id=task_id)
        return {"title": "Documento", "sections": []}

    def write_file(_canonical, destination, _filename=None, **_kwargs):
        destination.write_text("conteudo", encoding="utf-8")

    async def write_mp3(_text, destination, **_kwargs):
        destination.write_bytes(b"audio")

    async def fake_token(*args, **kwargs):
        return "tok"

    async def ignore_history(*args, **kwargs):
        return None

    monkeypatch.setattr("backend.service.process", fake_process)
    monkeypatch.setattr("backend.api.worker.export_txt", write_file)
    monkeypatch.setattr("backend.api.worker.export_docx", write_file)
    monkeypatch.setattr("backend.api.worker.export_pdf", write_file)
    monkeypatch.setattr("backend.api.worker.export_pdf_ua", write_file)
    monkeypatch.setattr("backend.api.worker.export_accessible_document", write_file)
    monkeypatch.setattr("backend.api.worker.export_mp3", write_mp3)
    monkeypatch.setattr("backend.api.worker.criar_token", fake_token)
    monkeypatch.setattr("backend.api.worker.finalizar_conversao", ignore_history)

    executor = JobExecutor()

    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(executor, "_run_in_executor", run_inline)
    await executor.run(
        ApiJob(
            task_id=task_id,
            file_path=input_path,
            filename="relatorio-final.pdf",
            output_dir=output_dir,
        )
    )

    task = state_manager.obter(task_id)
    assert task is not None
    assert task["arquivo"] == "relatorio-final.pdf"


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_format", [None, "MP3", "PDF/UA"])
async def test_job_executor_reports_optional_export_failure(
    api_paths, monkeypatch, failed_format
):
    from backend.agents.state_manager import state_manager
    from backend.api.worker import ApiJob, JobExecutor

    task_id = "bug0011"
    input_path = api_paths / "audio.pdf"
    output_dir = api_paths / "output" / task_id
    input_path.write_bytes(_fake_pdf_bytes())
    state_manager._tasks.clear()
    state_manager._cancel_events.clear()

    async def fake_process(*args, **kwargs):
        state_manager.criar_tarefa(input_path, task_id=task_id)
        return {"title": "Documento", "sections": []}

    def write_file(_canonical, destination, _filename=None, **_kwargs):
        destination.write_text("conteudo", encoding="utf-8")

    async def fail_mp3(*args, **kwargs):
        raise RuntimeError("tts offline")

    def fail_pdf_ua(_canonical, destination, _filename):
        destination.write_bytes(b"partial pdf")
        raise FileNotFoundError("pandoc indisponivel")

    async def write_mp3(_text, destination, **_kwargs):
        destination.write_bytes(b"audio")

    registered_formats = []

    async def fake_token(*args, formats=None, **kwargs):
        registered_formats.extend(formats or [])
        return "tok"

    sent_emails = []

    async def fake_result_email(*args, **kwargs):
        sent_emails.append(kwargs)
        return True

    async def ignore_history(*args, **kwargs):
        return None

    monkeypatch.setattr("backend.service.process", fake_process)
    monkeypatch.setattr("backend.api.worker.export_txt", write_file)
    monkeypatch.setattr("backend.api.worker.export_docx", write_file)
    monkeypatch.setattr("backend.api.worker.export_pdf", write_file)
    monkeypatch.setattr("backend.api.worker.export_pdf_ua", write_file)
    monkeypatch.setattr("backend.api.worker.export_accessible_document", write_file)
    if failed_format == "PDF/UA":
        monkeypatch.setattr("backend.api.worker.export_pdf_ua", fail_pdf_ua)
    monkeypatch.setattr(
        "backend.api.worker.export_mp3",
        fail_mp3 if failed_format == "MP3" else write_mp3,
    )
    monkeypatch.setattr("backend.api.worker.criar_token", fake_token)
    monkeypatch.setattr("backend.api.worker.send_confirmation_email", ignore_history)
    monkeypatch.setattr("backend.api.worker.send_result_email", fake_result_email)
    monkeypatch.setattr("backend.api.worker.finalizar_conversao", ignore_history)

    executor = JobExecutor()

    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(executor, "_run_in_executor", run_inline)
    await executor.run(
        ApiJob(
            task_id=task_id,
            file_path=input_path,
            filename=input_path.name,
            email="test@example.invalid",
            output_dir=output_dir,
        )
    )

    from backend.api.worker import get_job_status

    task = get_job_status(task_id)
    assert task is not None
    assert task["status"] == "done"
    assert task["download_url"]
    expected_errors = {
        None: [],
        "MP3": ["Falha ao gerar MP3: tts offline"],
        "PDF/UA": ["Falha ao gerar PDF/UA: pandoc indisponivel"],
    }
    assert task["erros"] == expected_errors[failed_format]

    if failed_format == "MP3":
        assert not (output_dir / "audio.mp3").exists()
    if failed_format == "PDF/UA":
        assert not (output_dir / "audio.pdf_ua.pdf").exists()

    expected_formats = {"txt", "docx", "pdf", "html", "zip"}
    if failed_format != "MP3":
        expected_formats.add("mp3")
    if failed_format != "PDF/UA":
        expected_formats.add("pdf_ua")
    assert set(registered_formats) == expected_formats

    with zipfile.ZipFile(output_dir / "audio_acessivel.zip") as archive:
        expected_files = {"audio.txt", "audio.docx", "audio.pdf", "audio.html"}
        if failed_format != "MP3":
            expected_files.add("audio.mp3")
        if failed_format != "PDF/UA":
            expected_files.add("audio.pdf_ua.pdf")
        assert set(archive.namelist()) == expected_files

    assert len(sent_emails) == 1
    assert sent_emails[0]["download_url"].endswith("/download/tok")
    assert sent_emails[0]["completed_formats"] == registered_formats
    assert sent_emails[0]["warnings"] == expected_errors[failed_format]


@pytest.mark.asyncio
async def test_job_executor_records_early_process_failure(api_paths, monkeypatch):
    from backend.agents.state_manager import state_manager
    from backend.api import worker as worker_module
    from backend.api.worker import ApiJob, JobExecutor
    from backend.services import history_service as hs

    task_id = "bug0012"
    input_path = api_paths / "early.pdf"
    input_path.write_bytes(_fake_pdf_bytes())
    state_manager._tasks.clear()
    state_manager._cancel_events.clear()
    worker_module.queued_jobs.clear()
    worker_module.register_queued_job(task_id, input_path.name, 1, "pytest")

    async def fail_before_state(*args, **kwargs):
        raise PermissionError("cache inacessivel")

    monkeypatch.setattr("backend.service.process", fail_before_state)

    await JobExecutor().run(
        ApiJob(
            task_id=task_id,
            file_path=input_path,
            filename=input_path.name,
        )
    )

    task = state_manager.obter(task_id)
    assert task is not None
    assert task["status"] == "error"
    assert task_id not in worker_module.queued_jobs
    assert not input_path.exists()
    rows = await hs.listar_historico(10)
    [row] = [row for row in rows if row["task_id"] == task_id]
    assert row["status"] == "error"
    assert row["erro"] == "cache inacessivel"
    assert row["concluido_em"] is not None
