import httpx
import pytest
import respx

from frontend.clients.api_client import ApiClient, ApiError

pytestmark = pytest.mark.asyncio

BASE = "https://api.test"


@respx.mock
async def test_submit_job(tmp_path):
    route = respx.post(f"{BASE}/api/v1/jobs").mock(
        return_value=httpx.Response(
            202, json={"task_id": "abcd1234", "position": 1, "message": "ok"}
        )
    )
    file_path = tmp_path / "doc.pdf"
    file_path.write_bytes(b"%PDF-1.4")

    client = ApiClient(base_url=BASE)
    result = await client.submit_job(file_path, "doc.pdf", source="test")

    assert result["task_id"] == "abcd1234"
    assert route.called
    request = route.calls[0].request
    assert b"doc.pdf" in request.read()
    assert b"source" in request.content


@respx.mock
async def test_get_job_status():
    respx.get(f"{BASE}/api/v1/jobs/abc123").mock(
        return_value=httpx.Response(
            200,
            json={
                "task_id": "abc123",
                "arquivo": "doc.pdf",
                "status": "queued",
                "progresso": 0.0,
                "etapa_atual": "Aguardando",
                "erros": [],
                "download_url": None,
            },
        )
    )
    client = ApiClient(base_url=BASE)
    status = await client.get_job_status("abc123")
    assert status["status"] == "queued"


@respx.mock
async def test_cancel_job():
    respx.post(f"{BASE}/api/v1/jobs/abc123/cancel").mock(
        return_value=httpx.Response(200, json={"task_id": "abc123", "status": "cancelled"})
    )
    client = ApiClient(base_url=BASE)
    result = await client.cancel_job("abc123")
    assert result["status"] == "cancelled"


@respx.mock
async def test_download_file(tmp_path):
    respx.get(f"{BASE}/api/v1/download/tok/pdf").mock(
        return_value=httpx.Response(200, content=b"%PDF-1.4-fake")
    )
    client = ApiClient(base_url=BASE)
    dest = tmp_path / "out" / "doc.pdf"
    path = await client.download_file("tok", "pdf", dest)
    assert path.read_bytes() == b"%PDF-1.4-fake"


@respx.mock
async def test_error_raises_api_error():
    respx.get(f"{BASE}/api/v1/jobs/unknown").mock(
        return_value=httpx.Response(404, json={"detail": "Tarefa não encontrada"})
    )
    client = ApiClient(base_url=BASE)
    with pytest.raises(ApiError) as exc_info:
        await client.get_job_status("unknown")
    assert exc_info.value.status_code == 404
    assert "não encontrada" in exc_info.value.detail


@respx.mock
async def test_history():
    respx.get(f"{BASE}/api/v1/history?limit=5").mock(return_value=httpx.Response(200, json=[]))
    client = ApiClient(base_url=BASE)
    assert await client.history(limit=5) == []
