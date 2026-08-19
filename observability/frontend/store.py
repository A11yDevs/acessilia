from __future__ import annotations

import sqlite3
from pathlib import Path


DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "observability.db"


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS annotations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_type TEXT NOT NULL,
                target_id TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'note',
                note TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_annotations_target
            ON annotations(target_type, target_id)
            """
        )
        conn.commit()


def list_annotations(
    db_path: Path = DEFAULT_DB_PATH,
    limit: int = 100,
) -> list[dict]:
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, target_type, target_id, severity, note, tags, created_at
            FROM annotations
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def create_annotation(
    target_type: str,
    target_id: str,
    note: str,
    tags: str = "",
    severity: str = "note",
    db_path: Path = DEFAULT_DB_PATH,
) -> dict:
    init_db(db_path)
    cleaned_note = note.strip()
    if not cleaned_note:
        raise ValueError("A anotação não pode ficar vazia.")

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """
            INSERT INTO annotations(target_type, target_id, severity, note, tags)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                target_type.strip() or "geral",
                target_id.strip() or "observability",
                severity.strip() or "note",
                cleaned_note,
                tags.strip(),
            ),
        )
        conn.commit()
        row = conn.execute(
            """
            SELECT id, target_type, target_id, severity, note, tags, created_at
            FROM annotations
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()
        return dict(row)


def delete_annotation(
    annotation_id: int,
    db_path: Path = DEFAULT_DB_PATH,
) -> bool:
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "DELETE FROM annotations WHERE id = ?",
            (annotation_id,),
        )
        conn.commit()
        return cursor.rowcount > 0
