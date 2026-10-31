"""End-to-end tests against a deployed Acessilia Core API.

Unlike the Toolbox E2E suite, these tests exercise the product as a client sees
it: upload, queue, worker, exports and download links. They need a reachable
API and are skipped unless ``CORE_BASE_URL`` is set, for example::

    CORE_BASE_URL=https://www.acessilia3.inf.ufg.br/api/v1 \
        uv run pytest -m e2e tests/test_core_api_e2e.py -v

``CORE_JOB_TIMEOUT`` (seconds, default 600) bounds each processing wait.
Set ``CORE_EXPECT_BUILD_INFO=1`` for a deployed host whose ``/health`` must
carry the git commit and image tag (the staging image does).

The suite is deliberately frugal: four uploads at most, one of them a full
job, to stay under the API's 5/minute upload limit.
"""

from __future__ import annotations

import io
import os
import re
import time
import zipfile
from pathlib import Path

import httpx
import pytest

CORE_BASE_URL = os.getenv("CORE_BASE_URL", "").strip().rstrip("/")
JOB_TIMEOUT = float(os.getenv("CORE_JOB_TIMEOUT", "600"))
FIXTURES_DIR = Path(__file__).parent / "fixtures"

pytestmark = pytest.mark.e2e

_UUID = re.compile(r"^[0-9a-f]{32}$")

_MEDIA_TYPES = {
    "txt": "text/plain",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf_ua": "application/pdf",
    "html": "text/html",
    "mp3": "audio/mpeg",
    "zip": "application/zip",
}

_EXPECTED_FORMATS = {"txt", "docx", "pdf_ua", "html", "mp3", "zip"}


def _require_core() -> str:
    if not CORE_BASE_URL:
        pytest.skip("CORE_BASE_URL not configured")
    return CORE_BASE_URL


@pytest.fixture(scope="module")
def client() -> httpx.Client:
    base = _require_core()
    with httpx.Client(base_url=base, timeout=60.0) as http:
        try:
            response = http.get("/health")
        except httpx.HTTPError as exc:
            pytest.skip(f"Core API is not reachable at {base}: {exc}")
        if response.status_code != 200:
            pytest.skip(f"Core API health returned {response.status_code} at {base}")
        yield http


def _upload(
    client: httpx.Client,
    content: bytes,
    filename: str,
    *,
    media_type: str = "application/octet-stream",
    data: dict[str, str] | None = None,
) -> httpx.Response:
    """Upload, waiting out the API's per-IP upload rate limit.

    ``POST /jobs`` allows five requests a minute. A clean run of this module
    makes four; a developer running it twice in a row, or another client on the
    same address, can exhaust the window. Waiting for the documented window
    keeps the suite from reporting a false product failure.
    """
    response: httpx.Response | None = None
    for attempt in range(3):
        response = client.post(
            "/jobs",
            files={"document_file": (filename, content, media_type)},
            data=data or {"email": ""},
        )
        if response.status_code != 429 or attempt == 2:
            return response
        retry_after = response.headers.get("Retry-After", "")
        delay = int(retry_after) if retry_after.isdigit() else 61
        time.sleep(min(max(delay, 1), 90))
    assert response is not None
    return response


def _poll(client: httpx.Client, task_id: str, token: str) -> dict:
    """Wait for a terminal job state; fail with the last status on timeout."""
    headers = {"X-Job-Token": token}
    deadline = time.monotonic() + JOB_TIMEOUT
    last: dict = {}
    while time.monotonic() < deadline:
        response = client.get(f"/jobs/{task_id}", headers=headers)
        assert response.status_code == 200, response.text
        last = response.json()
        if last.get("status") in {"done", "error", "cancelled"}:
            return last
        time.sleep(2)
    pytest.fail(f"Job {task_id} did not finish in {JOB_TIMEOUT:.0f}s: {last}")


def _make_untitled_pdf(path: Path) -> None:
    """A two-page PDF with paragraphs only: no heading infers a title."""
    pymupdf = pytest.importorskip("pymupdf")
    document = pymupdf.open()
    try:
        for number in (1, 2):
            page = document.new_page()
            page.insert_text((72, 90), f"Pagina {number}", fontsize=11)
            page.insert_text(
                (72, 120),
                "Conteudo simples, sem titulo nem cabecalho.",
                fontsize=11,
            )
            page.insert_text(
                (72, 150),
                "O titulo do documento deve vir do nome enviado.",
                fontsize=11,
            )
        document.save(path)
    finally:
        document.close()


@pytest.fixture(scope="module")
def completed_job(client: httpx.Client, tmp_path_factory) -> dict:
    """One real job shared by the download and title tests."""
    source = tmp_path_factory.mktemp("core-e2e") / "sem-titulo.pdf"
    _make_untitled_pdf(source)
    response = _upload(
        client, source.read_bytes(), source.name, media_type="application/pdf"
    )
    assert response.status_code == 202, response.text
    receipt = response.json()
    status = _poll(client, receipt["task_id"], receipt["job_token"])
    assert status["status"] == "done", status
    assert not status.get("erros"), status
    assert status.get("download_url"), status
    token = status["download_url"].rsplit("/download/", 1)[-1]
    return {"status": status, "token": token, "stem": source.stem}


# ---------------------------------------------------------------------------
# Health and readiness
# ---------------------------------------------------------------------------


