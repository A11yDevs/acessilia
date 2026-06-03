import asyncio
import sqlite3
import uuid
from pathlib import Path
from core.utils.logger import logger
from config.settings import settings

DB_PATH = settings.db_path

_connection: sqlite3.Connection | None = None
_connection_lock = asyncio.Lock()

TOKEN_EXPIRY_DAYS = 7


def _get_connection() -> sqlite3.Connection:
    global _connection
    if _connection is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS download_tokens (
                token TEXT PRIMARY KEY,
                zip_path TEXT NOT NULL,
                filename TEXT NOT NULL,
                usado INTEGER DEFAULT 0,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_download_tokens_token ON download_tokens(token)"
        )
        conn.commit()
        _connection = conn
    return _connection


async def criar_token(zip_path: Path) -> str:
    token = str(uuid.uuid4())
    async with _connection_lock:
        conn = _get_connection()
        conn.execute(
            "INSERT INTO download_tokens (token, zip_path, filename) VALUES (?, ?, ?)",
            (token, str(zip_path), zip_path.name),
        )
        conn.commit()
    logger.debug("Token de download criado: {} -> {}", token, zip_path.name)
    return token


async def consumir_token(token: str) -> Path | None:
    async with _connection_lock:
        conn = _get_connection()
        row = conn.execute(
            "SELECT zip_path, usado FROM download_tokens WHERE token = ?",
            (token,),
        ).fetchone()
        if row is None or row["usado"]:
            return None
        conn.execute(
            "UPDATE download_tokens SET usado = 1 WHERE token = ?",
            (token,),
        )
        conn.commit()
    zip_path = Path(row["zip_path"])
    return zip_path if zip_path.exists() else None


async def limpar_tokens_expirados(dias: int = TOKEN_EXPIRY_DAYS):
    async with _connection_lock:
        conn = _get_connection()
        conn.execute(
            "DELETE FROM download_tokens WHERE criado_em < datetime('now', ?)",
            (f"-{dias} days",),
        )
        conn.commit()
