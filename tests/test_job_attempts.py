"""Per-attempt configuration history and result provenance (#944).

Each attempt is appended once with its immutable configuration; the result is
filled once, and the job's current attempt pointer is written with the snapshot
in the same transaction.
"""

from __future__ import annotations

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
