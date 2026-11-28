"""Durable API job requests, authorization digests and terminal status.

One API process owns the queue. Pending requests survive a restart; work that
was executing is marked interrupted rather than retried with side effects.

The ``configuration`` column stores the latest effective-configuration snapshot
(#380), and ``current_attempt_id`` names the attempt that snapshot belongs to.
Every attempt is also appended to ``job_attempts`` (#944), with its own
immutable configuration, result state, origin and reused phases. New databases
are created with these columns; a database from an earlier release gains them
through ``ALTER TABLE ADD COLUMN`` on the first connection, which preserves
every existing row. Rollback note: a release before #380 inserts with
``INSERT INTO api_jobs VALUES (?, ?, ?, ?)`` and fails on the six-column table,
so a plain backup restore is not a transparent rollback:

- a backup taken **before** the migration restores the old schema, but loses
  changes written after it;
- a previous build that names the columns in its ``INSERT`` can keep the
  current schema and rows, subject to compatibility tests;
- a backup taken **after** the migration keeps the six-column schema and does
  not, by itself, make the old writer compatible;
- a controlled reverse migration needs its own procedure, backup and data
  preservation check.

No column is dropped and no data are deleted automatically.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from backend.config.settings import settings

#: Databases this process already inspected for the #380/#944 columns. The check runs
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
        "configuration TEXT, current_attempt_id TEXT)"
    )
    # One row per attempt, append-only: a resumed run adds a new row instead
    # of overwriting the previous configuration (#944).
    conn.execute(
        "CREATE TABLE IF NOT EXISTS job_attempts ("
        "task_id TEXT NOT NULL, attempt_id TEXT NOT NULL, captured_at TEXT NOT NULL, "
        "resumed INTEGER NOT NULL, state TEXT NOT NULL, origin TEXT NOT NULL, "
        "configuration TEXT NOT NULL, reused_phases TEXT NOT NULL, "
        "error_type TEXT, created_at REAL NOT NULL, finished_at REAL, "
        "PRIMARY KEY (task_id, attempt_id))"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_job_attempts_task "
        "ON job_attempts(task_id, created_at)"
    )
    key = str(settings.db_path)
    if key in _migrated:
        return
    with _migration_lock:
        if key in _migrated:
            return
        columns = {row[1] for row in conn.execute("PRAGMA table_info(api_jobs)")}
        for name, definition in (
            ("configuration", "TEXT"),
            ("current_attempt_id", "TEXT"),
        ):
            if name in columns:
                continue
            try:
                conn.execute(f"ALTER TABLE api_jobs ADD COLUMN {name} {definition}")
            except sqlite3.OperationalError as exc:
                # Another process may have added it between the PRAGMA and
                # the ALTER; that is the same end state, not a failure.
                if "duplicate column" not in str(exc).lower():
                    raise
        _migrate_legacy_configurations(conn)
        _migrated.add(key)


def _migrate_legacy_configurations(conn: sqlite3.Connection) -> None:
    """Keep the #942 configuration as the first attempt of its job (#944).

    ``api_jobs.configuration`` is the latest snapshot; before this migration it
    was the only one. A job with a configuration and no attempt row gets a
    ``legacy`` attempt so a later snapshot does not make the previous
    configuration disappear. The original JSON is kept verbatim, and the state
    does not invent a terminal result or a completion time.
    """
    rows = conn.execute(
        "SELECT task_id, configuration FROM api_jobs "
        "WHERE configuration IS NOT NULL AND NOT EXISTS "
        "(SELECT 1 FROM job_attempts a WHERE a.task_id = api_jobs.task_id)"
    ).fetchall()
    for row in rows:
        try:
            configuration = json.loads(row["configuration"])
        except (TypeError, ValueError):
            continue
        if not isinstance(configuration, dict):
            continue
        attempt = configuration.get("attempt")
        if not isinstance(attempt, dict):
            attempt = {}
        attempt_id = str(attempt.get("id") or f"legacy-{row['task_id']}")
        captured_at = str(attempt.get("captured_at") or "")
        resumed = bool(attempt.get("resumed", False))
        conn.execute(
            "INSERT OR IGNORE INTO job_attempts "
            "(task_id, attempt_id, captured_at, resumed, state, origin, "
            "configuration, reused_phases, error_type, created_at, finished_at) "
            "VALUES (?, ?, ?, ?, 'legacy', 'unknown', ?, '[]', NULL, 0, NULL)",
            (
                row["task_id"],
                attempt_id,
                captured_at,
                int(resumed),
                row["configuration"],
            ),
        )
        conn.execute(
            "UPDATE api_jobs SET current_attempt_id=? "
            "WHERE task_id=? AND current_attempt_id IS NULL",
            (attempt_id, row["task_id"]),
        )


def save_request(task_id: str, token: str, request: dict, status: dict) -> None:
    with connection() as conn:
        conn.execute(
            "INSERT INTO api_jobs (task_id, token_hash, request, status) VALUES (?, ?, ?, ?)",
            (task_id, token_digest(token), json.dumps(request), json.dumps(status)),
        )


#: Valid attempt states, from the start to a terminal result (#944).
ATTEMPT_STATES: frozenset[str] = frozenset(
    {"started", "completed", "failed", "cancelled", "interrupted", "legacy"}
)

#: Valid result origins. ``unknown`` is evidence-free, never a guess (#944).
ATTEMPT_ORIGINS: frozenset[str] = frozenset(
    {"produced", "cache", "resumed", "unknown"}
)


def save_attempt_start(
    task_id: str, attempt: dict[str, Any], configuration: dict[str, Any]
) -> None:
    """Append an attempt and make it the job's current one (#944).

    The attempt row and the job's pointer are written in one transaction, so
    a reader cannot see a current pointer without its snapshot. A missing job
    rolls the insert back and raises: the caller must not believe a record it
    did not store is current.
    """
    attempt_id = str(attempt.get("id") or "")
    if not attempt_id:
        raise ValueError("an attempt needs an id")
    captured_at = str(attempt.get("captured_at") or datetime.now(UTC).isoformat())
    resumed = bool(attempt.get("resumed", False))
    encoded = json.dumps(configuration, ensure_ascii=False, sort_keys=True)
    with connection() as conn:
        conn.execute(
            "INSERT INTO job_attempts "
            "(task_id, attempt_id, captured_at, resumed, state, origin, "
            "configuration, reused_phases, error_type, created_at, finished_at) "
            "VALUES (?, ?, ?, ?, 'started', 'unknown', ?, '[]', NULL, ?, NULL)",
            (task_id, attempt_id, captured_at, int(resumed), encoded, time.time()),
        )
        updated = conn.execute(
            "UPDATE api_jobs SET configuration=?, current_attempt_id=? WHERE task_id=?",
            (encoded, attempt_id, task_id),
        ).rowcount
        if updated == 0:
            raise LookupError("no api_jobs row for the task")


def save_configuration(task_id: str, configuration: dict[str, Any]) -> None:
    """Compatibility wrapper: append a snapshot from a configuration record.

    New callers use :func:`save_attempt_start` with the attempt identity they
    already hold; this keeps older callers and tests working without losing
    the attempt history.
    """
    attempt = configuration.get("attempt") or {}
    if not isinstance(attempt, dict):
        attempt = {}
    save_attempt_start(
        task_id,
        {
            "id": attempt.get("id") or uuid.uuid4().hex,
            "captured_at": attempt.get("captured_at")
            or datetime.now(UTC).isoformat(),
            "resumed": bool(attempt.get("resumed", False)),
        },
        configuration,
    )


def save_attempt_marker(
    task_id: str, attempt_id: str, captured_at: str
) -> bool:
    """Write the current-attempt marker into the durable status (#944).

    A dedicated operation instead of ``save_status``: it detects a job row
    that does not exist or a terminal status that refuses the update, so the
    caller does not treat an ignored write as a persisted marker. Returns
    whether a row was updated.
    """
    with connection() as conn:
        updated = conn.execute(
            "UPDATE api_jobs SET status = json_set("
            "status, '$.current_attempt_id', ?, "
            "'$.current_attempt_captured_at', ?) "
            "WHERE task_id=? AND json_extract(status, '$.status') "
            "IN ('queued', 'processing')",
            (attempt_id, captured_at, task_id),
        ).rowcount
    return updated > 0


def reconcile_started_attempts(
    task_id: str, *, error_type: str = "process-restart"
) -> int:
    """Close attempts a dead process left ``started`` (#944).

    Called by the recovery of a job whose owner is provably gone. Terminal
    attempts are never touched, the configuration stays immutable and the
    origin stays ``unknown``. ``finished_at`` is the reconciliation time, not
    the crash time; ``error_type`` records that distinction.
    """
    with connection() as conn:
        return conn.execute(
            "UPDATE job_attempts SET state='interrupted', origin='unknown', "
            "error_type=?, finished_at=? "
            "WHERE task_id=? AND state='started'",
            (error_type, time.time(), task_id),
        ).rowcount


def save_attempt_result(
    task_id: str,
    attempt_id: str,
    *,
    state: str,
    origin: str,
    reused_phases: list[str] | None = None,
    error_type: str | None = None,
) -> None:
    """Fill an attempt's result once, without touching its configuration (#944).

    ``state`` and ``origin`` are validated; ``error_type`` is the exception
    class name, never its message, so no user content reaches the audit.
    """
    if state not in ATTEMPT_STATES or state in {"started", "legacy"}:
        raise ValueError(f"invalid terminal attempt state: {state!r}")
    if origin not in ATTEMPT_ORIGINS:
        raise ValueError(f"invalid attempt origin: {origin!r}")
    with connection() as conn:
        updated = conn.execute(
            "UPDATE job_attempts SET state=?, origin=?, reused_phases=?, "
            "error_type=?, finished_at=? "
            "WHERE task_id=? AND attempt_id=? AND state='started'",
            (
                state,
                origin,
                json.dumps(list(dict.fromkeys(reused_phases or [])), ensure_ascii=False),
                error_type,
                time.time(),
                task_id,
                attempt_id,
            ),
        ).rowcount
    if updated == 0:
        raise LookupError("no started attempt to finish")


def load_attempts(task_id: str) -> list[dict[str, Any]]:
    """Every attempt of the job, oldest first, with its result and snapshot."""
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM job_attempts WHERE task_id=? ORDER BY created_at, rowid",
            (task_id,),
        ).fetchall()
    return [_attempt_record(row) for row in rows]


def load_latest_attempt(task_id: str) -> dict[str, Any] | None:
    """The job's latest attempt, or None when it has none."""
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM job_attempts WHERE task_id=? "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (task_id,),
        ).fetchone()
    return _attempt_record(row) if row is not None else None


def _attempt_record(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "task_id": row["task_id"],
        "attempt_id": row["attempt_id"],
        "captured_at": row["captured_at"],
        "resumed": bool(row["resumed"]),
        "state": row["state"],
        "origin": row["origin"],
        "configuration": json.loads(row["configuration"]),
        "reused_phases": json.loads(row["reused_phases"]),
        "error_type": row["error_type"],
        "created_at": row["created_at"],
        "finished_at": row["finished_at"],
    }


def load_record(task_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM api_jobs WHERE task_id=?", (task_id,)
        ).fetchone()
    return _record_from_row(row) if row is not None else None


def load_audit_view(
    task_id: str,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """The job record and its attempts from one SQLite read snapshot (#946).

    The route reads the current pointer and the history together, so a new
    attempt persisted between two independent reads cannot produce a pointer
    from one state and a history from another. ``BEGIN`` makes both SELECTs
    share the read transaction; SQLite readers see a stable snapshot until it
    ends.
    """
    with connection() as conn:
        conn.execute("BEGIN")
        row = conn.execute(
            "SELECT * FROM api_jobs WHERE task_id=?", (task_id,)
        ).fetchone()
        attempts = conn.execute(
            "SELECT * FROM job_attempts WHERE task_id=? ORDER BY created_at, rowid",
            (task_id,),
        ).fetchall()
    if row is None:
        return None, []
    return _record_from_row(row), [_attempt_record(item) for item in attempts]


def _record_from_row(row: sqlite3.Row) -> dict[str, Any]:
    configuration = row["configuration"]
    return {
        "task_id": row["task_id"],
        "token_hash": row["token_hash"],
        "request": json.loads(row["request"]),
        "status": json.loads(row["status"]),
        "configuration": json.loads(configuration) if configuration else None,
        "current_attempt_id": row["current_attempt_id"],
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
    """Delete the job and every attempt snapshot it owns (#944 retention).

    There is no separate expiry for attempts: their lifecycle is the job
    record's. Deleting the job record removes the configurations with it.
    """
    with connection() as conn:
        conn.execute("DELETE FROM job_attempts WHERE task_id=?", (task_id,))
        conn.execute("DELETE FROM api_jobs WHERE task_id=?", (task_id,))
