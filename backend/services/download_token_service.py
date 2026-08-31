import asyncio
import json
import sqlite3
import uuid
import threading
import shutil
from pathlib import Path

from backend.tools.logger import logger
from backend.config.settings import settings

# Database connection configuration
_connection = None
_connection_lock = threading.Lock()

TOKEN_EXPIRY_DAYS = 7

FORMAT_EXTENSIONS = {
    "txt": "texto",
    "docx": "word",
    "pdf": "pdf",
    "pdf_ua": "pdf/ua",
    "html": "html",
    "mp3": "audio",
    "zip": "completo",
}

FORMAT_OUTPUT_SUFFIX = {
    "pdf_ua": "pdf_ua.pdf",
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
                    formats TEXT NULL DEFAULT '[]'
                )
            """)
            cursor.execute("PRAGMA table_info(download_tokens)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'formats' not in columns:
                cursor.execute("ALTER TABLE download_tokens ADD COLUMN formats TEXT NULL DEFAULT '[]'")
            try:
                cursor.execute("CREATE INDEX idx_download_tokens_token ON download_tokens(token)")
            except sqlite3.OperationalError as e:
                if "already exists" not in str(e).lower():
                    raise
            _connection.commit()
        finally:
            cursor.close()
    return _connection


async def criar_token(output_dir: Path, filename: str, formats: list = None) -> str:
    token = str(uuid.uuid4())
    formats_json = json.dumps(formats) if formats else '[]'
    with _connection_lock:
        conn = _get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO download_tokens (token, output_dir, filename, formats) VALUES (?, ?, ?, ?)",
                (token, str(output_dir), filename, formats_json)
            )
            conn.commit()
        finally:
            cursor.close()
    logger.debug("Token de download criado: {} -> {}", token, filename)
    return token


async def obter_info_token(token: str) -> dict | None:
    with _connection_lock:
        conn = _get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT output_dir, filename, formats, criado_em FROM download_tokens WHERE token = ?",
                (token,)
            )
            row = cursor.fetchone()
        finally:
            cursor.close()
    if row is None:
        return None
    output_dir = Path(row["output_dir"])
    if not output_dir.exists():
        return None
    formats_list = json.loads(row["formats"]) if row["formats"] else []
    formats = []
    for ext, label in FORMAT_EXTENSIONS.items():
        suffix = FORMAT_OUTPUT_SUFFIX.get(ext, ext)
        file_path = output_dir / f"{Path(row['filename']).stem}.{suffix}"
        if file_path.exists():
            size_kb = file_path.stat().st_size / 1024
            size_str = f"{size_kb:.0f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
            formats.append({
                "ext": ext,
                "label": label,
                "file_path": str(file_path),
                "size": size_str,
                "url": f"/download/{token}/{ext}",
            })
    return {
        "filename": row["filename"],
        "stem": Path(row["filename"]).stem,
        "output_dir": str(output_dir),
        "criado_em": row["criado_em"],
        "formats": formats,
    }


async def limpar_tokens_expirados(dias: int = TOKEN_EXPIRY_DAYS):
    with _connection_lock:
        conn = _get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT output_dir FROM download_tokens WHERE criado_em < datetime('now', '-{} days')".format(dias)
            )
            rows = cursor.fetchall()
        finally:
            cursor.close()
        for row in rows:
            output_dir = Path(row["output_dir"])
            if output_dir.exists():
                if str(output_dir).startswith(str(settings.temp_dir)) or str(output_dir).startswith(str(settings.data_dir / "output")):
                    shutil.rmtree(output_dir, ignore_errors=True)
                    logger.debug("Diretório de output removido: {}", output_dir)
        cursor = conn.cursor()
        try:
            cursor.execute(
                "DELETE FROM download_tokens WHERE criado_em < datetime('now', '-{} days')".format(dias)
            )
            conn.commit()
        finally:
            cursor.close()
