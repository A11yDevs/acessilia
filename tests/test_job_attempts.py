"""Per-attempt configuration history and result provenance (#944).

Each attempt is appended once with its immutable configuration; the result is
filled once, and the job's current attempt pointer is written with the snapshot
in the same transaction.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from backend.config.settings import settings
from backend.services import job_store


def _job(tmp_path, monkeypatch, task_id: str = "attempt-job") -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    job_store.save_request(
        task_id, "token", {"file": "a.pdf"}, {"task_id": task_id, "status": "queued"}
    )


def _attempt(attempt_id: str, captured_at: str, *, resumed: bool = False) -> dict:
    return {"id": attempt_id, "captured_at": captured_at, "resumed": resumed}


def _configuration(attempt_id: str) -> dict:
    return {
        "schema": "acessilia/effective-configuration@2",
        "attempt": {"id": attempt_id},
    }


def test_attempts_are_append_only_and_the_latest_is_current(tmp_path, monkeypatch) -> None:
    _job(tmp_path, monkeypatch)

    job_store.save_attempt_start(
        "attempt-job", _attempt("a", "2026-11-27T10:00:00+00:00"), _configuration("a")
    )
    job_store.save_attempt_result(
        "attempt-job", "a", state="completed", origin="cache"
    )
    job_store.save_attempt_start(
        "attempt-job",
        _attempt("b", "2026-11-27T10:05:00+00:00", resumed=True),
        _configuration("b"),
    )
    job_store.save_attempt_result(
        "attempt-job",
        "b",
        state="completed",
        origin="resumed",
        reused_phases=["manifest", "enriched"],
    )

    attempts = job_store.load_attempts("attempt-job")
    assert [item["attempt_id"] for item in attempts] == ["a", "b"]
    assert [item["configuration"]["attempt"]["id"] for item in attempts] == ["a", "b"]
    assert attempts[0]["origin"] == "cache"
    assert attempts[1]["origin"] == "resumed"
    assert attempts[1]["reused_phases"] == ["manifest", "enriched"]
    assert attempts[1]["resumed"] is True

    latest = job_store.load_latest_attempt("attempt-job")
    assert latest["attempt_id"] == "b"
    assert job_store.load_record("attempt-job")["current_attempt_id"] == "b"

    # A finished result is immutable: a second write finds no started row.
    with pytest.raises(LookupError):
        job_store.save_attempt_result(
            "attempt-job", "a", state="failed", origin="unknown"
        )


def test_attempt_result_values_are_validated(tmp_path, monkeypatch) -> None:
    _job(tmp_path, monkeypatch)
    job_store.save_attempt_start(
        "attempt-job", _attempt("a", "2026-11-27T10:00:00+00:00"), _configuration("a")
    )

    with pytest.raises(ValueError):
        job_store.save_attempt_result(
            "attempt-job", "a", state="started", origin="produced"
        )
    with pytest.raises(ValueError):
        job_store.save_attempt_result(
            "attempt-job", "a", state="completed", origin="made-up"
        )
    with pytest.raises(LookupError):
        job_store.save_attempt_result(
            "attempt-job", "missing", state="completed", origin="produced"
        )


def test_an_unknown_job_does_not_append_an_attempt(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)

    with pytest.raises(LookupError):
        job_store.save_attempt_start(
            "missing", _attempt("a", "2026-11-27T10:00:00+00:00"), _configuration("a")
        )

    assert job_store.load_attempts("missing") == []


def test_delete_request_removes_the_attempt_history(tmp_path, monkeypatch) -> None:
    _job(tmp_path, monkeypatch)
    job_store.save_attempt_start(
        "attempt-job", _attempt("a", "2026-11-27T10:00:00+00:00"), _configuration("a")
    )

    job_store.delete_request("attempt-job")

    assert job_store.load_record("attempt-job") is None
    assert job_store.load_attempts("attempt-job") == []


def test_a_legacy_database_is_migrated_and_keeps_its_rows(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    database = tmp_path / "history.db"
    with sqlite3.connect(database) as conn:
        conn.execute(
            "CREATE TABLE api_jobs (task_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, "
            "request TEXT NOT NULL, status TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO api_jobs VALUES ('legacy', 'hash', '{}', '{\"status\": \"done\"}')"
        )

    job_store.save_request(
        "new-job", "token", {}, {"task_id": "new-job", "status": "queued"}
    )
    job_store.save_attempt_start(
        "new-job", _attempt("a", "2026-11-27T10:00:00+00:00"), _configuration("a")
    )

    legacy = job_store.load_record("legacy")
    assert legacy["status"] == {"status": "done"}
    assert legacy["configuration"] is None
    assert legacy["current_attempt_id"] is None
    assert job_store.load_latest_attempt("new-job")["attempt_id"] == "a"
    with sqlite3.connect(database) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(api_jobs)")}
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    assert {"configuration", "current_attempt_id"} <= columns
    assert "job_attempts" in tables


def test_save_configuration_remains_a_compatibility_wrapper(tmp_path, monkeypatch) -> None:
    _job(tmp_path, monkeypatch)

    job_store.save_configuration(
        "attempt-job",
        {
            "schema": "acessilia/effective-configuration@2",
            "attempt": {
                "id": "compat",
                "captured_at": "2026-11-27T10:00:00+00:00",
                "resumed": False,
            },
        },
    )

    latest = job_store.load_latest_attempt("attempt-job")
    assert latest["attempt_id"] == "compat"
    assert job_store.load_record("attempt-job")["configuration"] == latest["configuration"]

def test_a_942_configuration_is_kept_as_a_legacy_attempt(tmp_path, monkeypatch) -> None:
    """The snapshot that existed before #944 survives the next attempt."""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    database = tmp_path / "history.db"
    legacy_configuration = {
        "schema": "acessilia/effective-configuration@2",
        "attempt": {
            "id": "legacy-a",
            "captured_at": "2026-11-27T09:00:00+00:00",
            "resumed": False,
        },
        "processing": {"run": {"mode": "normal"}},
    }
    with sqlite3.connect(database) as conn:
        conn.execute(
            "CREATE TABLE api_jobs (task_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, "
            "request TEXT NOT NULL, status TEXT NOT NULL, configuration TEXT)"
        )
        conn.execute(
            "INSERT INTO api_jobs VALUES (?, ?, ?, ?, ?)",
            (
                "legacy-job",
                "hash",
                "{}",
                '{"task_id": "legacy-job", "status": "processing"}',
                None,  # overwritten below with valid JSON
            ),
        )
        conn.execute(
            "UPDATE api_jobs SET configuration=? WHERE task_id=?",
            (json.dumps(legacy_configuration), "legacy-job"),
        )

    # Opening the database migrates it and copies the old snapshot.
    assert job_store.load_record("legacy-job")["current_attempt_id"] == "legacy-a"
    legacy = job_store.load_attempts("legacy-job")
    assert len(legacy) == 1
    assert legacy[0]["attempt_id"] == "legacy-a"
    assert legacy[0]["state"] == "legacy"
    assert legacy[0]["origin"] == "unknown"
    assert legacy[0]["configuration"] == legacy_configuration

    job_store.save_attempt_start(
        "legacy-job",
        _attempt("new-b", "2026-11-27T10:00:00+00:00", resumed=True),
        _configuration("new-b"),
    )

    attempts = job_store.load_attempts("legacy-job")
    assert [item["attempt_id"] for item in attempts] == ["legacy-a", "new-b"]
    assert attempts[0]["configuration"] == legacy_configuration
    assert job_store.load_record("legacy-job")["current_attempt_id"] == "new-b"


