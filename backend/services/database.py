from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    func,
)
from sqlalchemy.engine import Engine

from backend.config.settings import settings
from backend.tools.logger import logger

metadata = MetaData()

conversoes = Table(
    "conversoes",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("task_id", String(64), unique=True, nullable=False),
    Column("arquivo", String(512), nullable=False),
    Column("extensao", String(16), nullable=False),
    Column("tamanho_bytes", Integer, nullable=False, server_default="0"),
    Column("modo", String(32), nullable=False, server_default="normal"),
    Column("pipeline", String(64), nullable=False, server_default=""),
    Column("status", String(32), nullable=False, server_default="processing"),
    Column("tempo_segundos", Float, nullable=False, server_default="0"),
    Column("erro", Text, nullable=True),
    Column("resultado_resumo", Text, nullable=True),
    Column("criado_em", DateTime, server_default=func.now()),
    Column("concluido_em", DateTime, nullable=True),
)

ocr_raw = Table(
    "ocr_raw",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("task_id", String(64), nullable=False),
    Column("page_number", Integer, nullable=False),
    Column("text", Text, nullable=False),
    Column("fonte", String(32), nullable=False, server_default="tesseract"),
    Column("criado_em", DateTime, server_default=func.now()),
    Index("idx_ocr_raw_task", "task_id"),
)

ocr_revised = Table(
    "ocr_revised",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("task_id", String(64), nullable=False),
    Column("page_number", Integer, nullable=False),
    Column("text", Text, nullable=False),
    Column("modelo", String(64), nullable=False, server_default="qwen2.5:3b"),
    Column("criado_em", DateTime, server_default=func.now()),
    Index("idx_ocr_revised_task", "task_id"),
)

ocr_translated = Table(
    "ocr_translated",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("task_id", String(64), nullable=False),
    Column("page_number", Integer, nullable=False),
    Column("text", Text, nullable=False),
    Column("modelo", String(64), nullable=False, server_default="qwen2.5:1.5b"),
    Column("criado_em", DateTime, server_default=func.now()),
    Index("idx_ocr_translated_task", "task_id"),
)

download_tokens = Table(
    "download_tokens",
    metadata,
    Column("token", String(36), primary_key=True),
    Column("output_dir", String(1024), nullable=False, server_default=""),
    Column("filename", String(512), nullable=False, server_default=""),
    Column("criado_em", DateTime, server_default=func.now()),
    Column("formats", String(512), nullable=True, server_default="[]"),
    Index("idx_download_tokens_token", "token"),
)

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = _create_engine()
    return _engine


def _create_engine() -> Engine:
    if settings.db_backend == "mysql":
        return create_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_recycle=3600,
            pool_size=5,
            max_overflow=10,
        )
    db_path = settings.db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )


def init_db() -> None:
    engine = get_engine()
    metadata.create_all(engine)
    if settings.db_backend != "mysql":
        _migrar_sqlite(engine)
    logger.info("Banco de dados inicializado (backend={})", settings.db_backend)


def _migrar_sqlite(engine: Engine) -> None:
    with engine.connect() as conn:
        columns = [
            row[1]
            for row in conn.exec_driver_sql("PRAGMA table_info(download_tokens)")
        ]
        if "formats" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE download_tokens ADD COLUMN formats VARCHAR(512) DEFAULT '[]'"
            )
            conn.commit()


def dispose() -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None