def test_health_reports_a_complete_contract(client: httpx.Client) -> None:
    response = client.get("/health")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["status"] == "ok"
    assert isinstance(body["model_reachable"], bool)
    assert isinstance(body["queue_size"], int)
    for field in (
        "model_client",
        "model_name",
        "git_commit",
        "image_tag",
        "image_digest",
        "ghcr_latest_sha",
        "last_check",
        "up_to_date",
        "update_available",
        "update_check_stale",
    ):
        assert field in body, f"/health is missing {field}"
    if body["up_to_date"]:
        assert body["ghcr_latest_sha"]
        assert not body["update_available"]
        assert not body["update_check_stale"]
    if os.getenv("CORE_EXPECT_BUILD_INFO") == "1":
        assert body["git_commit"], "deployed /health has no git_commit"
        assert body["image_tag"], "deployed /health has no image_tag"


def test_ready_follows_the_toolbox(client: httpx.Client) -> None:
    response = client.get("/ready")
    body = response.json()
    assert response.status_code == 200, f"core is not ready: {body}"
    assert body == {"status": "ready"}


# ---------------------------------------------------------------------------
# Upload validation (no job is queued by these)
# ---------------------------------------------------------------------------


def test_unsupported_extension_is_rejected(client: httpx.Client) -> None:
    response = _upload(client, b"not a document", "malicioso.exe")
    assert response.status_code == 400, response.text
    assert response.json().get("detail")


def test_empty_file_is_rejected(client: httpx.Client) -> None:
    response = _upload(client, b"", "vazio.pdf", media_type="application/pdf")
    assert response.status_code == 400, response.text
    assert response.json().get("detail")


# ---------------------------------------------------------------------------
# Job authorization and failure path
# ---------------------------------------------------------------------------


def test_corrupt_pdf_requires_the_job_token_and_fails(client: httpx.Client) -> None:
    corrupt = (FIXTURES_DIR / "failures" / "not-a-pdf.pdf").read_bytes()
    response = _upload(client, corrupt, "corrompido.pdf", media_type="application/pdf")
    assert response.status_code == 202, response.text
    receipt = response.json()
    task_id = receipt["task_id"]
    token = receipt["job_token"]
    assert token

    assert client.get(f"/jobs/{task_id}").status_code == 404
    assert (
        client.get(f"/jobs/{task_id}", headers={"X-Job-Token": "invalido"}).status_code
        == 404
    )

    status = _poll(client, task_id, token)
    assert status["status"] == "error", status
    assert status["erros"], status
    assert status["download_url"] is None


# ---------------------------------------------------------------------------
# Full pipeline and delivered formats
# ---------------------------------------------------------------------------


def test_full_job_delivers_every_advertised_format(
    client: httpx.Client, completed_job: dict
) -> None:
    token = completed_job["token"]
    info = client.get(f"/download/{token}")
    assert info.status_code == 200, info.text
    body = info.json()

    assert body["filename"]
    assert body["stem"] == completed_job["stem"]
    formats = {item["ext"] for item in body["formats"]}
    assert _EXPECTED_FORMATS <= formats, formats

    contents: dict[str, bytes] = {}
    for item in body["formats"]:
        ext = item["ext"]
        response = client.get(f"/download/{token}/{ext}")
        assert response.status_code == 200, f"{ext}: {response.text}"
        assert response.content, f"{ext} is empty"
        assert response.headers["content-type"].startswith(_MEDIA_TYPES[ext])
        contents[ext] = response.content

    assert contents["docx"].startswith(b"PK")
    assert contents["zip"].startswith(b"PK")
    assert contents["pdf_ua"].startswith(b"%PDF")
    assert contents["mp3"].startswith((b"ID3", b"\xff"))
    assert b"<html" in contents["html"].lower()

    with zipfile.ZipFile(io.BytesIO(contents["zip"])) as archive:
        names = archive.namelist()
    assert any(name.endswith(".txt") for name in names), names
    assert any(name.endswith(".html") for name in names), names
    assert any(name.endswith(".docx") for name in names), names
    assert any(name.endswith(".pdf_ua.pdf") for name in names), names

    # The veraPDF report is only packaged when the audit ran; when present it
    # must describe a compliant PDF/UA.
    report_name = next(
        (name for name in names if name.endswith(".verapdf.json")), None
    )
    if report_name is not None:
        import json

        with zipfile.ZipFile(io.BytesIO(contents["zip"])) as archive:
            report = json.loads(archive.read(report_name))
        assert report.get("compliant") is True, report


def test_untitled_document_uses_the_uploaded_filename_as_title(
    client: httpx.Client, completed_job: dict
) -> None:
    token = completed_job["token"]
    html = client.get(f"/download/{token}/html")
    assert html.status_code == 200, html.text
    title = re.search(r"<title>(.*?)</title>", html.text, re.DOTALL)
    assert title is not None
    assert title.group(1).strip() == completed_job["stem"]
    assert not _UUID.match(title.group(1).strip())

    pymupdf = pytest.importorskip("pymupdf")
    pdf = client.get(f"/download/{token}/pdf_ua")
    assert pdf.status_code == 200, pdf.text
    document = pymupdf.open(stream=pdf.content, filetype="pdf")
    try:
        assert (document.metadata or {}).get("title") == completed_job["stem"]
    finally:
        document.close()


def test_download_rejects_unknown_tokens_and_formats(
    client: httpx.Client, completed_job: dict
) -> None:
    assert client.get("/download/token-inexistente").status_code == 404
    token = completed_job["token"]
    assert client.get(f"/download/{token}/exe").status_code == 400
