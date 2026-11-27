"""Durable API job requests, authorization digests and terminal status.

One API process owns the queue. Pending requests survive a restart; work that
was executing is marked interrupted rather than retried with side effects.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from typing import Any

from backend.config.settings import settings


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@contextmanager
def connection():
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS api_jobs (task_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, request TEXT NOT NULL, status TEXT NOT NULL)"
        )
        # The effective configuration of the run (#380) lives in its own
        # column: it is written once per job start, while the status is
        # rewritten on every stage. Existing databases gain the column here.
        columns = {row[1] for row in conn.execute("PRAGMA table_info(api_jobs)")}
        if "configuration" not in columns:
            conn.execute("ALTER TABLE api_jobs ADD COLUMN configuration TEXT")
        yield conn
        conn.commit()
    finally:
        conn.close()


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
        conn.execute(
            "UPDATE api_jobs SET configuration=? WHERE task_id=?",
            (json.dumps(configuration, ensure_ascii=False, sort_keys=True), task_id),
        )


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
