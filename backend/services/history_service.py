import asyncio
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, update

from backend.config.settings import settings
from backend.services import database
from backend.tools.logger import logger

_connection_lock = asyncio.Lock()


def get_connection():
    return database.get_engine().connect()


def init_db():
    database.init_db()


def _agora() -> datetime:
    return datetime.utcnow()


def _serializar_linha(row: Any) -> dict:
    item = dict(row._mapping)
    for key in ("criado_em", "concluido_em"):
        if isinstance(item.get(key), datetime):
            item[key] = item[key].strftime("%Y-%m-%d %H:%M:%S")
    return item


def limpar_orfas():
    engine = database.get_engine()
    cutoff = _agora() - timedelta(hours=1)
    try:
        with engine.begin() as conn:
            conn.execute(
                update(database.conversoes)
                .where(
                    database.conversoes.c.status == "processing",
                    database.conversoes.c.criado_em < cutoff,
                )
                .values(
                    status="error",
                    erro="Stale: process interrupted",
                    concluido_em=_agora(),
                )
            )
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
        engine = database.get_engine()
        with engine.connect() as conn:
            existing = conn.execute(
                select(database.conversoes.c.id).where(
                    database.conversoes.c.task_id == task_id
                )
            ).first()
        if existing is None:
            with engine.begin() as conn:
                conn.execute(
                    database.conversoes.insert().values(
                        task_id=task_id,
                        arquivo=arquivo,
                        extensao=extensao,
                        tamanho_bytes=tamanho_bytes,
                        modo=modo,
                    )
                )


async def finalizar_conversao(
    task_id: str,
    status: str,
    pipeline: str = "",
    erro: str = "",
    resultado_resumo: str = "",
    tempo_segundos: float = 0,
):
    async with _connection_lock:
        engine = database.get_engine()
        with engine.begin() as conn:
            conn.execute(
                update(database.conversoes)
                .where(database.conversoes.c.task_id == task_id)
                .values(
                    status=status,
                    pipeline=pipeline,
                    erro=erro,
                    resultado_resumo=resultado_resumo,
                    tempo_segundos=tempo_segundos,
                    concluido_em=_agora(),
                )
            )


async def listar_historico(limite: int = 10) -> list[dict]:
    async with _connection_lock:
        engine = database.get_engine()
        with engine.connect() as conn:
            rows = conn.execute(
                select(database.conversoes)
                .order_by(database.conversoes.c.criado_em.desc())
                .limit(limite)
            )
            return [_serializar_linha(row) for row in rows]


async def salvar_ocr_raw(task_id: str, page_number: int, text: str):
    async with _connection_lock:
        engine = database.get_engine()
        with engine.begin() as conn:
            conn.execute(
                database.ocr_raw.insert().values(
                    task_id=task_id,
                    page_number=page_number,
                    text=text,
                )
            )


async def listar_ocr_raw(task_id: str) -> list[dict]:
    async with _connection_lock:
        engine = database.get_engine()
        with engine.connect() as conn:
            rows = conn.execute(
                select(database.ocr_raw)
                .where(database.ocr_raw.c.task_id == task_id)
                .order_by(database.ocr_raw.c.page_number)
            )
            return [dict(row._mapping) for row in rows]


async def salvar_ocr_revised(
    task_id: str, page_number: int, text: str, modelo: str = "qwen2.5:3b"
):
    async with _connection_lock:
        engine = database.get_engine()
        with engine.begin() as conn:
            conn.execute(
                database.ocr_revised.insert().values(
                    task_id=task_id,
                    page_number=page_number,
                    text=text,
                    modelo=modelo,
                )
            )


async def listar_ocr_revised(task_id: str) -> list[dict]:
    async with _connection_lock:
        engine = database.get_engine()
        with engine.connect() as conn:
            rows = conn.execute(
                select(database.ocr_revised)
                .where(database.ocr_revised.c.task_id == task_id)
                .order_by(database.ocr_revised.c.page_number)
            )
            return [dict(row._mapping) for row in rows]


async def salvar_ocr_translated(
    task_id: str, page_number: int, text: str, modelo: str = "qwen2.5:1.5b"
):
    async with _connection_lock:
        engine = database.get_engine()
        with engine.begin() as conn:
            conn.execute(
                database.ocr_translated.insert().values(
                    task_id=task_id,
                    page_number=page_number,
                    text=text,
                    modelo=modelo,
                )
            )


async def listar_ocr_translated(task_id: str) -> list[dict]:
    async with _connection_lock:
        engine = database.get_engine()
        with engine.connect() as conn:
            rows = conn.execute(
                select(database.ocr_translated)
                .where(database.ocr_translated.c.task_id == task_id)
                .order_by(database.ocr_translated.c.page_number)
            )
            return [dict(row._mapping) for row in rows]


async def limpar_ocr_data(task_id: str):
    async with _connection_lock:
        engine = database.get_engine()
        with engine.begin() as conn:
            conn.execute(
                delete(database.ocr_raw).where(database.ocr_raw.c.task_id == task_id)
            )
            conn.execute(
                delete(database.ocr_revised).where(
                    database.ocr_revised.c.task_id == task_id
                )
            )
            conn.execute(
                delete(database.ocr_translated).where(
                    database.ocr_translated.c.task_id == task_id
                )
            )


async def estatisticas() -> dict:
    async with _connection_lock:
        engine = database.get_engine()
        with engine.connect() as conn:
            total = conn.execute(
                select(func.count()).select_from(database.conversoes)
            ).scalar() or 0
            sucesso = (
                conn.execute(
                    select(func.count())
                    .select_from(database.conversoes)
                    .where(database.conversoes.c.status == "done")
                ).scalar()
                or 0
            )
            erros = (
                conn.execute(
                    select(func.count())
                    .select_from(database.conversoes)
                    .where(database.conversoes.c.status == "error")
                ).scalar()
                or 0
            )
            tempo_medio = (
                conn.execute(
                    select(func.avg(database.conversoes.c.tempo_segundos))
                    .select_from(database.conversoes)
                    .where(database.conversoes.c.status == "done")
                ).scalar()
                or 0
            )
        return {
            "total": total,
            "sucesso": sucesso,
            "erros": erros,
            "tempo_medio_segundos": round(float(tempo_medio), 1),
        }
