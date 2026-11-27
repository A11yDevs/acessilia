"""Durable API job requests, authorization digests and terminal status.

One API process owns the queue. Pending requests survive a restart; work that
was executing is marked interrupted rather than retried with side effects.

The ``configuration`` column stores the latest effective-configuration attempt
(#380). New databases are created with it; a database from an earlier release
gains it through ``ALTER TABLE ADD COLUMN`` on the first connection, which
preserves every existing row. Rollback note: a release before #380 inserts with
``INSERT INTO api_jobs VALUES (?, ?, ?, ?)`` and fails on the five-column table,
so rolling back requires a compatible build or a controlled restore from a
backup taken after the migration (rows written after that backup are lost). No
column is dropped or data deleted automatically.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any

from backend.config.settings import settings

#: Databases this process already inspected for the #380 column. The check runs
#: once per database path, not once per short-lived connection.
_migrated: set[str] = set()
_migration_lock = threading.Lock()


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@contextmanager
def connection():
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        _ensure_schema(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create ``api_jobs`` with the current shape and migrate an old one.

    New databases are created with ``configuration`` directly. An existing
    database from before #380 is altered once per process and path; the
    ``PRAGMA`` is not run on every connection. ``CREATE TABLE IF NOT EXISTS``
    leaves an existing table untouched, so the migration is additive.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS api_jobs (task_id TEXT PRIMARY KEY, "
        "token_hash TEXT NOT NULL, request TEXT NOT NULL, status TEXT NOT NULL, "
        "configuration TEXT)"
    )
    key = str(settings.db_path)
    if key in _migrated:
        return
    with _migration_lock:
        if key in _migrated:
            return
        columns = {row[1] for row in conn.execute("PRAGMA table_info(api_jobs)")}
        if "configuration" not in columns:
            try:
                conn.execute("ALTER TABLE api_jobs ADD COLUMN configuration TEXT")
            except sqlite3.OperationalError as exc:
                # Another process may have added it between the PRAGMA and
                # the ALTER; that is the same end state, not a failure.
                if "duplicate column" not in str(exc).lower():
                    raise
        _migrated.add(key)


def save_request(task_id: str, token: str, request: dict, status: dict) -> None:
    with connection() as conn:
        conn.execute(
            "INSERT INTO api_jobs (task_id, token_hash, request, status) VALUES (?, ?, ?, ?)",
            (task_id, token_digest(token), json.dumps(request), json.dumps(status)),
        )


def save_configuration(task_id: str, configuration: dict[str, Any]) -> None:
    """Store the effective configuration of the job's run (#380).

    Written once at the job's start. A resumed job overwrites it with the
    configuration its current run uses, so the record never describes a run
    that did not happen.
    """
    with connection() as conn:
        updated = conn.execute(
            "UPDATE api_jobs SET configuration=? WHERE task_id=?",
            (json.dumps(configuration, ensure_ascii=False, sort_keys=True), task_id),
        ).rowcount
    if updated == 0:
        # A missing job is a persistence failure, not a silent no-op: the
        # caller must not believe a record it did not store is current.
        raise LookupError("no api_jobs row for the task")


def load_record(task_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM api_jobs WHERE task_id=?", (task_id,)
        ).fetchone()
    if row is None:
        return None
    configuration = row["configuration"]
    return {
        "task_id": row["task_id"],
        "token_hash": row["token_hash"],
        "request": json.loads(row["request"]),
        "status": json.loads(row["status"]),
        "configuration": json.loads(configuration) if configuration else None,
    }


def save_status(task_id: str, status: dict) -> None:
    # ``resultado`` and the effective configuration live outside the status:
    # one is the job's result, the other is written once by
    # ``save_configuration`` (#380).
    status = {
        key: value
        for key, value in status.items()
        if key not in {"resultado", "configuracao_efetiva"}
    }
    destination = status.get("status")
    if destination not in {"queued", "processing", "cancelling", "cancelled", "done", "error"}:
        raise ValueError("A valid job status is required")
    with connection() as conn:
        conn.execute(
            """UPDATE api_jobs SET status=? WHERE task_id=?
               AND NOT (
                   COALESCE(json_extract(status, '$.status'), '') IN ('done', 'error', 'cancelled')
                   AND ? IN ('queued', 'processing', 'cancelling')
               ) AND NOT (
                   COALESCE(json_extract(status, '$.status'), '') = 'cancelling'
                   AND ? IN ('queued', 'processing')
               ) AND NOT (
                   COALESCE(json_extract(status, '$.status'), '') = 'cancelled'
                   AND ? != 'cancelled'
               )""",
            (json.dumps(status), task_id, destination, destination, destination),
        )


def pending_records() -> list[dict[str, Any]]:
    with connection() as conn:
        ids = [row[0] for row in conn.execute("SELECT task_id FROM api_jobs ORDER BY rowid")]
    return [
        record
        for task_id in ids
        if (record := load_record(task_id))
        and record["status"].get("status") in {"queued", "processing", "cancelling"}
    ]


def delete_request(task_id: str) -> None:
    with connection() as conn:
        conn.execute("DELETE FROM api_jobs WHERE task_id=?", (task_id,))
