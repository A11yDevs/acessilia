"""Migration regressions against the schema of the actual production image."""

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.migrations import v0_1_0_to_v0_2_0 as migration


NOW = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
LEGACY_SCHEMA = Path(__file__).parent / "fixtures/migrations/core_0_1_0.sql"


@pytest.fixture
def legacy(tmp_path):
    source = tmp_path / "production/var"
    (source / "data/output").mkdir(parents=True)
    with sqlite3.connect(source / "data/history.db") as conn:
        conn.executescript(LEGACY_SCHEMA.read_text())
    return source, tmp_path / "core-var"


def insert(source, sql, values=()):
    with sqlite3.connect(source / "data/history.db") as conn:
        conn.execute(sql, values)


def asset(source, *, token="keep-secret", days=1, base="document", directory="data/output/job",
          formats=("txt", "pdf", "pdf_ua", "zip"), task_id="task", owner="owner@example.test"):
    output = source / directory
    output.mkdir(parents=True, exist_ok=True)
    for extension in formats:
        (output / (base + migration.SUFFIXES[extension])).write_bytes(extension.encode() + b" result")
    created = migration.sql_timestamp(NOW - timedelta(days=days))
    insert(source, "INSERT INTO download_tokens VALUES (?, ?, ?, ?, ?, ?, ?)", (
        token, "/app/var/" + directory, base, created, json.dumps(list(formats)), task_id, owner,
    ))
    return output


def history(source, *, task_id="task", days=1, status="done"):
    created = migration.sql_timestamp(NOW - timedelta(days=days))
    insert(source, """INSERT INTO conversoes
        (task_id, arquivo, extensao, status, criado_em, concluido_em)
        VALUES (?, 'document.pdf', '.pdf', ?, ?, ?)""", (task_id, status, created, created))


def rows(destination, table):
    with sqlite3.connect(destination / "data/history.db") as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(f'SELECT * FROM "{table}"')]


