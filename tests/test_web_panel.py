import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fastapi.testclient")

from backend.i18n import t  # noqa: E402
from frontend.clients.api_client import ApiError  # noqa: E402
from frontend.web import app as web_module  # noqa: E402
from frontend.web.messages import (  # noqa: E402
    WEB_ADVANCED_HEADLINE,
    WEB_INDEX_HEADLINE,
    WEB_SUCCESS_QUEUED,
)


def _fake_pdf_bytes() -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n%%EOF\n"


class _FakeApiClient:
    def __init__(self):
        self.submitted = []
        self.download_destination = None

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

    async def download_file(self, token, format, destination):
        self.download_destination = destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        if token == "partial":
            destination.write_text("partial", encoding="utf-8")
            raise ApiError(502, "Falha durante download")
        if token == "bad":
            raise ApiError(404, "Arquivo não encontrado")
        destination.write_text(f"{token}:{format}", encoding="utf-8")
        return destination


@pytest.fixture()
def web_client(monkeypatch, tmp_path):
    fake = _FakeApiClient()
    monkeypatch.setattr(web_module, "client", fake)
    monkeypatch.setattr(web_module.settings, "temp_dir", tmp_path)
    monkeypatch.setattr(web_module, "WEB_UPLOAD_DIR", tmp_path / "web_uploads")
    web_module.limiter.enabled = False
    with TestClient(web_module.app) as c:
        c.fake = fake
        yield c


def test_index_page(web_client):
    """The main panel page must render its localized headline text.

    The headline comes from the i18n catalog via WEB_INDEX_HEADLINE, so the test
    compares against the translated constant rather than a hardcoded language,
    keeping this assertion stable regardless of the active server locale.
    """
    resp = web_client.get("/")
    assert resp.status_code == 200
    assert t(WEB_INDEX_HEADLINE) in resp.text


def test_advanced_page(web_client):
    """The advanced panel page must render its localized headline text.

    Same reason as test_index_page: assert on the localized WEB_ADVANCED_HEADLINE
    constant so the check survives locale switches.
    """
    resp = web_client.get("/advanced")
    assert resp.status_code == 200
    assert t(WEB_ADVANCED_HEADLINE) in resp.text


def test_upload_submits_via_api(web_client):
    """Uploading a document queues it and the panel shows the success notice.

    The success notice is localized (WEB_SUCCESS_QUEUED), so the exact words vary
    by active locale; the test builds the expected text from the translated
    constant with the known position and e-mail, then confirms the API client
    received a correctly formed submission.
    """
    resp = web_client.post(
        "/process",
        files={"document_file": ("doc.pdf", _fake_pdf_bytes(), "application/pdf")},
        data={"email": "test@example.com"},
    )
    assert resp.status_code == 200
    # The fake API reports the job landed at queue position 1.
    expected_success = t(WEB_SUCCESS_QUEUED).format(position=1, email="test@example.com")
    assert expected_success in resp.text
    assert len(web_client.fake.submitted) == 1
    sub = web_client.fake.submitted[0]
    assert sub["filename"] == "doc.pdf"
    assert sub["mode"] == "normal"
    assert sub["email"] == "test@example.com"
    assert sub["source"] == "web"
    assert not sub["file_path"].exists()


def test_upload_rejects_oversized_file_before_api_submission(web_client, monkeypatch):
    monkeypatch.setattr(web_module.settings, "max_file_size_mb", 1)
    resp = web_client.post(
        "/process",
        files={
            "document_file": (
                "grande.pdf",
                b"x" * (1024 * 1024 + 1),
                "application/pdf",
            )
        },
        data={"email": "test@example.com"},
    )

    assert resp.status_code == 413
    assert "limite de 1 MB" in resp.text
    assert web_client.fake.submitted == []
    assert list(web_module.WEB_UPLOAD_DIR.iterdir()) == []


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
    assert 'href="/api/v1/download/tok/txt"' in resp.text
    assert 'href="/api/v1/download/tok/zip"' in resp.text
    assert "localhost" not in resp.text


def test_download_proxy_delegates_to_api(web_client):
    resp = web_client.get("/api/v1/download/tok/txt")
    assert resp.status_code == 200
    assert resp.text == "tok:txt"
    assert 'filename="doc.txt"' in resp.headers["content-disposition"]
    assert not web_client.fake.download_destination.exists()


def test_download_proxy_removes_partial_file_after_api_failure(web_client):
    resp = web_client.get("/api/v1/download/partial/txt")
    assert resp.status_code == 502
    assert not web_client.fake.download_destination.exists()


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
    respx.get("http://localhost:8000/api/v1/download/tok/txt").mock(
        return_value=httpx.Response(200, content=b"conteudo acessivel")
    )
    with respx.mock:
        with TestClient(web_module.app) as c:
            resp = c.get("/download/tok")
            download_resp = c.get("/api/v1/download/tok/txt")
    assert resp.status_code == 200
    assert 'href="/api/v1/download/tok/txt"' in resp.text
    assert "localhost" not in resp.text
    assert download_resp.status_code == 200
    assert download_resp.content == b"conteudo acessivel"
    assert 'filename="doc.txt"' in download_resp.headers["content-disposition"]
