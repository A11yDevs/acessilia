import asyncio

import pytest

from backend.config.settings import settings
from backend.services import download_token_service as token_service


@pytest.fixture(autouse=True)
def isolate_token_database(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "temp_dir", tmp_path / "temp")
    token_service._connection = None
    yield
    if token_service._connection is not None:
        token_service._connection.close()
        token_service._connection = None


def test_expired_download_token_is_rejected(tmp_path):
    output_dir = tmp_path / "output" / "job-expirado"
    output_dir.mkdir(parents=True)
    (output_dir / "doc.txt").write_text("resultado", encoding="utf-8")
    token = asyncio.run(token_service.criar_token(output_dir, "doc"))
    connection = token_service._get_connection()
    connection.execute(
        "UPDATE download_tokens SET criado_em = datetime('now', '-8 days') WHERE token = ?",
        (token,),
    )
    connection.commit()

    info = asyncio.run(token_service.obter_info_token(token))

    assert info is None


def test_recent_download_token_remains_valid(tmp_path):
    output_dir = tmp_path / "output" / "job-recente"
    output_dir.mkdir(parents=True)
    (output_dir / "doc.txt").write_text("resultado", encoding="utf-8")
    token = asyncio.run(token_service.criar_token(output_dir, "doc"))

    info = asyncio.run(token_service.obter_info_token(token))

    assert info is not None
    assert info["stem"] == "doc"


def test_download_tokens_are_not_written_to_application_logs(tmp_path):
    messages = []
    sink = token_service.logger.add(messages.append, level="DEBUG", format="{message}")
    try:
        output_dir = tmp_path / "output" / "job"
        output_dir.mkdir(parents=True)
        token = asyncio.run(token_service.criar_token(output_dir, "doc"))
        asyncio.run(token_service.obter_info_token("unknown-download-token"))
        output_dir.rmdir()
        asyncio.run(token_service.obter_info_token(token))
    finally:
        token_service.logger.remove(sink)

    logged = "".join(str(message) for message in messages)
    assert token not in logged
    assert "unknown-download-token" not in logged


def test_download_token_only_lists_registered_formats(tmp_path):
    output_dir = tmp_path / "output" / "job-partial"
    output_dir.mkdir(parents=True)
    (output_dir / "doc.pdf_ua.pdf").write_bytes(b"partial pdf")
    (output_dir / "doc_acessivel.zip").write_bytes(b"complete zip")
    token = asyncio.run(
        token_service.criar_token(output_dir, "doc", formats=["zip"])
    )

    info = asyncio.run(token_service.obter_info_token(token))

    assert info is not None
    assert [item["ext"] for item in info["formats"]] == ["zip"]


def test_download_token_stores_task_id_and_owner(tmp_path):
    output_dir = tmp_path / "output" / "job-owner"
    output_dir.mkdir(parents=True)
    (output_dir / "doc.txt").write_text("resultado", encoding="utf-8")
    token = asyncio.run(
        token_service.criar_token(
            output_dir,
            "doc",
            formats=["txt"],
            task_id="task-12345",
            owner="user@example.com",
        )
    )

    info = asyncio.run(token_service.obter_info_token(token))

    assert info is not None
    assert info["task_id"] == "task-12345"
    assert info["owner"] == "user@example.com"
