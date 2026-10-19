import json

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


@respx.mock
async def test_job_token_retention_is_bounded_and_terminal_jobs_remain_accessible(tmp_path):
    client = ApiClient(base_url=BASE)
    client._job_tokens.update((f"old-{i}", "token") for i in range(256))
    respx.post(f"{BASE}/api/v1/jobs").mock(return_value=httpx.Response(
        202, json={"task_id": "new", "job_token": "new-token"}))
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"%PDF")
    await client.submit_job(path, "doc.pdf")
    assert len(client._job_tokens) == 256
    assert "old-0" not in client._job_tokens
    route = respx.get(f"{BASE}/api/v1/jobs/new").mock(return_value=httpx.Response(
        200, json={"task_id": "new", "status": "done"}))
    await client.get_job_status("new")
    await client.get_job_status("new")
    assert all(call.request.headers["X-Job-Token"] == "new-token" for call in route.calls)


@pytest.mark.parametrize("payload", [["upstream unavailable"], "upstream unavailable", None, 42])
@respx.mock
async def test_non_object_http_error_preserves_api_error_status(payload):
    respx.get(f"{BASE}/api/v1/jobs/example").mock(
        return_value=httpx.Response(502, content=json.dumps(payload))
    )
    with pytest.raises(ApiError) as raised:
        await ApiClient(base_url=BASE).get_job_status("example")
    assert raised.value.status_code == 502


@pytest.mark.parametrize("content", [b"[]", b"null", b"not json"])
@respx.mock
async def test_invalid_successful_job_status_is_reported_as_bad_gateway(content):
    respx.get(f"{BASE}/api/v1/jobs/example").mock(
        return_value=httpx.Response(200, content=content)
    )
    with pytest.raises(ApiError) as raised:
        await ApiClient(base_url=BASE).get_job_status("example")
    assert raised.value.status_code == 502


@pytest.mark.parametrize("receipt", [
    [], {"job_token": "token"}, {"task_id": None}, {"task_id": "invalid/path"},
    {"task_id": "example", "job_token": ["invalid"]},
])
@respx.mock
async def test_invalid_submission_receipt_does_not_enter_token_cache(tmp_path, receipt):
    respx.post(f"{BASE}/api/v1/jobs").mock(return_value=httpx.Response(202, json=receipt))
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"%PDF")
    client = ApiClient(base_url=BASE)
    with pytest.raises(ApiError) as raised:
        await client.submit_job(source, "doc.pdf")
    assert raised.value.status_code == 502
    assert not client._job_tokens
