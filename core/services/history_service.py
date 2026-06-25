import asyncio
import sqlite3
from core.utils.logger import logger
from config.settings import settings

DB_PATH = settings.db_path

_connection: sqlite3.Connection | None = None
_connection_lock = asyncio.Lock()


def _criar_tabelas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT UNIQUE NOT NULL,
            arquivo TEXT NOT NULL,
            extensao TEXT NOT NULL,
            tamanho_bytes INTEGER DEFAULT 0,
            modo TEXT DEFAULT 'normal',
            pipeline TEXT DEFAULT '',
            status TEXT DEFAULT 'processing',
            tempo_segundos REAL DEFAULT 0,
            erro TEXT DEFAULT '',
            resultado_resumo TEXT DEFAULT '',
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            concluido_em TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ocr_raw (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            page_number INTEGER NOT NULL,
            text TEXT NOT NULL,
            fonte TEXT DEFAULT 'tesseract',
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ocr_revised (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            page_number INTEGER NOT NULL,
            text TEXT NOT NULL,
            modelo TEXT DEFAULT 'qwen2.5:3b',
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ocr_translated (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            page_number INTEGER NOT NULL,
            text TEXT NOT NULL,
            modelo TEXT DEFAULT 'qwen2.5:1.5b',
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ocr_raw_task ON ocr_raw(task_id)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ocr_revised_task ON ocr_revised(task_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ocr_translated_task ON ocr_translated(task_id)"
    )
    conn.commit()


def get_connection() -> sqlite3.Connection:
    global _connection
    if _connection is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        _criar_tabelas(conn)
        _connection = conn
    return _connection


def init_db():
    get_connection()


def limpar_orfas():
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE conversoes SET status='error', erro='Stale: process interrupted' "
            "WHERE status='processing' AND criado_em < datetime('now', '-1 hours')"
        )
        conn.commit()
        logger.info("Tarefas orfas limpas")
    except Exception as e:
        logger.warning("Falha ao limpar tarefas orfas: {}", e)


async def registrar_conversao(
    task_id: str,
    arquivo: str,
    extensao: str,
    tamanho_bytes: int = 0,
    modo: str = "normal",
):
    async with _connection_lock:
        conn = get_connection()
        conn.execute(
            """INSERT OR IGNORE INTO conversoes
               (task_id, arquivo, extensao, tamanho_bytes, modo)
               VALUES (?, ?, ?, ?, ?)""",
            (task_id, arquivo, extensao, tamanho_bytes, modo),
        )
        conn.commit()


async def finalizar_conversao(
    task_id: str,
    status: str,
    pipeline: str = "",
    erro: str = "",
    resultado_resumo: str = "",
    tempo_segundos: float = 0,
):
    async with _connection_lock:
        conn = get_connection()
        conn.execute(
            """UPDATE conversoes SET
               status = ?, pipeline = ?, erro = ?,
               resultado_resumo = ?, tempo_segundos = ?,
               concluido_em = CURRENT_TIMESTAMP
               WHERE task_id = ?""",
            (status, pipeline, erro, resultado_resumo, tempo_segundos, task_id),
        )
        conn.commit()


async def listar_historico(limite: int = 10) -> list[dict]:
    async with _connection_lock:
        conn = get_connection()
        rows = conn.execute(
            """SELECT * FROM conversoes
               ORDER BY criado_em DESC LIMIT ?""",
            (limite,),
        ).fetchall()
        return [dict(r) for r in rows]


async def salvar_ocr_raw(task_id: str, page_number: int, text: str):
    async with _connection_lock:
        conn = get_connection()
        conn.execute(
            "INSERT INTO ocr_raw (task_id, page_number, text) VALUES (?, ?, ?)",
            (task_id, page_number, text),
        )
        conn.commit()


async def listar_ocr_raw(task_id: str) -> list[dict]:
    async with _connection_lock:
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM ocr_raw WHERE task_id = ? ORDER BY page_number", (task_id,)
        ).fetchall()
        return [dict(r) for r in rows]


async def salvar_ocr_revised(
    task_id: str, page_number: int, text: str, modelo: str = "qwen2.5:3b"
):
    async with _connection_lock:
        conn = get_connection()
        conn.execute(
            "INSERT INTO ocr_revised (task_id, page_number, text, modelo) VALUES (?, ?, ?, ?)",
            (task_id, page_number, text, modelo),
        )
        conn.commit()


async def listar_ocr_revised(task_id: str) -> list[dict]:
    async with _connection_lock:
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM ocr_revised WHERE task_id = ? ORDER BY page_number",
            (task_id,),
        ).fetchall()
        return [dict(r) for r in rows]


async def salvar_ocr_translated(
    task_id: str, page_number: int, text: str, modelo: str = "qwen2.5:1.5b"
):
    async with _connection_lock:
        conn = get_connection()
        conn.execute(
            "INSERT INTO ocr_translated (task_id, page_number, text, modelo) VALUES (?, ?, ?, ?)",
            (task_id, page_number, text, modelo),
        )
        conn.commit()


async def listar_ocr_translated(task_id: str) -> list[dict]:
    async with _connection_lock:
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM ocr_translated WHERE task_id = ? ORDER BY page_number",
            (task_id,),
        ).fetchall()
        return [dict(r) for r in rows]


async def limpar_ocr_data(task_id: str):
    async with _connection_lock:
        conn = get_connection()
        conn.execute("DELETE FROM ocr_raw WHERE task_id = ?", (task_id,))
        conn.execute("DELETE FROM ocr_revised WHERE task_id = ?", (task_id,))
        conn.execute("DELETE FROM ocr_translated WHERE task_id = ?", (task_id,))
        conn.commit()


async def estatisticas() -> dict:
    async with _connection_lock:
        conn = get_connection()
        total = conn.execute("SELECT COUNT(*) FROM conversoes").fetchone()[0]
        sucesso = conn.execute(
            "SELECT COUNT(*) FROM conversoes WHERE status='done'"
        ).fetchone()[0]
        erros = conn.execute(
            "SELECT COUNT(*) FROM conversoes WHERE status='error'"
        ).fetchone()[0]
        tempo_medio = (
            conn.execute(
                "SELECT AVG(tempo_segundos) FROM conversoes WHERE status='done'"
            ).fetchone()[0]
            or 0
        )
        return {
            "total": total,
            "sucesso": sucesso,
            "erros": erros,
            "tempo_medio_segundos": round(tempo_medio, 1),
        }
