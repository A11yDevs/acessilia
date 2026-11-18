"""Durable operation ids per job, so a repeated call keeps its identity (#407).

ADR-0019 defines the identifiers and makes the Toolbox join an
``operation_id`` it already knows. The in-memory registry in
:mod:`backend.services.operation_registry` is enough for one process; after a
core restart it is empty, and a repeated logical call would reach the Toolbox
under a new id and run the provider again. This journal remembers which id a
job used for a logical slot, so the same call after a restart names the same
operation.

The journal stores identity, never results: the Toolbox owns the operation
state and its result (ADR-0019). If it no longer retains an operation, the
repeat runs again under the same id — safe, because the core only names
capabilities the contract marks idempotent.

Rows are removed when the job ends (``forget``) and swept by the periodic
cleanup after ``EXPIRY_SECONDS`` if a job disappears without one. The decision
is recorded in ``docs/adr/0020-job-resumption-and-operation-journal.md``.
"""

from __future__ import annotations

import sqlite3
import time

from acessilia_core.logger import logger

from backend.config.settings import settings

#: A journal row is only useful while its job can still resume. After the
#: longest cache retention (7 days) it cannot be, so the sweep may drop it.
EXPIRY_SECONDS = 7 * 24 * 60 * 60


def _connection() -> sqlite3.Connection:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(settings.db_path, timeout=10)
    connection.execute(
        """CREATE TABLE IF NOT EXISTS operation_journal (
               task_id TEXT NOT NULL,
               slot TEXT NOT NULL,
               operation_id TEXT NOT NULL,
               state TEXT NOT NULL,
               updated_at REAL NOT NULL,
               PRIMARY KEY (task_id, slot)
           )"""
    )
    return connection


def operation_id(task_id: str, slot: str) -> str | None:
    """The id this job already used for ``slot``, or ``None``.

    A journal failure never fails the call: the operation simply starts under
    a fresh id, which is the pre-#407 behaviour.
    """
    try:
        with _connection() as connection:
            row = connection.execute(
                "SELECT operation_id FROM operation_journal WHERE task_id=? AND slot=?",
                (task_id, slot),
            ).fetchone()
    except sqlite3.Error as exc:
        logger.warning(
            "Operation journal unavailable for task {} slot {}: {}", task_id, slot, exc
        )
        return None
    return str(row[0]) if row is not None else None


def record(task_id: str, slot: str, operation_id: str, state: str = "started") -> None:
    """Remember the id of a logical call, replacing a previous id of the slot."""
    try:
        with _connection() as connection:
            connection.execute(
                """INSERT INTO operation_journal
                       (task_id, slot, operation_id, state, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(task_id, slot) DO UPDATE SET
                       operation_id=excluded.operation_id,
                       state=excluded.state,
                       updated_at=excluded.updated_at""",
                (task_id, slot, operation_id, state, time.time()),
            )
    except sqlite3.Error as exc:
        logger.warning(
            "Operation journal could not record task {} slot {}: {}", task_id, slot, exc
        )


def set_state(task_id: str, operation_id: str, state: str) -> None:
    """Update the state of an operation, matching it by id rather than slot."""
    try:
        with _connection() as connection:
            connection.execute(
                """UPDATE operation_journal SET state=?, updated_at=?
                   WHERE task_id=? AND operation_id=?""",
                (state, time.time(), task_id, operation_id),
            )
    except sqlite3.Error as exc:
        logger.warning(
            "Operation journal could not update task {} operation {}: {}",
            task_id,
            operation_id,
            exc,
        )


def forget(task_id: str) -> None:
    """Drop every row of a job that reached a terminal state."""
    try:
        with _connection() as connection:
            connection.execute(
                "DELETE FROM operation_journal WHERE task_id=?", (task_id,)
            )
    except sqlite3.Error as exc:
        logger.warning("Operation journal could not forget task {}: {}", task_id, exc)


def expire(max_age_seconds: float = EXPIRY_SECONDS, now: float | None = None) -> int:
    """Remove rows untouched for longer than ``max_age_seconds``; returns the count."""
    current = now if now is not None else time.time()
    try:
        with _connection() as connection:
            cursor = connection.execute(
                "DELETE FROM operation_journal WHERE updated_at < ?",
                (current - max_age_seconds,),
            )
            return max(0, cursor.rowcount)
    except sqlite3.Error as exc:
        logger.warning("Operation journal could not expire old rows: {}", exc)
        return 0


__all__ = [
    "EXPIRY_SECONDS",
    "expire",
    "forget",
    "operation_id",
    "record",
    "set_state",
]