def test_dry_run_preserves_source_and_creates_no_destination(legacy, capsys):
    source, destination = legacy
    asset(source)
    before = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    assert migration.main(["--source-var", str(source), "--destination-var", str(destination)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["mode"] == "dry-run"
    assert report["rows"]["download_tokens"] == {"retained": 1, "excluded": 0, "invalid_timestamps": 0}
    assert not destination.exists()
    assert before == {str(p.relative_to(source)): p.read_bytes() for p in source.rglob("*") if p.is_file()}


def test_apply_filters_by_token_expiry_not_file_mtime_and_keeps_dependencies(legacy):
    source, destination = legacy
    kept = asset(source)
    for file in kept.iterdir():
        os.utime(file, (0, 0))
    asset(source, token="expired-secret", days=8, directory="data/output/expired", task_id="expired")
    history(source, days=8)  # A long-running job issued its live download later.
    history(source, task_id="expired", days=8)
    history(source, task_id="recent-error", status="error")
    for task in ("task", "expired", "recent-error"):
        insert(source, "INSERT INTO ocr_raw (task_id, page_number, text) VALUES (?, 1, 'recognized')", (task,))
    (source / "temp/cache").mkdir(parents=True)
    (source / "temp/cache/fresh.json").write_text('{"timestamp": 9999999999}')
    (source / "data/output/orphan").mkdir()
    (source / "data/output/orphan/new.txt").write_text("unreferenced")
    report = migration.migrate(source, destination, apply=True, at=NOW)
    assert report["files_to_copy"] == 4
    assert report["rows"]["download_tokens"] == {"retained": 1, "excluded": 1, "invalid_timestamps": 0}
    token = rows(destination, "download_tokens")[0]
    assert token["token"] == "keep-secret"
    assert token["owner"] == "owner@example.test"
    assert token["criado_em"] == migration.sql_timestamp(NOW - timedelta(days=1))
    assert token["output_dir"] == "/app/var/data/output/job"
    assert {row["task_id"] for row in rows(destination, "conversoes")} == {"task", "recent-error"}
    assert {row["task_id"] for row in rows(destination, "ocr_raw")} == {"task", "recent-error"}
    assert rows(destination, "api_jobs") == []
    assert not (destination / "data/output/expired").exists()
    assert not (destination / "data/output/orphan").exists()
    assert not (destination / "temp/cache").exists()
    assert migration.verify(destination)["verified"] is True
    assert (destination / "data/history.db").stat().st_mode & 0o777 == 0o600
    assert destination.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("age,retained", [(timedelta(days=7), 1), (timedelta(days=7, seconds=1), 0),
                                        (timedelta(days=7) - timedelta(seconds=1), 1)])
def test_seven_day_boundary_matches_existing_download_contract(legacy, age, retained):
    source, destination = legacy
    asset(source, days=age.total_seconds() / 86400)
    report = migration.migrate(source, destination, apply=True, at=NOW)
    assert report["rows"]["download_tokens"]["retained"] == retained
    assert len(rows(destination, "download_tokens")) == retained


def test_expired_files_sharing_a_live_directory_are_not_copied(legacy):
    source, destination = legacy
    asset(source, base="live")
    asset(source, token="expired", days=8, base="old", task_id="expired")
    migration.migrate(source, destination, apply=True, at=NOW)
    assert {p.name for p in (destination / "data/output/job").iterdir()} == {
        "live.txt", "live.pdf", "live.pdf_ua.pdf", "live_acessivel.zip",
    }


@pytest.mark.parametrize("directory", ["data/output/job", "temp/web_output/job"])
def test_runtime_paths_are_remapped_and_tokens_are_not_renewed(legacy, directory):
    source, destination = legacy
    asset(source, directory=directory, days=6)
    migration.migrate(source, destination, apply=True, at=NOW, destination_runtime_var=Path("/srv/core/var"))
    token = rows(destination, "download_tokens")[0]
    assert token["output_dir"] == "/srv/core/var/" + directory
    assert token["criado_em"] == migration.sql_timestamp(NOW - timedelta(days=6))


@pytest.mark.parametrize("stored", ["var/data/output/job", "host"])
def test_relative_and_host_storage_paths_are_adapted(legacy, stored):
    source, destination = legacy
    output = asset(source)
    insert(source, "UPDATE download_tokens SET output_dir=?", (str(output) if stored == "host" else stored,))
    migration.migrate(source, destination, apply=True, at=NOW)
    assert rows(destination, "download_tokens")[0]["output_dir"] == "/app/var/data/output/job"


def test_sqlite_snapshot_reads_committed_wal_data(legacy):
    source, destination = legacy
    conn = sqlite3.connect(source / "data/history.db")
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        asset(source)
        assert Path(str(source / "data/history.db") + "-wal").exists()
        report = migration.migrate(source, destination, at=NOW)
        assert report["rows"]["download_tokens"]["retained"] == 1
    finally:
        conn.close()


def test_offset_timestamps_keep_the_same_utc_expiration(legacy):
    source, destination = legacy
    asset(source)
    insert(source, "UPDATE download_tokens SET criado_em='2026-10-26T09:00:00-03:00'")
    migration.migrate(source, destination, apply=True, at=NOW)
    assert rows(destination, "download_tokens")[0]["criado_em"] == "2026-10-26 12:00:00"


def test_old_schema_without_optional_token_columns_is_supported(legacy):
    source, destination = legacy
    asset(source)
    with sqlite3.connect(source / "data/history.db") as conn:
        for column in ("owner", "task_id", "formats"):
            conn.execute(f"ALTER TABLE download_tokens DROP COLUMN {column}")
    migration.migrate(source, destination, apply=True, at=NOW)
    token = rows(destination, "download_tokens")[0]
    assert (token["owner"], token["task_id"], token["formats"]) == ("", "", "[]")
    assert (destination / "data/output/job/document.pdf").exists()


@pytest.mark.parametrize("apply", [False, True])
@pytest.mark.parametrize("status", ["queued", "processing", "cancelling"])
@pytest.mark.parametrize("days", [2, 10 / (24 * 60)])
def test_orphaned_history_is_reported_and_only_repaired_in_destination(legacy, apply, status, days):
    source, destination = legacy
    asset(source)
    history(source, task_id="orphan", days=days, status=status)
    insert(source, "UPDATE conversoes SET concluido_em=NULL WHERE task_id='orphan'")
    insert(source, "INSERT INTO ocr_raw (task_id, page_number, text) VALUES ('orphan', 1, 'recognized')")
    before = (source / "data/history.db").read_bytes()

    report = migration.migrate(source, destination, apply=apply, at=NOW)

    assert report["rows"]["conversoes"] == {
        "retained": 1, "excluded": 0, "invalid_timestamps": 0, "interrupted": 1,
    }
    assert (source / "data/history.db").read_bytes() == before
    assert rows(source, "conversoes")[0]["status"] == status
    if apply:
        repaired = rows(destination, "conversoes")[0]
        assert repaired["status"] == "error"
        assert repaired["erro"] == "Stale: process interrupted"
        assert repaired["criado_em"] == migration.sql_timestamp(NOW - timedelta(days=days))
        assert repaired["concluido_em"] == migration.sql_timestamp(NOW)
        assert rows(destination, "download_tokens")[0]["token"] == "keep-secret"
        assert rows(destination, "ocr_raw")[0]["task_id"] == "orphan"
        assert rows(destination, "api_jobs") == []
        assert migration.verify(destination)["verified"]
    else:
        assert not destination.exists()


@pytest.mark.parametrize("apply", [False, True])
@pytest.mark.parametrize("value", [None, "", "0000-invalid", "2020-01-01-invalid", 123])
def test_ineligible_token_dates_are_excluded_without_breaking_live_links(legacy, apply, value):
    source, destination = legacy
    asset(source)
    asset(source, token="invalid-secret", directory="data/output/invalid", task_id="invalid")
    insert(source, "UPDATE download_tokens SET criado_em=? WHERE token='invalid-secret'", (value,))
    with sqlite3.connect(source / "data/history.db") as conn:
        # Exercise the actual legacy column predicate, including SQL NULL.
        assert not conn.execute(
            "SELECT criado_em >= datetime(?, '-7 days') FROM download_tokens WHERE token='invalid-secret'",
            (migration.sql_timestamp(NOW),),
        ).fetchone()[0]
    before = (source / "data/history.db").read_bytes()

    report = migration.migrate(source, destination, apply=apply, at=NOW)

    assert report["rows"]["download_tokens"] == {"retained": 1, "excluded": 1, "invalid_timestamps": 1}
    assert (source / "data/history.db").read_bytes() == before
    if apply:
        assert [row["token"] for row in rows(destination, "download_tokens")] == ["keep-secret"]
        assert not (destination / "data/output/invalid").exists()
    else:
        assert not destination.exists()


@pytest.mark.parametrize("apply", [False, True])
@pytest.mark.parametrize("value", [None, "not-a-date"])
def test_unreferenced_invalid_history_dates_are_counted_and_excluded(legacy, apply, value):
    source, destination = legacy
    asset(source)
    history(source, task_id="invalid")
    insert(source, "UPDATE conversoes SET criado_em=? WHERE task_id='invalid'", (value,))
    insert(source, "INSERT INTO ocr_raw (task_id, page_number, text) VALUES ('invalid', 1, 'recognized')")
    report = migration.migrate(source, destination, apply=apply, at=NOW)
    assert report["rows"]["conversoes"] == {
        "retained": 0, "excluded": 1, "invalid_timestamps": 1, "interrupted": 0,
    }
    if apply:
        assert rows(destination, "conversoes") == []
        assert rows(destination, "ocr_raw") == []


@pytest.mark.parametrize("value", [None, "not-a-date"])
def test_invalid_history_supporting_a_live_download_still_blocks_publication(legacy, value):
    source, destination = legacy
    asset(source)
    history(source)
    insert(source, "UPDATE conversoes SET criado_em=?", (value,))
    with pytest.raises(migration.MigrationError, match="history with an invalid timestamp"):
        migration.migrate(source, destination, apply=True, at=NOW)
    assert not destination.exists()


def test_invalid_date_accepted_by_legacy_sql_is_not_silently_discarded(legacy):
    source, destination = legacy
    asset(source)
    insert(source, "UPDATE download_tokens SET criado_em='not-a-date'")
    with sqlite3.connect(source / "data/history.db") as conn:
        assert conn.execute(
            "SELECT criado_em >= datetime(?, '-7 days') FROM download_tokens",
            (migration.sql_timestamp(NOW),),
        ).fetchone()[0] == 1
    with pytest.raises(migration.MigrationError, match="source expiry predicate"):
        migration.migrate(source, destination, apply=True, at=NOW)
    assert not destination.exists()


@pytest.mark.parametrize("change", ["missing-file", "symlink-file", "symlink-directory", "escape", "filename", "formats",
                                  "timestamp", "future", "unknown-table", "unknown-column", "processing"])
def test_incomplete_or_unsupported_assets_abort_without_publishing(legacy, tmp_path, change):
    source, destination = legacy
    output = asset(source)
    if change == "missing-file":
        (output / "document.txt").unlink()
    elif change == "symlink-file":
        (output / "document.txt").unlink()
        (output / "document.txt").symlink_to(tmp_path / "outside")
    elif change == "symlink-directory":
        renamed = output.with_name("renamed")
        output.rename(renamed)
        output.symlink_to(renamed, target_is_directory=True)
    elif change == "escape":
        insert(source, "UPDATE download_tokens SET output_dir='/app/var/temp/../../outside'")
    elif change == "filename":
        insert(source, "UPDATE download_tokens SET filename='../outside'")
    elif change == "formats":
        insert(source, "UPDATE download_tokens SET formats='[\"unknown\"]'")
    elif change == "timestamp":
        insert(source, "UPDATE download_tokens SET criado_em='not-a-date'")
    elif change == "future":
        insert(source, "UPDATE download_tokens SET criado_em=?", (migration.sql_timestamp(NOW + timedelta(days=1)),))
    elif change == "unknown-table":
        insert(source, "CREATE TABLE unexpected (data TEXT)")
    elif change == "unknown-column":
        insert(source, "ALTER TABLE download_tokens ADD COLUMN unexpected TEXT")
    else:
        history(source, status="processing")
    with pytest.raises(migration.MigrationError):
        migration.migrate(source, destination, apply=True, at=NOW)
    assert not destination.exists()
    assert not list(destination.parent.glob(".core-var.migration-*"))


def test_partial_copy_failure_keeps_source_and_discards_staging(legacy, monkeypatch):
    source, destination = legacy
    output = asset(source)
    def fail(*args):
        raise OSError("simulated full disk")
    monkeypatch.setattr(migration.shutil, "copy2", fail)
    with pytest.raises(OSError, match="full disk"):
        migration.migrate(source, destination, apply=True, at=NOW)
    assert (output / "document.txt").read_bytes() == b"txt result"
    assert not destination.exists()
    assert not list(destination.parent.glob(".core-var.migration-*"))


def test_database_writes_during_copy_abort_publication(legacy, monkeypatch):
    source, destination = legacy
    asset(source)
    original = migration.shutil.copy2
    def modify_database(*args):
        result = original(*args)
        insert(source, "UPDATE download_tokens SET owner='changed'")
        return result
    monkeypatch.setattr(migration.shutil, "copy2", modify_database)
    with pytest.raises(migration.MigrationError, match="database changed"):
        migration.migrate(source, destination, apply=True, at=NOW)
    assert not destination.exists()


def test_repeated_apply_refuses_to_overwrite_the_destination(legacy):
    source, destination = legacy
    asset(source)
    migration.migrate(source, destination, apply=True, at=NOW)
    with pytest.raises(migration.MigrationError, match="already exists"):
        migration.migrate(source, destination, apply=True, at=NOW)
    assert migration.verify(destination)["verified"]


def test_destination_must_not_overlap_source(legacy):
    source, _ = legacy
    asset(source)
    with pytest.raises(migration.MigrationError, match="overlap"):
        migration.migrate(source, source / "new", at=NOW)


def test_verification_detects_damaged_files_and_does_not_print_tokens(legacy, capsys):
    source, destination = legacy
    asset(source)
    migration.migrate(source, destination, apply=True, at=NOW)
    assert migration.main(["--verify", "--destination-var", str(destination)]) == 0
    assert "keep-secret" not in capsys.readouterr().out
    (destination / "data/output/job/document.txt").write_bytes(b"damaged")
    assert migration.main(["--verify", "--destination-var", str(destination)]) == 1
    captured = capsys.readouterr()
    assert "checksum" in captured.err
    assert "keep-secret" not in captured.err


def test_actual_020_api_downloads_legacy_tokens_and_rejects_expired_ones(legacy, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.api.app import app
    from backend.config.settings import settings
    from backend.services import download_token_service as tokens, history_service, queue_service

    source, destination = legacy
    current = datetime.now(timezone.utc)
    asset(source, days=(NOW - current).total_seconds() / 86400 + 1)
    asset(source, token="expired-secret", days=(NOW - current).total_seconds() / 86400 + 8,
          directory="data/output/expired", task_id="expired")
    migration.migrate(source, destination, apply=True, at=current, destination_runtime_var=destination)
    original_connection = tokens._connection
    monkeypatch.setattr(tokens, "_connection", None)
    monkeypatch.setattr(history_service, "_connection", None)
    monkeypatch.setattr(queue_service.unified_queue, "_worker_task", None)
    monkeypatch.setattr(settings, "data_dir", destination / "data")
    monkeypatch.setattr(settings, "temp_dir", destination / "temp")
    monkeypatch.setattr(settings, "logs_dir", destination / "logs")
    try:
        with TestClient(app) as client:
            info = client.get("/api/v1/download/keep-secret")
            assert info.status_code == 200
            assert {f["ext"] for f in info.json()["formats"]} == {"txt", "pdf", "pdf_ua", "zip"}
            for extension in ("txt", "pdf", "pdf_ua", "zip"):
                result = client.get(f"/api/v1/download/keep-secret/{extension}")
                assert result.status_code == 200
                assert result.content == extension.encode() + b" result"
            assert client.get("/api/v1/download/expired-secret").status_code == 404
            insert(destination, "UPDATE download_tokens SET criado_em=datetime('now', '-8 days')")
            assert client.get("/api/v1/download/keep-secret").status_code == 404
    finally:
        if tokens._connection is not None:
            tokens._connection.close()
        if history_service._connection is not None:
            history_service._connection.close()
        tokens._connection = original_connection
