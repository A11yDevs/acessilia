import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fastapi.testclient")

from backend.i18n import t  # noqa: E402
from backend.services.download_token_service import TOKEN_EXPIRY_DAYS  # noqa: E402
from frontend.clients.api_client import ApiError  # noqa: E402
from frontend.web import app as web_module  # noqa: E402
from frontend.web.messages import (  # noqa: E402
    WEB_ADVANCED_HEADLINE,
    WEB_ERROR_INTERNAL,
    WEB_INDEX_HEADLINE,
    WEB_JOB_CLOSE_INFO,
    WEB_JOB_PENDING,
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
        return {"task_id": "web12345", "job_token": "private-web-token", "position": 1, "message": "ok"}

    async def get_job_status(self, task_id, job_token=None):
        if task_id != "web12345" or job_token != "private-web-token":
            raise ApiError(404, "Job not found")
        return {"task_id": task_id, "arquivo": "doc.pdf", "status": "queued", "etapa_atual": "Queued", "erros": []}

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
    """Uploading redirects to a private, refreshable job receipt."""
    resp = web_client.post(
        "/process",
        files={"document_file": ("doc.pdf", _fake_pdf_bytes(), "application/pdf")},
        data={"email": "test@example.com"},
    )
    assert resp.status_code == 200
    assert resp.url.path == "/jobs/web12345"
    assert t(WEB_JOB_CLOSE_INFO).format(days=TOKEN_EXPIRY_DAYS) in resp.text
    assert t(WEB_JOB_PENDING) not in resp.text
    assert "private-web-token" not in resp.text
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


def test_advanced_upload_rejects_unsupported_options(web_client):
    resp = web_client.post(
        "/advanced/process",
        files={"document_file": ("doc.pdf", _fake_pdf_bytes(), "application/pdf")},
        data={
            "email": "test@example.com",
            "custom_prompt": "Explique em detalhes",
            "thinking_mode": "true",
        },
    )
    assert resp.status_code == 422
    assert 'action="/advanced/process"' in resp.text
    assert web_client.fake.submitted == []


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


def test_download_proxy_rejects_internal_drbench_markdown(web_client):
    resp = web_client.get("/api/v1/download/tok/drbench_md")
    assert resp.status_code == 400
    assert web_client.fake.download_destination is None


def test_download_proxy_removes_partial_file_after_api_failure(web_client):
    resp = web_client.get("/api/v1/download/partial/txt")
    assert resp.status_code == 502
    assert not web_client.fake.download_destination.exists()


def test_download_page_not_found(web_client):
    messages = []
    sink = web_module.logger.add(messages.append, format="{message}")
    try:
        resp = web_client.get("/download/bad")
    finally:
        web_module.logger.remove(sink)
    assert resp.status_code == 404
    logged = "".join(str(message) for message in messages)
    assert "/download/{token}" in logged
    assert "/download/bad" not in logged


def test_internal_error_does_not_expose_exception_details(monkeypatch):
    async def fail_download_info(token):
        raise RuntimeError("internal-detail-should-stay-private")

    monkeypatch.setattr(web_module.client, "get_download_info", fail_download_info)
    monkeypatch.setattr(web_module.limiter, "enabled", False)
    with TestClient(web_module.app, raise_server_exceptions=False) as client:
        response = client.get("/download/example")

    assert response.status_code == 500
    assert t(WEB_ERROR_INTERNAL) in response.text
    assert "internal-detail-should-stay-private" not in response.text


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


def test_receipt_cookie_is_private_and_scoped_to_job(web_client):
    response = web_client.post("/process", files={"document_file": ("doc.pdf", _fake_pdf_bytes(), "application/pdf")},
        data={"email": "test@example.com"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/jobs/web12345"
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/jobs/web12345" in cookie
    assert "private-web-token" not in response.text
    assert web_client.get("/jobs/someone-else").status_code == 404
    assert web_client.get("/jobs/web12345", headers={"Cookie": ""}).status_code == 404


@pytest.mark.parametrize("delivery", ["sent", "failed"])
def test_receipt_recovers_result_after_refresh(web_client, monkeypatch, delivery):
    from frontend.web.messages import WEB_JOB_EMAIL_FAILED, WEB_JOB_EMAIL_SENT
    web_client.post("/process", files={"document_file": ("doc.pdf", _fake_pdf_bytes(), "application/pdf")},
        data={"email": "test@example.com"})

    async def status(task_id, job_token=None):
        assert job_token == "private-web-token"
        return {"arquivo": "doc.pdf", "status": "done", "email_delivery": delivery,
            "download_url": "http://web.invalid/download/tok", "erros": []}

    monkeypatch.setattr(web_client.fake, "get_job_status", status)
    for _ in range(2):
        page = web_client.get("/jobs/web12345")
        assert page.status_code == 200
        assert 'href="/download/tok"' in page.text
        assert t(WEB_JOB_EMAIL_FAILED if delivery == "failed" else WEB_JOB_EMAIL_SENT) in page.text
        assert page.headers["cache-control"] == "no-store"
        assert page.headers["referrer-policy"] == "no-referrer"
        assert "private-web-token" not in page.text
        assert 'http-equiv="refresh"' not in page.text


@pytest.mark.parametrize("delivery", ["sent", "failed"])
def test_receipt_explains_the_failure_email(web_client, monkeypatch, delivery):
    """A failed job must not promise a result e-mail: the failure copy is different."""
    from frontend.web.messages import (
        WEB_JOB_EMAIL_SENT,
        WEB_JOB_FAILURE_EMAIL_FAILED,
        WEB_JOB_FAILURE_EMAIL_SENT,
    )

    web_client.post("/process", files={"document_file": ("doc.pdf", _fake_pdf_bytes(), "application/pdf")},
        data={"email": "test@example.com"})

    async def status(task_id, job_token=None):
        return {"arquivo": "doc.pdf", "status": "error", "email_delivery": delivery,
            "download_url": None, "erros": ["pipeline failed"]}

    monkeypatch.setattr(web_client.fake, "get_job_status", status)
    page = web_client.get("/jobs/web12345")

    expected = t(
        WEB_JOB_FAILURE_EMAIL_SENT if delivery == "sent" else WEB_JOB_FAILURE_EMAIL_FAILED
    )
    assert expected in page.text
    # The result-mail copy mentions downloading files that do not exist here.
    assert t(WEB_JOB_EMAIL_SENT) not in page.text
    assert "pipeline failed" in page.text


@pytest.mark.parametrize(("status_value", "delivery", "shows_close_info", "shows_pending"), [
    ("queued", None, True, False),
    ("processing", None, True, False),
    ("processing", "pending", True, False),
    ("done", "pending", True, False),
    ("done", "sent", False, False),
    ("done", "failed", False, False),
    ("done", "unknown", False, False),
    ("error", None, False, False),
    ("cancelled", None, False, False),
    ("cancelling", None, False, True),
])
def test_receipt_close_info_only_while_the_email_promise_holds(
    web_client, monkeypatch, status_value, delivery, shows_close_info, shows_pending
):
    """The "you can safely close this window" notice must appear only while the
    email promise still holds (job queued/processing or email still pending).

    For finished jobs the delivery alerts already tell the user what happened,
    and for error/cancelled jobs no result email is sent at all, so promising
    one would contradict the page. When the notice shows, it must replace
    WEB_JOB_PENDING instead of stacking with it, and while the job is
    cancelling (no close-info promise) the pending guidance still applies.
    """
    web_client.post("/process", files={"document_file": ("doc.pdf", _fake_pdf_bytes(), "application/pdf")},
        data={"email": "test@example.com"})

    async def status(task_id, job_token=None):
        assert job_token == "private-web-token"
        return {"arquivo": "doc.pdf", "status": status_value, "etapa_atual": "…",
            "email_delivery": delivery,
            "download_url": "http://web.invalid/download/tok", "erros": []}

    monkeypatch.setattr(web_client.fake, "get_job_status", status)
    page = web_client.get("/jobs/web12345")
    assert page.status_code == 200
    close_info = t(WEB_JOB_CLOSE_INFO).format(days=TOKEN_EXPIRY_DAYS)
    assert (close_info in page.text) is shows_close_info
    assert (t(WEB_JOB_PENDING) in page.text) is shows_pending


def test_receipt_survives_temporary_api_failure(web_client, monkeypatch):
    from frontend.web.messages import WEB_JOB_UNAVAILABLE
    web_client.post("/process", files={"document_file": ("doc.pdf", _fake_pdf_bytes(), "application/pdf")},
        data={"email": "test@example.com"})

    async def unavailable(*args, **kwargs):
        raise ApiError(503, "upstream unavailable")

    monkeypatch.setattr(web_client.fake, "get_job_status", unavailable)
    page = web_client.get("/jobs/web12345")
    assert page.status_code == 503
    assert t(WEB_JOB_UNAVAILABLE) in page.text
    assert 'http-equiv="refresh"' in page.text


def test_receipt_cookie_requires_https_when_served_over_https(web_client):
    response = web_client.post("https://testserver/process", files={"document_file": ("doc.pdf", _fake_pdf_bytes(), "application/pdf")},
        data={"email": "test@example.com"}, follow_redirects=False)
    assert response.status_code == 303
    assert "; Secure" in response.headers["set-cookie"]
