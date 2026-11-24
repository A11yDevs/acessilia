"""End-to-end tests against a deployed Acessilia Core API.

Unlike the Toolbox E2E suite, these tests exercise the product as a client sees
it: upload, queue, worker, exports and download links. They need a reachable
API and are skipped unless ``CORE_BASE_URL`` is set, for example::

    CORE_BASE_URL=https://www.acessilia3.inf.ufg.br/api/v1 \
        uv run pytest -m e2e tests/test_core_api_e2e.py -v

``CORE_JOB_TIMEOUT`` (seconds, default 600) bounds each processing wait.
Set ``CORE_EXPECT_BUILD_INFO=1`` for a deployed host whose ``/health`` must
carry the git commit and image tag (the staging image does).

The suite is deliberately frugal: this module makes four uploads at most, one
of them a full job, to stay under the API's 5/minute upload limit.
``test_slide_case_e2e.py`` is the fifth upload when the dataset clone is
present.
"""

from __future__ import annotations

import io
import os
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import httpx
import pytest

from tests.core_api_support import poll, upload

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


@pytest.fixture(scope="module")
def client(core_client: httpx.Client) -> httpx.Client:
    """The shared deployed-core client, under the name this module reads."""
    return core_client


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
    response = upload(
        client, source.read_bytes(), source.name, media_type="application/pdf"
    )
    assert response.status_code == 202, response.text
    receipt = response.json()
    status = poll(client, receipt["task_id"], receipt["job_token"])
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
    response = upload(client, b"not a document", "malicioso.exe")
    assert response.status_code == 400, response.text
    assert response.json().get("detail")


def test_empty_file_is_rejected(client: httpx.Client) -> None:
    response = upload(client, b"", "vazio.pdf", media_type="application/pdf")
    assert response.status_code == 400, response.text
    assert response.json().get("detail")


# ---------------------------------------------------------------------------
# Job authorization and failure path
# ---------------------------------------------------------------------------


def test_corrupt_pdf_requires_the_job_token_and_fails(client: httpx.Client) -> None:
    corrupt = (FIXTURES_DIR / "failures" / "not-a-pdf.pdf").read_bytes()
    response = upload(client, corrupt, "corrompido.pdf", media_type="application/pdf")
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

    status = poll(client, task_id, token)
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

    docx = client.get(f"/download/{token}/docx")
    assert docx.status_code == 200, docx.text
    with zipfile.ZipFile(io.BytesIO(docx.content)) as archive:
        core = ElementTree.fromstring(archive.read("docProps/core.xml"))
    docx_titles = [
        element.text
        for element in core.iter()
        if element.tag.rsplit("}", 1)[-1] == "title"
    ]
    assert docx_titles == [completed_job["stem"]], docx_titles

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
