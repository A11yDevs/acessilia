"""Offline, standard-library-only migration of unexpired 0.1.0 download assets.

Run without --apply to inspect; --verify audits a published migration before
application startup. The source is read-only and the destination must not exist.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import sys
import tempfile
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path


MIGRATION_ID = "core-0.1.0-to-0.2.0"
RETENTION_DAYS = 7
TABLES = ("download_tokens", "conversoes", "ocr_raw", "ocr_revised", "ocr_translated")
# Frozen output names shared by both versions, including the legacy plain PDF.
SUFFIXES = {
    "txt": ".txt", "docx": ".docx", "pdf": ".pdf",
    "pdf_ua": ".pdf_ua.pdf", "html": ".html", "mp3": ".mp3",
    "zip": "_acessivel.zip",
}
MANIFEST = "migration-0.1.0-to-0.2.0.json"
SCHEMA = Path(__file__).with_suffix(".sql")


class MigrationError(ValueError):
    """An incomplete or unsupported dataset must not be published."""


def timestamp(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise MigrationError("Invalid timestamp; repair the source before migrating.") from exc
    return result.replace(tzinfo=result.tzinfo or timezone.utc).astimezone(timezone.utc)


def sql_timestamp(value: datetime) -> str:
    # SQLite's download expiry compares UTC strings to datetime('now', '-7 days').
    return value.astimezone(timezone.utc).isoformat(sep=" ").replace("+00:00", "")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _regular_file(root: Path, relative: Path) -> Path:
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise MigrationError("An asset path escapes its storage root.")
    path = root
    for component in relative.parts:
        path = path / component
        if path.is_symlink():
            raise MigrationError("A retained asset uses a symlink; migration refused.")
    if not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
        raise MigrationError("A retained asset is missing or is not a regular file.")
    return path


def _output_relative(value: str, source: Path, runtime_root: Path) -> Path:
    try:
        stored = Path(value)
    except TypeError as exc:
        raise MigrationError("Invalid download output directory.") from exc
    if ".." in stored.parts:
        raise MigrationError("A download output directory contains parent traversal.")
    if not stored.is_absolute():
        stored = runtime_root.parent / stored
    for prefix in (runtime_root, source):
        if stored.is_relative_to(prefix):
            relative = stored.relative_to(prefix)
            if (
                len(relative.parts) >= 3 and relative.parts[:2] == ("data", "output")
                or len(relative.parts) >= 2 and relative.parts[0] == "temp"
            ):
                return relative
    raise MigrationError("A retained output is outside var/data/output or var/temp; supply the correct runtime root.")


def _database_signature(path: Path) -> tuple:
    result = []
    for candidate in (path, Path(str(path) + "-wal")):
        if candidate.is_symlink():
            raise MigrationError("The source database or WAL is a symlink.")
        info = candidate.stat() if candidate.exists() else None
        result.append((info.st_ino, info.st_size, info.st_mtime_ns) if info else None)
    return tuple(result)


def _snapshot(path: Path) -> sqlite3.Connection:
    snapshot = sqlite3.connect(":memory:")
    snapshot.row_factory = sqlite3.Row
    try:
        deadline = time.monotonic() + 30

        def progress(_status: int, _remaining: int, _total: int) -> None:
            if time.monotonic() > deadline:
                raise MigrationError("Timed out reading the database; stop writers and retry.")

        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)) as source:
            source.backup(snapshot, pages=256, progress=progress)
        if snapshot.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise MigrationError("The source database failed its integrity check.")
        return snapshot
    except BaseException:
        snapshot.close()
        raise


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]


def _read_tables(snapshot: sqlite3.Connection) -> dict[str, list[dict]]:
    present = {
        row[0] for row in snapshot.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if not row[0].startswith("sqlite_")
    }
    if "download_tokens" not in present or present - set(TABLES):
        raise MigrationError("Unsupported source schema; expected the 0.1.0 core tables only.")
    tables = {}
    with closing(sqlite3.connect(":memory:")) as target:
        target.executescript(SCHEMA.read_text(encoding="utf-8"))
        for table in TABLES:
            if table not in present:
                tables[table] = []
                continue
            columns = set(_columns(snapshot, table))
            expected = set(_columns(target, table))
            optional = {"formats", "task_id", "owner"} if table == "download_tokens" else set()
            if columns - expected or expected - columns - optional:
                raise MigrationError(f"Unsupported columns in {table}; a versioned adapter is required.")
            tables[table] = [dict(row) for row in snapshot.execute(f'SELECT * FROM "{table}"')]
    return tables


def _select(tables: dict, source: Path, source_runtime: Path, destination_runtime: Path,
            now: datetime) -> tuple[dict, dict]:
    cutoff = now - timedelta(days=RETENTION_DAYS)
    selected = {table: [] for table in TABLES}
    files = {}
    for number, token in enumerate(tables["download_tokens"], 1):
        created = timestamp(token["criado_em"])
        if created > now:
            raise MigrationError("A download timestamp is in the future; check the source clock.")
        if created < cutoff:
            continue
        if not isinstance(token["token"], str) or not token["token"]:
            raise MigrationError("A retained download has no token.")
        base = token["filename"]
        if not isinstance(base, str) or base in {"", ".", ".."} or any(c in base for c in ("/", "\\", "\0")):
            raise MigrationError("A retained filename is unsafe.")
        try:
            formats = json.loads(token.get("formats") or "[]")
        except (ValueError, TypeError) as exc:
            raise MigrationError("A retained download has invalid formats JSON.") from exc
        if not isinstance(formats, list) or any(not isinstance(f, str) or f not in SUFFIXES for f in formats):
            raise MigrationError("A retained download has unsupported formats.")
        relative = _output_relative(token["output_dir"], source, source_runtime)
        found = 0
        for extension in formats or SUFFIXES:
            file_relative = relative / (base + SUFFIXES[extension])
            file_path = source / file_relative
            if not formats and not os.path.lexists(file_path):
                continue
            try:
                file_path = _regular_file(source, file_relative)
            except MigrationError as exc:
                raise MigrationError(f"Retained download #{number}: {exc}") from exc
            files[str(file_relative)] = {"sha256": digest(file_path), "bytes": file_path.stat().st_size}
            found += 1
        if not found:
            raise MigrationError(f"Retained download #{number} has no downloadable files.")
        selected["download_tokens"].append({
            **token,
            "output_dir": str(destination_runtime / relative),
            "criado_em": sql_timestamp(created),
            "formats": token.get("formats") or "[]",
            "task_id": token.get("task_id") or "",
            "owner": token.get("owner") or "",
        })
    referenced = {row["task_id"] for row in selected["download_tokens"] if row["task_id"]}
    for row in tables["conversoes"]:
        created = timestamp(row["criado_em"])
        if created > now:
            raise MigrationError("A history timestamp is in the future; check the source clock.")
        if created >= cutoff or row["task_id"] in referenced:
            if row["status"] not in {"done", "error", "cancelled"}:
                raise MigrationError("History has nonterminal jobs to migrate; drain processing before applying.")
            selected["conversoes"].append(row)
    task_ids = referenced | {row["task_id"] for row in selected["conversoes"]}
    for table in TABLES[2:]:
        selected[table] = [row for row in tables[table] if row["task_id"] in task_ids]
    return selected, files


def _write_database(path: Path, selected: dict, now: datetime) -> None:
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        for table, rows in selected.items():
            columns = _columns(conn, table)
            placeholders = ", ".join("?" for _ in columns)
            conn.executemany(
                f'INSERT INTO "{table}" ({", ".join(columns)}) VALUES ({placeholders})',
                [[row[column] for column in columns] for row in rows],
            )
        conn.execute("INSERT INTO schema_migrations VALUES (?, ?, ?)", (
            MIGRATION_ID, sql_timestamp(now), sql_timestamp(now - timedelta(days=RETENTION_DAYS)),
        ))
        conn.commit()
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise MigrationError("The migrated database failed its integrity check.")
    path.chmod(0o600)


def migrate(source_var: Path, destination_var: Path, *, apply: bool = False,
            at: datetime | None = None, source_runtime_var: Path = Path("/app/var"),
            destination_runtime_var: Path = Path("/app/var")) -> dict:
    """Build a new dataset; never modify, delete or overwrite the source."""
    now = at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise MigrationError("The migration reference time must include a timezone.")
    now = now.astimezone(timezone.utc)
    source = source_var.resolve(strict=True)
    destination = destination_var.absolute()
    if not source.is_dir():
        raise MigrationError("The source var directory does not exist.")
    for runtime in (source_runtime_var, destination_runtime_var):
        if not runtime.is_absolute() or ".." in runtime.parts:
            raise MigrationError("Runtime storage roots must be absolute without parent traversal.")
    resolved_destination = destination.resolve()
    if resolved_destination.is_relative_to(source) or source.is_relative_to(resolved_destination):
        raise MigrationError("Source and destination storage must not overlap.")
    if os.path.lexists(destination):
        raise MigrationError("Destination already exists; it will never be overwritten.")
    database = _regular_file(source, Path("data/history.db"))
    signature = _database_signature(database)
    with closing(_snapshot(database)) as snapshot:
        tables = _read_tables(snapshot)
    selected, files = _select(tables, source, source_runtime_var, destination_runtime_var, now)
    if _database_signature(database) != signature:
        raise MigrationError("The source database changed; stop the application and retry.")
    summary = {
        "migration_id": MIGRATION_ID,
        "mode": "apply" if apply else "dry-run",
        "as_of_utc": sql_timestamp(now),
        "retention_days": RETENTION_DAYS,
        "cutoff_utc": sql_timestamp(now - timedelta(days=RETENTION_DAYS)),
        "rows": {table: {"retained": len(selected[table]), "excluded": len(tables[table]) - len(selected[table])}
                 for table in TABLES},
        "files_to_copy": len(files),
        "file_bytes_to_copy": sum(item["bytes"] for item in files.values()),
    }
    if not apply:
        return summary
    if not destination.parent.is_dir():
        raise MigrationError("Create the destination parent directory before applying.")
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.migration-", dir=destination.parent))
    try:
        for directory in ("data", "data/output", "temp", "logs"):
            (staging / directory).mkdir(parents=True, exist_ok=True)
        for relative, expected in files.items():
            source_file = _regular_file(source, Path(relative))
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target)
            target.chmod(0o600)
            if digest(target) != expected["sha256"] or digest(source_file) != expected["sha256"]:
                raise MigrationError("A retained asset changed during migration; stop writers and retry.")
        if _database_signature(database) != signature:
            raise MigrationError("The source database changed; stop the application and retry.")
        _write_database(staging / "data/history.db", selected, now)
        manifest = {
            "summary": summary,
            "runtime_var": str(destination_runtime_var),
            "database_sha256": digest(staging / "data/history.db"),
            "files": files,
        }
        manifest_path = staging / MANIFEST
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        manifest_path.chmod(0o600)
        for directory, _, _ in os.walk(staging):
            Path(directory).chmod(0o700)
        if os.path.lexists(destination):
            raise MigrationError("Destination appeared during migration; it will not be overwritten.")
        staging.rename(destination)
    except BaseException:
        shutil.rmtree(staging)
        raise
    return summary


def verify(destination_var: Path) -> dict:
    """Audit checksums and the migration receipt before the application starts."""
    destination = destination_var.resolve(strict=True)
    manifest_path = _regular_file(destination, Path(MANIFEST))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    summary = manifest["summary"]
    if summary["migration_id"] != MIGRATION_ID:
        raise MigrationError("The manifest belongs to a different migration.")
    for relative, expected in {**manifest["files"], "data/history.db": {"sha256": manifest["database_sha256"]}}.items():
        if digest(_regular_file(destination, Path(relative))) != expected["sha256"]:
            raise MigrationError("A migrated file failed its checksum verification.")
    with closing(sqlite3.connect((destination / "data/history.db").as_uri() + "?mode=ro", uri=True)) as conn:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise MigrationError("The migrated database failed its integrity check.")
        if conn.execute("SELECT migration_id FROM schema_migrations").fetchall() != [(MIGRATION_ID,)]:
            raise MigrationError("The database has no matching migration receipt.")
    return {**summary, "mode": "verify", "verified": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-var", type=Path)
    parser.add_argument("--destination-var", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Publish to a new directory; source must be offline.")
    mode.add_argument("--dry-run", action="store_true", help="Default: inspect without creating the destination.")
    mode.add_argument("--verify", action="store_true", help="Verify a migrated destination before application startup.")
    parser.add_argument("--source-runtime-var", type=Path, default=Path("/app/var"))
    parser.add_argument("--destination-runtime-var", type=Path, default=Path("/app/var"))
    args = parser.parse_args(argv)
    if not args.verify and args.source_var is None:
        parser.error("--source-var is required unless --verify is used")
    try:
        result = verify(args.destination_var) if args.verify else migrate(
            args.source_var, args.destination_var, apply=args.apply,
            source_runtime_var=args.source_runtime_var,
            destination_runtime_var=args.destination_runtime_var,
        )
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError) as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
