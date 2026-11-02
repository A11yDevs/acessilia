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


@pytest.mark.parametrize("reference", ["same", "alias", "child", "parent"])
def test_expired_token_cleanup_preserves_active_directory(tmp_path, reference):
    output = tmp_path / "output" / "job"
    active_dir = output / "child" if reference == "child" else output
    expired_dir = output / "child" if reference == "parent" else output
    active_dir.mkdir(parents=True)
    expired_dir.mkdir(parents=True, exist_ok=True)
    (active_dir / "doc.txt").write_text("valid result", encoding="utf-8")
    if reference == "alias":
        active_dir = active_dir / ".." / "job"
    expired = asyncio.run(token_service.criar_token(expired_dir, "doc"))
    valid = asyncio.run(token_service.criar_token(active_dir, "doc"))
    connection = token_service._get_connection()
    connection.execute(
        "UPDATE download_tokens SET criado_em = datetime('now', '-8 days') WHERE token = ?",
        (expired,),
    )
    connection.commit()

    asyncio.run(token_service.limpar_tokens_expirados())

    assert asyncio.run(token_service.obter_info_token(valid)) is not None
    assert (active_dir / "doc.txt").read_text(encoding="utf-8") == "valid result"
    assert connection.execute(
        "SELECT 1 FROM download_tokens WHERE token = ?", (expired,)
    ).fetchone() is None


@pytest.mark.parametrize("location", ["owned", "prefix-sibling", "root", "symlink"])
def test_cleanup_only_removes_expired_owned_subdirectories(tmp_path, location):
    root = tmp_path / "output"
    root.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    if location == "owned":
        output = root / "job"
        output.mkdir()
    elif location == "prefix-sibling":
        output = tmp_path / "output-unrelated"
        output.mkdir()
    elif location == "symlink":
        output = root / "linked"
        output.symlink_to(external, target_is_directory=True)
    else:
        output = root
    (output / "doc.txt").write_text("result", encoding="utf-8")
    expired = asyncio.run(token_service.criar_token(output, "doc"))
    connection = token_service._get_connection()
    connection.execute(
        "UPDATE download_tokens SET criado_em = datetime('now', '-8 days') WHERE token = ?",
        (expired,),
    )
    connection.commit()

    asyncio.run(token_service.limpar_tokens_expirados())

    assert output.exists() == (location != "owned")


@pytest.mark.parametrize(
    ("size_bytes", "expected"),
    [
        (0, "0 B"),
        (116, "116 B"),
        (500, "500 B"),
        (1023, "1023 B"),
        (1024, "1 KB"),
        (1024 * 1024 - 1, "1024 KB"),
        (1024 * 1024, "1.0 MB"),
        (1536 * 1024, "1.5 MB"),
    ],
)
def test_download_size_formatting(tmp_path, size_bytes, expected):
    output_dir = tmp_path / "output" / "small-file"
    output_dir.mkdir(parents=True)
    (output_dir / "doc.txt").write_bytes(b"x" * size_bytes)
    token = asyncio.run(token_service.criar_token(output_dir, "doc", formats=["txt"]))

    info = asyncio.run(token_service.obter_info_token(token))

    assert info is not None
    assert len(info["formats"]) == 1
    assert info["formats"][0]["size"] == expected
