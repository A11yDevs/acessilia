from __future__ import annotations

from fastapi import APIRouter, Query, Request

from backend.api.limiter import limiter
from backend.api.schemas import HistoryItem, StatsResponse
from backend.services.history_service import estatisticas, listar_historico

router = APIRouter(tags=["history"])

FIELD_NAMES = {
    "task_id",
    "arquivo",
    "extensao",
    "status",
    "modo",
    "pipeline",
    "erro",
    "resultado_resumo",
    "tempo_segundos",
    "criado_em",
    "concluido_em",
}


@router.get("/history", response_model=list[HistoryItem])
@limiter.limit("30/minute")
async def history(request: Request, limit: int = Query(20, ge=1, le=100)):
    rows = await listar_historico(limit)
    result = []
    for row in rows:
        item = {key: row[key] for key in FIELD_NAMES if key in row}
        item["extra"] = {key: row[key] for key in row if key not in FIELD_NAMES}
        result.append(HistoryItem(**item))
    return result


@router.get("/stats", response_model=StatsResponse)
@limiter.limit("30/minute")
async def stats(request: Request):
    data = await estatisticas()
    return StatsResponse(**data)