def test_a_legacy_configuration_without_an_attempt_id_gets_a_stable_one(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    database = tmp_path / "history.db"
    configuration = {"schema": "acessilia/effective-configuration@2", "processing": {}}
    with sqlite3.connect(database) as conn:
        conn.execute(
            "CREATE TABLE api_jobs (task_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, "
            "request TEXT NOT NULL, status TEXT NOT NULL, configuration TEXT)"
        )
        conn.execute(
            "INSERT INTO api_jobs VALUES (?, ?, ?, ?, ?)",
            (
                "no-id",
                "hash",
                "{}",
                '{"task_id": "no-id", "status": "processing"}',
                json.dumps(configuration),
            ),
        )

    assert job_store.load_latest_attempt("no-id")["attempt_id"] == "legacy-no-id"

def test_the_attempt_marker_reports_whether_it_was_persisted(
    tmp_path, monkeypatch
) -> None:
    _job(tmp_path, monkeypatch)

    assert job_store.save_attempt_marker(
        "attempt-job", "attempt-a", "2026-11-27T10:00:00+00:00"
    )
    status = job_store.load_record("attempt-job")["status"]
    assert status["current_attempt_id"] == "attempt-a"
    assert status["current_attempt_captured_at"] == "2026-11-27T10:00:00+00:00"

    assert not job_store.save_attempt_marker("missing", "attempt-a", "")

    job_store.save_status(
        "attempt-job",
        {"task_id": "attempt-job", "status": "done"},
    )
    assert not job_store.save_attempt_marker(
        "attempt-job", "attempt-b", "2026-11-27T10:05:00+00:00"
    )


def test_reconcile_closes_only_started_attempts(tmp_path, monkeypatch) -> None:
    _job(tmp_path, monkeypatch)
    job_store.save_attempt_start(
        "attempt-job", _attempt("old", "2026-11-27T10:00:00+00:00"), _configuration("old")
    )
    job_store.save_attempt_start(
        "attempt-job", _attempt("done", "2026-11-27T10:01:00+00:00"), _configuration("done")
    )
    job_store.save_attempt_result(
        "attempt-job", "done", state="completed", origin="produced"
    )

    assert job_store.reconcile_started_attempts("attempt-job") == 1
    attempts = job_store.load_attempts("attempt-job")
    assert attempts[0]["state"] == "interrupted"
    assert attempts[0]["origin"] == "unknown"
    assert attempts[0]["error_type"] == "process-restart"
    assert attempts[1]["state"] == "completed"
    # Idempotent: a second recovery changes nothing.
    assert job_store.reconcile_started_attempts("attempt-job") == 0


def test_the_audit_view_reads_the_pointer_and_history_together(
    tmp_path, monkeypatch
) -> None:
    _job(tmp_path, monkeypatch)
    job_store.save_attempt_start(
        "attempt-job", _attempt("a", "2026-11-27T10:00:00+00:00"), _configuration("a")
    )

    record, attempts = job_store.load_audit_view("attempt-job")

    assert record["current_attempt_id"] == "a"
    assert [item["attempt_id"] for item in attempts] == ["a"]
    assert job_store.load_audit_view("missing") == (None, [])

def test_the_attempt_marker_survives_later_status_writes(tmp_path, monkeypatch) -> None:
    _job(tmp_path, monkeypatch)
    assert job_store.save_attempt_marker(
        "attempt-job", "attempt-a", "2026-11-27T10:00:00+00:00"
    )

    status = job_store.load_record("attempt-job")["status"]
    status["etapa_atual"] = "still running"
    job_store.save_status("attempt-job", status)

    persisted = job_store.load_record("attempt-job")["status"]
    assert persisted["current_attempt_id"] == "attempt-a"
    assert persisted["current_attempt_captured_at"] == "2026-11-27T10:00:00+00:00"


@pytest.fixture
def legacy_audit_database(tmp_path, monkeypatch):
    """A five-column #942 database, before any job_store connection opens it."""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    original = ' {"schema": "acessilia/effective-configuration@2", "attempt": {"id": "legacy-a"}} '
    with sqlite3.connect(settings.db_path) as conn:
        conn.execute(
            "CREATE TABLE api_jobs (task_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, "
            "request TEXT NOT NULL, status TEXT NOT NULL, configuration TEXT)"
        )
        conn.execute(
            "INSERT INTO api_jobs VALUES (?, ?, ?, ?, ?)",
            ("legacy-job", "hash", "{}", '{"status":"processing"}', original),
        )
    return original


def test_first_legacy_audit_read_commits_migration_before_its_read_transaction(
    legacy_audit_database,
):
    record, attempts = job_store.load_audit_view("legacy-job")
    assert record["current_attempt_id"] == "legacy-a"
    assert attempts[0]["state"] == "legacy"
    assert attempts[0]["configuration"] == json.loads(legacy_audit_database)
    job_store.save_attempt_start(
        "legacy-job", _attempt("new-b", "2026-11-28T10:00:00+00:00"), _configuration("new-b")
    )
    _, attempts = job_store.load_audit_view("legacy-job")
    assert [item["attempt_id"] for item in attempts] == ["legacy-a", "new-b"]
    with sqlite3.connect(settings.db_path) as conn:
        assert conn.execute(
            "SELECT configuration FROM job_attempts WHERE attempt_id='legacy-a'"
        ).fetchone()[0] == legacy_audit_database


@pytest.mark.parametrize("failure", ["migration", "commit"])
def test_migration_failure_never_caches_success_and_can_retry(
    legacy_audit_database, monkeypatch, failure
):
    migrate = job_store._migrate_legacy_configurations
    connect = sqlite3.connect
    fail_once = True

    def fail_migration(conn):
        nonlocal fail_once
        migrate(conn)
        if failure == "migration" and fail_once:
            fail_once = False
            raise sqlite3.OperationalError("injected migration failure")

    class Connection(sqlite3.Connection):
        def commit(self):
            nonlocal fail_once
            if failure == "commit" and fail_once:
                fail_once = False
                raise sqlite3.OperationalError("injected commit failure")
            return super().commit()

    monkeypatch.setattr(job_store, "_migrate_legacy_configurations", fail_migration)
    monkeypatch.setattr(job_store.sqlite3, "connect", lambda *a, **kw: connect(*a, **kw, factory=Connection))
    with pytest.raises(sqlite3.OperationalError, match="injected"):
        job_store.load_audit_view("legacy-job")
    assert str(settings.db_path) not in job_store._migrated
    _, attempts = job_store.load_audit_view("legacy-job")
    assert len(attempts) == 1
    assert attempts[0]["configuration"] == json.loads(legacy_audit_database)
    assert str(settings.db_path) in job_store._migrated


def test_consumer_failure_cannot_rollback_a_completed_legacy_migration(legacy_audit_database):
    with pytest.raises(RuntimeError, match="consumer"):
        with job_store.connection():
            raise RuntimeError("consumer failed after schema initialization")
    _, attempts = job_store.load_audit_view("legacy-job")
    assert len(attempts) == 1 and attempts[0]["state"] == "legacy"
    assert attempts[0]["configuration"] == json.loads(legacy_audit_database)
