import asyncio

# NOTE: Table creation drops the existing download_tokens table, invalidating all previous tokens.
# If migration of existing tokens is required, implement a proper migration before dropping.

# NOTE: Table creation drops the existing download_tokens table, invalidating all previous tokens.
# If migration of existing tokens is required, implement a proper migration before dropping.
import sqlite3
import uuid
from pathlib import Path
from core.utils.logger import logger
from config.settings import settings

DB_PATH = settings.db_path

_connection: sqlite3.Connection | None = None
_connection_lock = asyncio.Lock()

TOKEN_EXPIRY_DAYS = 7

FORMAT_EXTENSIONS = {
    "txt": "texto",
    "docx": "word",
    "pdf": "pdf",
    "html": "html",
    "mp3": "audio",
    "zip": "completo",
}


def _get_connection() -> sqlite3.Connection:
    global _connection
    if _connection is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("DROP TABLE IF EXISTS download_tokens")
        conn.execute("""
            CREATE TABLE download_tokens (
                token TEXT PRIMARY KEY,
                output_dir TEXT NOT NULL,
                filename TEXT NOT NULL,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_download_tokens_token ON download_tokens(token)"
        )
        conn.commit()
        _connection = conn
    return _connection


async def criar_token(output_dir: Path, filename: str) -> str:
    token = str(uuid.uuid4())
    async with _connection_lock:
        conn = _get_connection()
        conn.execute(
            "INSERT INTO download_tokens (token, output_dir, filename) VALUES (?, ?, ?)",
            (token, str(output_dir), filename),
        )
        conn.commit()
    logger.debug("Token de download criado: {} -> {}", token, filename)
    return token


async def obter_info_token(token: str) -> dict | None:
    async with _connection_lock:
        conn = _get_connection()
        row = conn.execute(
            "SELECT output_dir, filename, criado_em FROM download_tokens WHERE token = ?",
            (token,),
        ).fetchone()
        if row is None:
            return None
        output_dir = Path(row["output_dir"])
        if not output_dir.exists():
            return None
        formats = []
        for ext, label in FORMAT_EXTENSIONS.items():
            file_path = output_dir / f"{Path(row['filename']).stem}.{ext}"
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
    async with _connection_lock:
        conn = _get_connection()
        rows = conn.execute(
            "SELECT output_dir FROM download_tokens WHERE criado_em < datetime('now', ?)",
            (f"-{dias} days",),
        ).fetchall()
        for row in rows:
            output_dir = Path(row["output_dir"])
            if output_dir.exists():
                import shutil
                # Ensure we only delete directories inside the configured temporary directory
                if str(output_dir).startswith(str(settings.temp_dir)):
                    shutil.rmtree(output_dir, ignore_errors=True)
                else:
                    logger.warning("Attempted to delete directory outside temp_dir: {}", output_dir)
        conn.execute(
            "DELETE FROM download_tokens WHERE criado_em < datetime('now', ?)",
            (f"-{dias} days",),
        )
        conn.commit()
