from __future__ import annotations

import json
import math
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from observability.src.events import sanitize_agno_event_for_console

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "observability.db"


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

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agno_sessions (
                session_id TEXT PRIMARY KEY,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                model_provider TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_agno_sessions_entity
            ON agno_sessions(entity_type, entity_id, updated_at DESC)
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agno_runs (
                run_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                model TEXT NOT NULL DEFAULT '',
                model_provider TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'completed',
                duration_seconds REAL DEFAULT 0.0,
                ttft_seconds REAL DEFAULT NULL,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                reasoning_tokens INTEGER DEFAULT 0,
                cache_read_tokens INTEGER DEFAULT 0,
                cache_write_tokens INTEGER DEFAULT 0,
                cost REAL DEFAULT NULL,
                error_type TEXT DEFAULT '',
                error TEXT DEFAULT '',
                trace_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        _ensure_column(conn, "agno_runs", "trace_id", "TEXT NOT NULL DEFAULT ''")
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_agno_runs_session
            ON agno_runs(session_id, created_at ASC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_agno_runs_entity
            ON agno_runs(entity_type, entity_id, created_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_agno_runs_trace
            ON agno_runs(trace_id)
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agno_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                run_id TEXT DEFAULT '',
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_agno_messages_session
            ON agno_messages(session_id, id ASC)
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agno_run_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                event_name TEXT NOT NULL,
                event_data_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_agno_events_run
            ON agno_run_events(run_id, id ASC)
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agno_tool_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                tool_args_json TEXT NOT NULL DEFAULT '{}',
                tool_result_json TEXT DEFAULT NULL,
                status TEXT NOT NULL DEFAULT 'completed',
                error TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_agno_tool_calls_run
            ON agno_tool_calls(run_id, id ASC)
            """
        )
        conn.commit()


def _ensure_column(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


# --- ANNOTATIONS ---

def list_annotations(
    db_path: Path = DEFAULT_DB_PATH,
    limit: int = 100,
) -> list[dict[str, Any]]:
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
) -> dict[str, Any]:
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


# --- AGNO SESSIONS & RUNS ---

def upsert_agno_session(
    session_id: str,
    entity_type: str,
    entity_id: str,
    name: str = "",
    model: str = "",
    model_provider: str = "",
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    init_db(db_path)
    now = datetime.now(timezone.utc).isoformat()
    session_name = name.strip() or f"{entity_id} ({datetime.now().strftime('%d/%m %H:%M')})"
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            INSERT INTO agno_sessions(session_id, entity_type, entity_id, name, model, model_provider, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                entity_type = excluded.entity_type,
                entity_id = excluded.entity_id,
                model = CASE WHEN excluded.model != '' THEN excluded.model ELSE agno_sessions.model END,
                model_provider = CASE WHEN excluded.model_provider != '' THEN excluded.model_provider ELSE agno_sessions.model_provider END,
                updated_at = excluded.updated_at
            """,
            (
                session_id,
                entity_type,
                entity_id,
                session_name,
                model,
                model_provider,
                now,
                now,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM agno_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return dict(row)


def list_agno_sessions(
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = 50,
    db_path: Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        query = """
            SELECT s.*,
                   COUNT(DISTINCT m.id) as message_count,
                   COUNT(DISTINCT r.run_id) as run_count
            FROM agno_sessions s
            LEFT JOIN agno_messages m ON m.session_id = s.session_id
            LEFT JOIN agno_runs r ON r.session_id = s.session_id
        """
        params: list[Any] = []
        where_clauses = []
        if entity_type:
            where_clauses.append("s.entity_type = ?")
            params.append(entity_type)
        if entity_id:
            where_clauses.append("s.entity_id = ?")
            params.append(entity_id)
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
        query += " GROUP BY s.session_id ORDER BY s.updated_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def get_agno_session(
    session_id: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM agno_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return dict(row) if row else None


def delete_agno_session(
    session_id: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> bool:
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM agno_messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM agno_run_events WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM agno_tool_calls WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM agno_runs WHERE session_id = ?", (session_id,))
        cursor = conn.execute("DELETE FROM agno_sessions WHERE session_id = ?", (session_id,))
        conn.commit()
        return cursor.rowcount > 0


def create_agno_run(
    run_id: str,
    session_id: str,
    entity_type: str,
    entity_id: str,
    model: str = "",
    model_provider: str = "",
    status: str = "completed",
    duration_seconds: float = 0.0,
    ttft_seconds: float | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int = 0,
    reasoning_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    cost: float | None = None,
    error_type: str = "",
    error: str = "",
    trace_id: str = "",
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    init_db(db_path)
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            INSERT OR REPLACE INTO agno_runs(
                run_id, session_id, entity_type, entity_id, model, model_provider,
                status, duration_seconds, ttft_seconds, input_tokens, output_tokens,
                total_tokens, reasoning_tokens, cache_read_tokens, cache_write_tokens,
                cost, error_type, error, trace_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                session_id,
                entity_type,
                entity_id,
                model,
                model_provider,
                status,
                max(float(duration_seconds), 0.0),
                float(ttft_seconds) if ttft_seconds is not None else None,
                int(input_tokens or 0),
                int(output_tokens or 0),
                int(total_tokens or (input_tokens + output_tokens)),
                int(reasoning_tokens or 0),
                int(cache_read_tokens or 0),
                int(cache_write_tokens or 0),
                float(cost) if cost is not None else None,
                error_type,
                error,
                trace_id,
                now,
            ),
        )
        conn.execute(
            "UPDATE agno_sessions SET updated_at = ? WHERE session_id = ?",
            (now, session_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM agno_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return dict(row)


def create_agno_message(
    session_id: str,
    role: str,
    content: str,
    run_id: str = "",
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    init_db(db_path)
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """
            INSERT INTO agno_messages(session_id, run_id, role, content, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, run_id, role, content, now),
        )
        conn.execute(
            "UPDATE agno_sessions SET updated_at = ? WHERE session_id = ?",
            (now, session_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM agno_messages WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        return dict(row)


def create_agno_run_event(
    run_id: str,
    session_id: str,
    event_name: str,
    event_data: dict[str, Any] | str = "",
    db_path: Path = DEFAULT_DB_PATH,
    store_full_reasoning: bool | None = None,
) -> dict[str, Any]:
    init_db(db_path)
    if store_full_reasoning is None:
        store_full_reasoning = (
            os.getenv("AGNO_CONSOLE_STORE_REASONING", "false").lower() == "true"
        )

    if isinstance(event_data, dict):
        cleaned_data = dict(event_data)
        had_event_key = "event" in cleaned_data
        event_payload = cleaned_data if had_event_key else {"event": event_name, **cleaned_data}
        safe_data = sanitize_agno_event_for_console(
            event_payload,
            store_full_reasoning=store_full_reasoning,
        )
        if not had_event_key:
            safe_data.pop("event", None)
        raw_json = json.dumps(safe_data, ensure_ascii=False)
    else:
        raw_json = str(event_data)

    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """
            INSERT INTO agno_run_events(run_id, session_id, event_name, event_data_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, session_id, event_name, raw_json, now),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM agno_run_events WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        return dict(row)


def create_agno_tool_call(
    run_id: str,
    session_id: str,
    tool_name: str,
    tool_args: dict[str, Any] | str = "",
    tool_result: dict[str, Any] | str | None = None,
    status: str = "completed",
    error: str = "",
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    init_db(db_path)
    args_json = json.dumps(tool_args, ensure_ascii=False) if isinstance(tool_args, (dict, list)) else str(tool_args)
    result_json = (
        json.dumps(tool_result, ensure_ascii=False)
        if isinstance(tool_result, (dict, list))
        else (str(tool_result) if tool_result is not None else None)
    )
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """
            INSERT INTO agno_tool_calls(run_id, session_id, tool_name, tool_args_json, tool_result_json, status, error, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, session_id, tool_name, args_json, result_json, status, error, now),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM agno_tool_calls WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        return dict(row)


def get_agno_session_details(
    session_id: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    session = get_agno_session(session_id, db_path)
    if not session:
        return None

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        messages = [
            dict(m)
            for m in conn.execute(
                "SELECT * FROM agno_messages WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
        ]
        runs = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM agno_runs WHERE session_id = ? ORDER BY created_at ASC",
                (session_id,),
            ).fetchall()
        ]
        events = [
            dict(e)
            for e in conn.execute(
                "SELECT * FROM agno_run_events WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
        ]
        tool_calls = [
            dict(t)
            for t in conn.execute(
                "SELECT * FROM agno_tool_calls WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
        ]

    runs_by_id = {r["run_id"]: r for r in runs}
    events_by_run: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        events_by_run.setdefault(ev["run_id"], []).append(ev)

    tools_by_run: dict[str, list[dict[str, Any]]] = {}
    for tc in tool_calls:
        tools_by_run.setdefault(tc["run_id"], []).append(tc)

    return {
        "session": session,
        "messages": messages,
        "runs": runs,
        "runs_by_id": runs_by_id,
        "events_by_run": events_by_run,
        "tools_by_run": tools_by_run,
    }


def list_agno_runs(
    *,
    status: str = "",
    search: str = "",
    limit: int = 100,
    db_path: Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    init_db(db_path)
    query = """
        SELECT
            r.*,
            s.name AS session_name,
            (SELECT COUNT(*) FROM agno_run_events e WHERE e.run_id = r.run_id)
                AS event_count,
            (SELECT COUNT(*) FROM agno_tool_calls t WHERE t.run_id = r.run_id)
                AS tool_count
        FROM agno_runs r
        LEFT JOIN agno_sessions s ON s.session_id = r.session_id
        WHERE 1 = 1
    """
    params: list[Any] = []
    if status:
        query += " AND r.status = ?"
        params.append(status)
    cleaned_search = search.strip()
    if cleaned_search:
        query += """
            AND (
                r.trace_id LIKE ? OR r.run_id LIKE ? OR r.session_id LIKE ?
                OR r.entity_id LIKE ? OR r.model LIKE ?
            )
        """
        pattern = f"%{cleaned_search}%"
        params.extend([pattern] * 5)
    query += " ORDER BY r.created_at DESC LIMIT ?"
    params.append(min(max(int(limit), 1), 500))

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def get_agno_run_details(
    run_id: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        run = conn.execute(
            "SELECT * FROM agno_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if not run:
            return None
        session = conn.execute(
            "SELECT * FROM agno_sessions WHERE session_id = ?",
            (run["session_id"],),
        ).fetchone()
        messages = conn.execute(
            "SELECT * FROM agno_messages WHERE run_id = ? ORDER BY id ASC",
            (run_id,),
        ).fetchall()
        events = conn.execute(
            "SELECT * FROM agno_run_events WHERE run_id = ? ORDER BY id ASC",
            (run_id,),
        ).fetchall()
        tools = conn.execute(
            "SELECT * FROM agno_tool_calls WHERE run_id = ? ORDER BY id ASC",
            (run_id,),
        ).fetchall()

    normalized_events = []
    for event in events:
        item = dict(event)
        item["event_data"] = _json_or_text(item.pop("event_data_json", ""))
        normalized_events.append(item)

    normalized_tools = []
    for tool in tools:
        item = dict(tool)
        item["tool_args"] = _json_or_text(item.pop("tool_args_json", ""))
        item["tool_result"] = _json_or_text(item.pop("tool_result_json", ""))
        normalized_tools.append(item)

    return {
        "run": dict(run),
        "session": dict(session) if session else None,
        "messages": [dict(message) for message in messages],
        "events": normalized_events,
        "tools": normalized_tools,
    }


def _json_or_text(value: Any) -> Any:
    if value in (None, ""):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return str(value)


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return round(sorted_vals[int(k)], 3)
    d0 = sorted_vals[int(f)] * (c - k)
    d1 = sorted_vals[int(c)] * (k - f)
    return round(d0 + d1, 3)


def get_agent_metrics_summary(
    entity_type: str,
    entity_id: str,
    days: int = 30,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = [
            dict(r)
            for r in conn.execute(
                """
                SELECT * FROM agno_runs
                WHERE entity_type = ? AND entity_id = ?
                  AND datetime(created_at) >= datetime('now', '-' || ? || ' days')
                ORDER BY created_at DESC
                """,
                (entity_type, entity_id, days),
            ).fetchall()
        ]

    total_runs = len(rows)
    if total_runs == 0:
        return {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "total_runs": 0,
            "successful_runs": 0,
            "failed_runs": 0,
            "error_rate": 0.0,
            "avg_duration": None,
            "p50_duration": None,
            "p95_duration": None,
            "avg_ttft": None,
            "p50_ttft": None,
            "p95_ttft": None,
            "total_tokens": 0,
            "avg_tokens": 0,
            "input_tokens_total": 0,
            "output_tokens_total": 0,
            "reasoning_tokens_total": 0,
            "total_cost": None,
            "recent_runs": [],
        }

    durations = [r["duration_seconds"] for r in rows if r["duration_seconds"] is not None and r["duration_seconds"] > 0]
    ttfts = [r["ttft_seconds"] for r in rows if r["ttft_seconds"] is not None and r["ttft_seconds"] > 0]
    costs = [r["cost"] for r in rows if r["cost"] is not None]

    failed_runs = sum(1 for r in rows if r["status"] == "error")
    successful_runs = total_runs - failed_runs
    error_rate = round((failed_runs / total_runs) * 100, 1)

    avg_duration = round(sum(durations) / len(durations), 3) if durations else None
    avg_ttft = round(sum(ttfts) / len(ttfts), 3) if ttfts else None
    total_cost = round(sum(costs), 6) if costs else None

    input_tokens = sum(r["input_tokens"] or 0 for r in rows)
    output_tokens = sum(r["output_tokens"] or 0 for r in rows)
    reasoning_tokens = sum(r["reasoning_tokens"] or 0 for r in rows)
    total_tokens = sum(r["total_tokens"] or 0 for r in rows)

    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "total_runs": total_runs,
        "successful_runs": successful_runs,
        "failed_runs": failed_runs,
        "error_rate": error_rate,
        "avg_duration": avg_duration,
        "p50_duration": _percentile(durations, 0.5),
        "p95_duration": _percentile(durations, 0.95),
        "avg_ttft": avg_ttft,
        "p50_ttft": _percentile(ttfts, 0.5),
        "p95_ttft": _percentile(ttfts, 0.95),
        "total_tokens": total_tokens,
        "avg_tokens": round(total_tokens / total_runs, 1),
        "input_tokens_total": input_tokens,
        "output_tokens_total": output_tokens,
        "reasoning_tokens_total": reasoning_tokens,
        "total_cost": total_cost,
        "recent_runs": rows[:15],
    }


def get_comparative_metrics(
    group_by: str = "agent",
    days: int = 30,
    db_path: Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        group_col = "entity_id" if group_by == "agent" else "model"
        rows = conn.execute(
            f"""
            SELECT
                {group_col} as group_key,
                entity_type,
                model,
                model_provider,
                COUNT(*) as total_calls,
                SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as error_calls,
                AVG(duration_seconds) as avg_duration,
                AVG(ttft_seconds) as avg_ttft,
                AVG(total_tokens) as avg_tokens,
                SUM(total_tokens) as total_tokens,
                SUM(cost) as total_cost,
                COUNT(cost) as cost_count
            FROM agno_runs
            WHERE datetime(created_at) >= datetime('now', '-' || ? || ' days')
              AND {group_col} != ''
            GROUP BY {group_col}
            ORDER BY total_calls DESC
            """,
            (days,),
        ).fetchall()

        results: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            total = d["total_calls"] or 0
            errs = d["error_calls"] or 0
            d["error_rate"] = round((errs / total) * 100, 1) if total else 0.0
            d["success_rate"] = round(100 - d["error_rate"], 1)
            d["avg_duration"] = round(d["avg_duration"], 3) if d["avg_duration"] is not None else None
            d["avg_ttft"] = round(d["avg_ttft"], 3) if d["avg_ttft"] is not None else None
            d["avg_tokens"] = round(d["avg_tokens"], 1) if d["avg_tokens"] is not None else 0
            d["total_cost"] = round(d["total_cost"], 6) if d["cost_count"] and d["total_cost"] is not None else None
            results.append(d)
        return results
