from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class UploadResponse(BaseModel):
    task_id: str
    position: int
    message: str


class CancelResponse(BaseModel):
    task_id: str
    status: str


class JobStatus(BaseModel):
    task_id: str
    arquivo: str
    status: str
    progresso: float
    etapa_atual: str
    erros: list[str] = Field(default_factory=list)
    download_url: str | None = None
    criado_em: float | None = None
    fim: float | None = None


class DownloadFormat(BaseModel):
    ext: str
    label: str
    size: str
    url: str


class DownloadInfo(BaseModel):
    filename: str
    stem: str
    criado_em: str | None = None
    formats: list[DownloadFormat]


class HistoryItem(BaseModel):
    task_id: str
    arquivo: str
    extensao: str
    status: str
    modo: str
    pipeline: str
    erro: str
    resultado_resumo: str
    tempo_segundos: float
    criado_em: str | None = None
    concluido_em: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class StatsResponse(BaseModel):
    total: int
    sucesso: int
    erros: int
    tempo_medio_segundos: float


class HealthResponse(BaseModel):
    status: str
    model_client: str
    model_name: str
    model_reachable: bool
    queue_size: int
    git_commit: str = ""
    image_tag: str = ""
