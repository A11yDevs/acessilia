import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fastapi.testclient")

from frontend.clients.api_client import ApiError  # noqa: E402
from frontend.web import app as web_module  # noqa: E402


def _fake_pdf_bytes() -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n%%EOF\n"


class _FakeApiClient:
    def __init__(self):
        self.submitted = []

    async def submit_job(
        self,
        file_path,
        filename,
        mode="normal",
        custom_prompt=None,
        thinking_mode=False,
        email=None,
        source="api",
    ):
        self.submitted.append(
            {
                "file_path": file_path,
                "filename": filename,
                "mode": mode,
                "custom_prompt": custom_prompt,
                "thinking_mode": thinking_mode,
                "email": email,
                "source": source,
            }
        )
        return {"task_id": "web12345", "position": 1, "message": "ok"}

    async def get_download_info(self, token):
        if token == "bad":
            raise ApiError(404, "Link inválido ou expirado")
        return {
            "filename": "doc.pdf",
            "stem": "doc",
            "criado_em": None,
            "formats": [
                {"ext": "txt", "label": "texto", "size": "1 KB", "url": "/download/tok/txt"},
                {"ext": "zip", "label": "completo", "size": "2 KB", "url": "/download/tok/zip"},
            ],
        }


@pytest.fixture()
def web_client(monkeypatch, tmp_path):
    fake = _FakeApiClient()
    monkeypatch.setattr(web_module, "client", fake)
    monkeypatch.setattr(web_module, "WEB_UPLOAD_DIR", tmp_path / "web_uploads")
    web_module.limiter.enabled = False
    with TestClient(web_module.app) as c:
        c.fake = fake
        yield c


def test_index_page(web_client):
    resp = web_client.get("/")
    assert resp.status_code == 200
    assert "Bot Acess" in resp.text


def test_advanced_page(web_client):
    resp = web_client.get("/advanced")
    assert resp.status_code == 200
    assert "Modo Avançado" in resp.text


def test_upload_submits_via_api(web_client):
    resp = web_client.post(
        "/process",
        files={"document_file": ("doc.pdf", _fake_pdf_bytes(), "application/pdf")},
        data={"email": "test@example.com"},
    )
    assert resp.status_code == 200
    assert "Posição" in resp.text
    assert len(web_client.fake.submitted) == 1
    sub = web_client.fake.submitted[0]
    assert sub["filename"] == "doc.pdf"
    assert sub["mode"] == "normal"
    assert sub["email"] == "test@example.com"
    assert sub["source"] == "web"
    assert not sub["file_path"].exists()


def test_advanced_upload_sends_prompt_and_thinking(web_client):
    resp = web_client.post(
        "/advanced/process",
        files={"document_file": ("doc.pdf", _fake_pdf_bytes(), "application/pdf")},
        data={
            "email": "test@example.com",
            "custom_prompt": "Explique em detalhes",
            "thinking_mode": "true",
        },
    )
    assert resp.status_code == 200
    assert len(web_client.fake.submitted) == 1
    sub = web_client.fake.submitted[0]
    assert sub["custom_prompt"] == "Explique em detalhes"
    assert sub["thinking_mode"] is True


def test_advanced_upload_oversized_prompt(web_client):
    resp = web_client.post(
        "/advanced/process",
        files={"document_file": ("doc.pdf", _fake_pdf_bytes(), "application/pdf")},
        data={"email": "test@example.com", "custom_prompt": "x" * 6001},
    )
    assert resp.status_code == 200
    assert "6000" in resp.text
    assert web_client.fake.submitted == []


def test_download_page_delegates_to_api(web_client):
    resp = web_client.get("/download/tok")
    assert resp.status_code == 200
    assert "doc.pdf" in resp.text
    assert "http://localhost:8000/api/v1/download/tok/txt" in resp.text
    assert "http://localhost:8000/api/v1/download/tok/zip" in resp.text


def test_download_page_not_found(web_client):
    resp = web_client.get("/download/bad")
    assert resp.status_code == 404


def test_download_page_uses_real_client(monkeypatch):
    import httpx
    import respx

    from frontend.clients.api_client import ApiClient

    web_module.limiter.enabled = False
    monkeypatch.setattr(
        web_module,
        "client",
        ApiClient(base_url="http://localhost:8000"),
    )

    respx.get("http://localhost:8000/api/v1/download/tok").mock(
        return_value=httpx.Response(
            200,
            json={
                "filename": "doc.pdf",
                "stem": "doc",
                "criado_em": None,
                "formats": [
                    {
                        "ext": "txt",
                        "label": "texto",
                        "size": "1 KB",
                        "url": "/download/tok/txt",
                    }
                ],
            },
        )
    )
    with respx.mock:
        with TestClient(web_module.app) as c:
            resp = c.get("/download/tok")
    assert resp.status_code == 200
    assert "http://localhost:8000/api/v1/download/tok/txt" in resp.text
