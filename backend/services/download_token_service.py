from backend.services.blocking import offload
from contextlib import contextmanager
import json
import sqlite3
import uuid
import threading
import shutil
from pathlib import Path

from backend.i18n import t
from backend.log_messages import (
    LOG_DOWNLOAD_TOKEN_CREATED,
    LOG_DOWNLOAD_TOKEN_DIR_MISSING,
    LOG_DOWNLOAD_TOKEN_NOT_FOUND,
    LOG_OUTPUT_DIR_REMOVED,
)
from backend.tools.logger import logger
from backend.config.settings import settings

# Database connection configuration
_connection = None
_connection_lock = threading.Lock()

TOKEN_EXPIRY_DAYS = 7

FORMAT_EXTENSIONS = {
    "txt": "texto",
    "docx": "word",
    # Only PDF/UA is produced now; "pdf" lists the files of jobs made before
    # that, whose links stay valid for TOKEN_EXPIRY_DAYS.
    "pdf": "pdf",
    "pdf_ua": "pdf/ua",
    "html": "html",
    "mp3": "audio",
    "zip": "completo",
}

FORMAT_OUTPUT_SUFFIX = {
    "pdf_ua": "pdf_ua.pdf",
    "zip": "_acessivel.zip",
}


def _get_connection():
    global _connection
    if _connection is None:
        db_path = settings.db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _connection = sqlite3.connect(str(db_path), check_same_thread=False)
        _connection.row_factory = sqlite3.Row
        cursor = _connection.cursor()
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS download_tokens (
                    token TEXT PRIMARY KEY,
                    output_dir TEXT NOT NULL DEFAULT '',
                    filename TEXT NOT NULL DEFAULT '',
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    formats TEXT NULL DEFAULT '[]',
                    task_id TEXT NULL DEFAULT '',
                    owner TEXT NULL DEFAULT ''
                )
            """)
            cursor.execute("PRAGMA table_info(download_tokens)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'formats' not in columns:
                cursor.execute("ALTER TABLE download_tokens ADD COLUMN formats TEXT NULL DEFAULT '[]'")
            if 'task_id' not in columns:
                cursor.execute("ALTER TABLE download_tokens ADD COLUMN task_id TEXT NULL DEFAULT ''")
            if 'owner' not in columns:
                cursor.execute("ALTER TABLE download_tokens ADD COLUMN owner TEXT NULL DEFAULT ''")
            try:
                cursor.execute("CREATE INDEX idx_download_tokens_token ON download_tokens(token)")
            except sqlite3.OperationalError as e:
                if "already exists" not in str(e).lower():
                    raise
            _connection.commit()
        finally:
            cursor.close()
    return _connection


@offload
def criar_token(
    output_dir: Path,
    filename: str,
    formats: list = None,
    task_id: str = "",
    owner: str = "",
) -> str:
    token = str(uuid.uuid4())
    formats_json = json.dumps(formats) if formats else '[]'
    with _connection_lock:
        conn = _get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO download_tokens (token, output_dir, filename, formats, task_id, owner) VALUES (?, ?, ?, ?, ?, ?)",
                (token, str(output_dir), filename, formats_json, task_id, owner)
            )
            conn.commit()
        finally:
            cursor.close()
    logger.debug(t(LOG_DOWNLOAD_TOKEN_CREATED).format(filename=filename))
    return token


@offload
def obter_info_token(token: str) -> dict | None:
    with _connection_lock:
        conn = _get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """SELECT output_dir, filename, formats, criado_em, task_id, owner
                   FROM download_tokens
                   WHERE token = ?
                     AND criado_em >= datetime('now', ?)""",
                (token, f"-{TOKEN_EXPIRY_DAYS} days")
            )
            row = cursor.fetchone()
        finally:
            cursor.close()
    if row is None:
        logger.warning(t(LOG_DOWNLOAD_TOKEN_NOT_FOUND))
        return None
    output_dir = Path(row["output_dir"])
    if not output_dir.exists():
        logger.warning(
            t(LOG_DOWNLOAD_TOKEN_DIR_MISSING).format(output_dir=output_dir)
        )
        return None
    formats_list = json.loads(row["formats"]) if row["formats"] else []
    allowed_formats = set(formats_list) if isinstance(formats_list, list) else set()
    base = str(row["filename"])
    formats = []
    for ext, label in FORMAT_EXTENSIONS.items():
        if allowed_formats and ext not in allowed_formats:
            continue
        suffix = FORMAT_OUTPUT_SUFFIX.get(ext, ext)
        separator = "" if suffix.startswith("_") else "."
        file_path = output_dir / f"{base}{separator}{suffix}"
        if file_path.exists():
            size_bytes = file_path.stat().st_size
            # Choose the unit before rounding: 1 MB minus one byte remains
            # in the KB range and rounds to "1024 KB".
            if size_bytes < 1024:
                size_str = f"{size_bytes} B"
            elif size_bytes < 1024 * 1024:
                size_str = f"{size_bytes / 1024:.0f} KB"
            else:
                size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
            formats.append({
                "ext": ext,
                "label": label,
                "file_path": str(file_path),
                "size": size_str,
                "url": f"/download/{token}/{ext}",
            })
    return {
        "filename": row["filename"],
        "stem": base,
        "output_dir": str(output_dir),
        "criado_em": row["criado_em"],
        "task_id": row["task_id"] if "task_id" in row.keys() else "",
        "owner": row["owner"] if "owner" in row.keys() else "",
        "formats": formats,
    }


@offload
def limpar_tokens_expirados(dias: int = TOKEN_EXPIRY_DAYS):
    with _connection_lock:
        conn = _get_connection()
        cursor = conn.cursor()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cutoff = f"-{dias} days"
            cursor.execute(
                "SELECT DISTINCT output_dir FROM download_tokens WHERE criado_em < datetime('now', ?)",
                (cutoff,),
            )
            expired_dirs = [Path(row["output_dir"]) for row in cursor.fetchall()]
            cursor.execute(
                "SELECT DISTINCT output_dir FROM download_tokens WHERE criado_em >= datetime('now', ?)",
                (cutoff,),
            )
            active_dirs = {Path(row["output_dir"]).resolve() for row in cursor.fetchall()}
            for output_dir in expired_dirs:
                _remove_unreferenced_output_directory(output_dir, active_dirs)
            cursor.execute(
                "DELETE FROM download_tokens WHERE criado_em < datetime('now', ?)",
                (cutoff,),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()


def _remove_unreferenced_output_directory(output_dir: Path, active_dirs: set[Path]) -> bool:
    resolved = output_dir.resolve()
    roots = (settings.temp_dir.resolve(), (settings.data_dir / "output").resolve())
    if output_dir.is_symlink() or not any(root in resolved.parents for root in roots):
        return False
    if any(
        resolved == active or resolved in active.parents or active in resolved.parents
        for active in active_dirs
    ):
        return False
    if not output_dir.is_dir():
        return False
    shutil.rmtree(output_dir)
    logger.debug(t(LOG_OUTPUT_DIR_REMOVED).format(name=output_dir))
    return True


@contextmanager
def active_download_directories():
    """Hold token creation and expiry while a caller checks and removes files."""
    with _connection_lock:
        conn = _get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT DISTINCT output_dir FROM download_tokens WHERE criado_em >= datetime('now', ?)",
                (f"-{TOKEN_EXPIRY_DAYS} days",),
            ).fetchall()
            active_dirs = {Path(row["output_dir"]).resolve() for row in rows}
            yield active_dirs
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def remove_unreferenced_output_directory(output_dir: Path) -> bool:
    """Serialize retention checks and deletion with token creation, including other processes."""
    with active_download_directories() as active_dirs:
        return _remove_unreferenced_output_directory(output_dir, active_dirs)
