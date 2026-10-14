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
        yield conn
        conn.commit()
    finally:
        conn.close()


def save_request(task_id: str, token: str, request: dict, status: dict) -> None:
    with connection() as conn:
        conn.execute(
            "INSERT INTO api_jobs VALUES (?, ?, ?, ?)",
            (task_id, token_digest(token), json.dumps(request), json.dumps(status)),
        )


def load_record(task_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM api_jobs WHERE task_id=?", (task_id,)
        ).fetchone()
    if row is None:
        return None
    return {
        "task_id": row["task_id"],
        "token_hash": row["token_hash"],
        "request": json.loads(row["request"]),
        "status": json.loads(row["status"]),
    }


def save_status(task_id: str, status: dict) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE api_jobs SET status=? WHERE task_id=?",
            (json.dumps(status), task_id),
        )


def pending_records() -> list[dict[str, Any]]:
    with connection() as conn:
        ids = [row[0] for row in conn.execute("SELECT task_id FROM api_jobs")]
    return [
        record
        for task_id in ids
        if (record := load_record(task_id))
        and record["status"].get("status") in {"queued", "processing"}
    ]
