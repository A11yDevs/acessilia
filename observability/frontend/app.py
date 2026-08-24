from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from observability.frontend.agno_client import AgnoClient
from observability.frontend.store import (
    DEFAULT_DB_PATH,
    create_annotation,
    delete_annotation,
    list_annotations,
)


BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))

INTERNAL_HANDLER_RE = "/metrics|/api/v1/health|/api/v1/stats|/api/v1/history"
HTTP_4XX_RE = "4..|4xx"
HTTP_5XX_RE = "5..|5xx"


def _selector(extra: str = "") -> str:
    extra = f",{extra}" if extra else ""
    return f'{{job="acessilia-api"{extra}}}'


def _zero(query: str) -> str:
    return f"(({query}) or vector(0))"


def _traffic_rate(extra: str = "", window: str = "30s") -> str:
    return _zero(f"sum(rate(http_requests_total{_selector(extra)}[{window}]))")


USER_TRAFFIC_FILTER = f'handler!~"{INTERNAL_HANDLER_RE}"'
INTERNAL_TRAFFIC_FILTER = f'handler=~"{INTERNAL_HANDLER_RE}"'
HTTP_4XX_USER_FILTER = f'{USER_TRAFFIC_FILTER},status=~"{HTTP_4XX_RE}"'
HTTP_5XX_USER_FILTER = f'{USER_TRAFFIC_FILTER},status=~"{HTTP_5XX_RE}"'
HTTP_ERROR_USER_FILTER = f'{USER_TRAFFIC_FILTER},status=~"{HTTP_4XX_RE}|{HTTP_5XX_RE}"'

REQ_USER = _traffic_rate(USER_TRAFFIC_FILTER)
REQ_INTERNAL = _traffic_rate(INTERNAL_TRAFFIC_FILTER)
REQ_TOTAL = _traffic_rate()
HTTP_USER_DENOMINATOR = _zero(
    f"sum(rate(http_requests_total{_selector(USER_TRAFFIC_FILTER)}[5m]))"
)
HTTP_4XX_USER = (
    f"({_traffic_rate(HTTP_4XX_USER_FILTER, '5m')} "
    f"/ clamp_min({HTTP_USER_DENOMINATOR}, 0.001)) * 100"
)
HTTP_5XX_USER = (
    f"({_traffic_rate(HTTP_5XX_USER_FILTER, '5m')} "
    f"/ clamp_min({HTTP_USER_DENOMINATOR}, 0.001)) * 100"
)
HTTP_ERROR_USER = (
    f"({_traffic_rate(HTTP_ERROR_USER_FILTER, '5m')} "
    f"/ clamp_min({HTTP_USER_DENOMINATOR}, 0.001)) * 100"
)
P95_USER = (
    "histogram_quantile(0.95, sum by (le) "
    f'(rate(http_request_duration_seconds_bucket{_selector(USER_TRAFFIC_FILTER)}[5m])))'
)
CPU_QUERY = _zero('100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[1m])) * 100)')
RAM_QUERY = _zero(
    "avg((1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100)"
)
DISK_ROOT_QUERY = _zero(
    'max(100 * (1 - (node_filesystem_avail_bytes{mountpoint="/",fstype!~"tmpfs|overlay|squashfs|proc|sysfs|devtmpfs"} '
    '/ node_filesystem_size_bytes{mountpoint="/",fstype!~"tmpfs|overlay|squashfs|proc|sysfs|devtmpfs"})))'
)
NET_RX_QUERY = _zero(
    'sum(rate(node_network_receive_bytes_total{device!~"lo|veth.*|docker.*|br-.*|flannel.*|cali.*"}[1m]))'
)
NET_TX_QUERY = _zero(
    'sum(rate(node_network_transmit_bytes_total{device!~"lo|veth.*|docker.*|br-.*|flannel.*|cali.*"}[1m]))'
)
GPU_UTIL_QUERY = "avg(DCGM_FI_DEV_GPU_UTIL)"
GPU_VRAM_QUERY = (
    "sum(DCGM_FI_DEV_FB_USED) / clamp_min(sum(DCGM_FI_DEV_FB_TOTAL), 1) * 100"
)
GPU_WATTS_QUERY = "avg(DCGM_FI_DEV_POWER_USAGE)"
GPU_TEMP_QUERY = "avg(DCGM_FI_DEV_GPU_TEMP)"
QUEUE_QUERY = _zero("acessilia_queue_size")
JOBS_ACTIVE_QUERY = _zero("sum(acessilia_jobs_active)")
JOBS_DONE_RATE_QUERY = _zero('sum(rate(acessilia_jobs_total{status="done"}[1m])) * 60')
JOBS_ERROR_RATE_QUERY = _zero('sum(rate(acessilia_jobs_total{status="error"}[1m])) * 60')
PIPELINE_ERRORS_RATE_QUERY = _zero("sum(rate(acessilia_pipeline_errors_total[1m])) * 60")
CONVERSION_AVG_QUERY = _zero(
    "sum(rate(acessilia_conversion_duration_seconds_sum[5m])) "
    "/ clamp_min(sum(rate(acessilia_conversion_duration_seconds_count[5m])), 1)"
)
EXPORTS_RATE_QUERY = _zero("sum(rate(acessilia_exports_total[1m])) * 60")
OUTPUT_BYTES_RATE_QUERY = _zero("sum(rate(acessilia_output_bytes_sum[1m]))")
LLM_CALLS_PER_MIN_QUERY = _zero("sum(rate(acessilia_llm_calls_total[1m])) * 60")
LLM_FAILURES_PER_MIN_QUERY = _zero("sum(rate(acessilia_llm_failures_total[1m])) * 60")
LLM_DURATION_AVG_QUERY = _zero(
    "sum(rate(acessilia_llm_duration_seconds_sum[5m])) "
    "/ clamp_min(sum(rate(acessilia_llm_duration_seconds_count[5m])), 1)"
)
LLM_TTFT_AVG_QUERY = _zero(
    "sum(rate(acessilia_llm_time_to_first_token_seconds_sum[5m])) "
    "/ clamp_min(sum(rate(acessilia_llm_time_to_first_token_seconds_count[5m])), 1)"
)
LLM_TOTAL_TOKENS_RATE_QUERY = _zero(
    'sum(rate(acessilia_llm_tokens_total{token_type="total"}[1m]))'
)
LLM_INPUT_TOKENS_RATE_QUERY = _zero(
    'sum(rate(acessilia_llm_tokens_total{token_type="input"}[1m]))'
)
LLM_OUTPUT_TOKENS_RATE_QUERY = _zero(
    'sum(rate(acessilia_llm_tokens_total{token_type="output"}[1m]))'
)
LLM_REASONING_TOKENS_RATE_QUERY = _zero(
    'sum(rate(acessilia_llm_tokens_total{token_type="reasoning"}[1m]))'
)
LLM_CACHE_READ_TOKENS_RATE_QUERY = _zero(
    'sum(rate(acessilia_llm_tokens_total{token_type="cache_read"}[1m]))'
)
LLM_CACHE_WRITE_TOKENS_RATE_QUERY = _zero(
    'sum(rate(acessilia_llm_tokens_total{token_type="cache_write"}[1m]))'
)
LLM_COST_PER_MIN_QUERY = _zero("sum(rate(acessilia_llm_cost_total[5m])) * 60")

REALTIME_METRICS = [
    {"key": "req_user", "label": "Req/s usuários", "query": REQ_USER, "unit": "rps"},
    {
        "key": "req_internal",
        "label": "Req/s interno",
        "query": REQ_INTERNAL,
        "unit": "rps",
    },
    {"key": "req_total", "label": "Req/s total", "query": REQ_TOTAL, "unit": "rps"},
    {"key": "http_4xx", "label": "HTTP 4xx %", "query": HTTP_4XX_USER, "unit": "percent"},
    {"key": "http_5xx", "label": "HTTP 5xx %", "query": HTTP_5XX_USER, "unit": "percent"},
    {"key": "queue", "label": "Fila", "query": QUEUE_QUERY, "unit": "count"},
    {
        "key": "jobs_active",
        "label": "Jobs ativos",
        "query": JOBS_ACTIVE_QUERY,
        "unit": "count",
    },
    {"key": "cpu", "label": "CPU", "query": CPU_QUERY, "unit": "percent"},
    {"key": "ram", "label": "RAM", "query": RAM_QUERY, "unit": "percent"},
    {
        "key": "llm_calls_per_min",
        "label": "LLM chamadas/min",
        "query": LLM_CALLS_PER_MIN_QUERY,
        "unit": "per_minute",
    },
    {
        "key": "llm_total_tokens_rate",
        "label": "LLM tokens/s",
        "query": LLM_TOTAL_TOKENS_RATE_QUERY,
        "unit": "tokens_per_second",
    },
    {
        "key": "llm_ttft_avg",
        "label": "LLM TTFT",
        "query": LLM_TTFT_AVG_QUERY,
        "unit": "seconds",
    },
]

TIMESERIES_METRICS = [
    *REALTIME_METRICS,
    {"key": "disk_root", "label": "Disco /", "query": DISK_ROOT_QUERY, "unit": "percent"},
    {"key": "net_rx", "label": "Rede entrada", "query": NET_RX_QUERY, "unit": "bytes_per_second"},
    {"key": "net_tx", "label": "Rede saída", "query": NET_TX_QUERY, "unit": "bytes_per_second"},
    {"key": "jobs_done_per_min", "label": "Jobs ok/min", "query": JOBS_DONE_RATE_QUERY, "unit": "per_minute"},
    {"key": "jobs_error_per_min", "label": "Jobs erro/min", "query": JOBS_ERROR_RATE_QUERY, "unit": "per_minute"},
    {"key": "pipeline_errors_per_min", "label": "Erros pipeline/min", "query": PIPELINE_ERRORS_RATE_QUERY, "unit": "per_minute"},
    {"key": "conversion_avg", "label": "Conversão média", "query": CONVERSION_AVG_QUERY, "unit": "seconds"},
    {"key": "exports_per_min", "label": "Exportações/min", "query": EXPORTS_RATE_QUERY, "unit": "per_minute"},
    {"key": "output_bytes_rate", "label": "Outputs/s", "query": OUTPUT_BYTES_RATE_QUERY, "unit": "bytes_per_second"},
    {"key": "llm_failures_per_min", "label": "LLM falhas/min", "query": LLM_FAILURES_PER_MIN_QUERY, "unit": "per_minute"},
    {"key": "llm_duration_avg", "label": "LLM duração", "query": LLM_DURATION_AVG_QUERY, "unit": "seconds"},
    {"key": "llm_input_tokens_rate", "label": "Input tokens/s", "query": LLM_INPUT_TOKENS_RATE_QUERY, "unit": "tokens_per_second"},
    {"key": "llm_output_tokens_rate", "label": "Output tokens/s", "query": LLM_OUTPUT_TOKENS_RATE_QUERY, "unit": "tokens_per_second"},
    {"key": "llm_reasoning_tokens_rate", "label": "Reasoning tokens/s", "query": LLM_REASONING_TOKENS_RATE_QUERY, "unit": "tokens_per_second"},
    {"key": "llm_cache_read_tokens_rate", "label": "Cache read tokens/s", "query": LLM_CACHE_READ_TOKENS_RATE_QUERY, "unit": "tokens_per_second"},
    {"key": "llm_cache_write_tokens_rate", "label": "Cache write tokens/s", "query": LLM_CACHE_WRITE_TOKENS_RATE_QUERY, "unit": "tokens_per_second"},
    {"key": "llm_cost_per_min", "label": "LLM custo/min", "query": LLM_COST_PER_MIN_QUERY, "unit": "currency_per_minute"},
    {"key": "gpu_util", "label": "GPU uso", "query": GPU_UTIL_QUERY, "unit": "percent"},
    {"key": "gpu_vram", "label": "GPU VRAM", "query": GPU_VRAM_QUERY, "unit": "percent"},
    {"key": "gpu_watts", "label": "GPU watts", "query": GPU_WATTS_QUERY, "unit": "watts"},
    {"key": "gpu_temp", "label": "GPU temp.", "query": GPU_TEMP_QUERY, "unit": "celsius"},
]


class AnnotationPayload(BaseModel):
    target_type: str = Field(default="geral", max_length=80)
    target_id: str = Field(default="observability", max_length=160)
    severity: str = Field(default="note", max_length=40)
    note: str = Field(min_length=1, max_length=4000)
    tags: str = Field(default="", max_length=240)


class AgnoRunPayload(BaseModel):
    entity_type: str = Field(pattern="^(agent|team)$")
    entity_id: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=12000)
    session_id: str = Field(default="", max_length=200)


def create_app() -> FastAPI:
    app = FastAPI(title="Acessilia Observability", version="1.0.0")
    app.mount(
        "/static",
        StaticFiles(directory=str(BASE_DIR / "static")),
        name="static",
    )

    app.state.api_url = _env_url("ACESSILIA_API_URL", "http://localhost:8000")
    app.state.prometheus_url = _env_url("PROMETHEUS_URL", "http://localhost:9090")
    app.state.loki_url = _env_url("LOKI_URL", "http://localhost:3100")
    app.state.langfuse_url = _env_url("LANGFUSE_URL", "http://localhost:3001")
    app.state.agno_os_url = _env_url("AGNO_OS_URL", "http://localhost:7777")
    app.state.agno_os_security_key = os.getenv("AGNO_OS_SECURITY_KEY", "").strip()
    app.state.db_path = Path(
        os.getenv("OBSERVABILITY_DB_PATH", str(DEFAULT_DB_PATH))
    ).expanduser()
    app.state.public_links = {
        "api": _env_url("PUBLIC_ACESSILIA_API_URL", "http://localhost:8000"),
        "grafana": _env_url("PUBLIC_GRAFANA_URL", "http://localhost:3000"),
        "prometheus": _env_url("PUBLIC_PROMETHEUS_URL", "http://localhost:9090"),
        "loki": _env_url("PUBLIC_LOKI_URL", "http://localhost:3100"),
        "langfuse": _env_url("PUBLIC_LANGFUSE_URL", "http://localhost:3001"),
        "agno": "/agno",
    }

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {"links": app.state.public_links},
        )

    @app.get("/agno", response_class=HTMLResponse)
    async def agno_console(request: Request) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(
            request,
            "agno.html",
            {
                "links": app.state.public_links,
                "agno_endpoint": app.state.agno_os_url,
            },
        )

    @app.get("/api/agno/status")
    async def agno_status() -> dict[str, Any]:
        timeout = httpx.Timeout(5.0, connect=2.0)
        agno = AgnoClient(
            app.state.agno_os_url,
            app.state.agno_os_security_key,
        )
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await agno.health(client)

    @app.get("/api/agno/entities")
    async def agno_entities() -> dict[str, Any]:
        timeout = httpx.Timeout(8.0, connect=2.0)
        agno = AgnoClient(
            app.state.agno_os_url,
            app.state.agno_os_security_key,
        )
        async with httpx.AsyncClient(timeout=timeout) as client:
            status, entities = await asyncio.gather(
                agno.health(client),
                agno.entities(client),
            )
        return {
            "endpoint": app.state.agno_os_url,
            "status": status,
            "entities": entities,
            "capabilities": {
                "agents": True,
                "teams": True,
                "workflows": False,
                "step_functions": False,
            },
        }

    @app.post("/api/agno/runs")
    async def agno_run(payload: AgnoRunPayload) -> StreamingResponse:
        agno = AgnoClient(
            app.state.agno_os_url,
            app.state.agno_os_security_key,
        )

        async def stream() -> Any:
            try:
                async for chunk in agno.stream_run(
                    entity_type=payload.entity_type,
                    entity_id=payload.entity_id,
                    message=payload.message,
                    session_id=payload.session_id,
                ):
                    yield chunk
            except Exception as exc:
                error = {
                    "event": "RunError",
                    "content": str(exc),
                    "created_at": int(time.time()),
                }
                yield json.dumps(error).encode("utf-8")

        return StreamingResponse(stream(), media_type="application/json")

    @app.get("/api/snapshot")
    async def snapshot() -> dict[str, Any]:
        timeout = httpx.Timeout(6.0, connect=2.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            api = await _read_api(client, app.state.api_url)
            metrics = await _read_prometheus(client, app.state.prometheus_url)
            logs = await _read_loki(client, app.state.loki_url)
            services = {
                "api": api["health"] is not None,
                "prometheus": metrics["available"],
                "loki": logs["available"],
                "langfuse": await _is_http_available(
                    client,
                    app.state.langfuse_url,
                    "/api/public/health",
                ),
            }

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "services": services,
            "api": api,
            "metrics": metrics["groups"],
            "logs": logs["entries"],
            "links": app.state.public_links,
            "annotations": list_annotations(app.state.db_path, limit=20),
        }

    @app.get("/api/realtime")
    async def realtime() -> dict[str, Any]:
        timeout = httpx.Timeout(4.0, connect=1.5)
        async with httpx.AsyncClient(timeout=timeout) as client:
            metrics = await _read_metric_definitions(
                client,
                app.state.prometheus_url,
                REALTIME_METRICS,
            )
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "metrics": metrics,
        }

    @app.get("/api/timeseries")
    async def timeseries(
        range_seconds: int = Query(default=300, ge=60, le=3600),
        step_seconds: int = Query(default=1, ge=1, le=60),
    ) -> dict[str, Any]:
        timeout = httpx.Timeout(8.0, connect=2.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            series = await _read_timeseries(
                client,
                app.state.prometheus_url,
                range_seconds=range_seconds,
                step_seconds=step_seconds,
            )
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "range_seconds": range_seconds,
            "step_seconds": step_seconds,
            "series": series,
        }

    @app.get("/api/annotations")
    async def annotations(limit: int = 100) -> dict[str, Any]:
        return {"items": list_annotations(app.state.db_path, limit=limit)}

    @app.post("/api/annotations", status_code=201)
    async def add_annotation(payload: AnnotationPayload) -> dict[str, Any]:
        try:
            item = create_annotation(
                target_type=payload.target_type,
                target_id=payload.target_id,
                severity=payload.severity,
                note=payload.note,
                tags=payload.tags,
                db_path=app.state.db_path,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"item": item}

    @app.delete(
        "/api/annotations/{annotation_id}",
        status_code=204,
        response_class=Response,
    )
    async def remove_annotation(annotation_id: int) -> Response:
        if not delete_annotation(annotation_id, app.state.db_path):
            raise HTTPException(status_code=404, detail="Anotação não encontrada")
        return Response(status_code=204)

    return app


def _env_url(name: str, default: str) -> str:
    return os.getenv(name, default).rstrip("/")


async def _read_api(client: httpx.AsyncClient, base_url: str) -> dict[str, Any]:
    return {
        "health": await _json_or_none(client, base_url, "/api/v1/health"),
        "stats": await _json_or_none(client, base_url, "/api/v1/stats"),
        "history": await _json_or_none(client, base_url, "/api/v1/history?limit=20")
        or [],
    }


async def _read_prometheus(
    client: httpx.AsyncClient,
    base_url: str,
) -> dict[str, Any]:
    available = await _is_http_available(client, base_url, "/-/ready")
    groups = {
        "overview": [
            await _metric(
                client,
                base_url,
                "API up",
                'up{job="acessilia-api"}',
                "state",
            ),
            await _metric(
                client,
                base_url,
                "Req/s usuários",
                REQ_USER,
                "rps",
            ),
            await _metric(
                client,
                base_url,
                "Req/s interno",
                REQ_INTERNAL,
                "rps",
            ),
            await _metric(
                client,
                base_url,
                "Req/s total",
                REQ_TOTAL,
                "rps",
            ),
            await _metric(
                client,
                base_url,
                "Erro HTTP usuário %",
                HTTP_ERROR_USER,
                "percent",
            ),
            await _metric(
                client,
                base_url,
                "HTTP 4xx usuário %",
                HTTP_4XX_USER,
                "percent",
            ),
            await _metric(
                client,
                base_url,
                "HTTP 5xx usuário %",
                HTTP_5XX_USER,
                "percent",
            ),
            await _metric(
                client,
                base_url,
                "p95 usuário",
                P95_USER,
                "seconds",
            ),
        ],
        "pipeline": [
            await _metric(
                client,
                base_url,
                "Fila",
                QUEUE_QUERY,
                "count",
            ),
            await _metric(
                client,
                base_url,
                "Jobs ativos",
                JOBS_ACTIVE_QUERY,
                "count",
            ),
            await _vector_metric(
                client,
                base_url,
                "Jobs por status",
                "sum by (status) (acessilia_jobs_total)",
                "count",
            ),
            await _vector_metric(
                client,
                base_url,
                "Erros por etapa",
                "sum by (stage) (acessilia_pipeline_errors_total)",
                "count",
            ),
            await _metric(
                client,
                base_url,
                "Jobs ok/min",
                JOBS_DONE_RATE_QUERY,
                "per_minute",
            ),
            await _metric(
                client,
                base_url,
                "Jobs erro/min",
                JOBS_ERROR_RATE_QUERY,
                "per_minute",
            ),
            await _metric(
                client,
                base_url,
                "Erros pipeline/min",
                PIPELINE_ERRORS_RATE_QUERY,
                "per_minute",
            ),
        ],
        "detailed": [
            await _metric(
                client,
                base_url,
                "Duração média",
                CONVERSION_AVG_QUERY,
                "seconds",
            ),
            await _metric(
                client,
                base_url,
                "Exportações/min",
                EXPORTS_RATE_QUERY,
                "per_minute",
            ),
            await _metric(
                client,
                base_url,
                "Outputs/s",
                OUTPUT_BYTES_RATE_QUERY,
                "bytes_per_second",
            ),
            await _metric(
                client,
                base_url,
                "Duração média histórica",
                (
                    "sum(acessilia_conversion_duration_seconds_sum) "
                    "/ clamp_min(sum(acessilia_conversion_duration_seconds_count), 1)"
                ),
                "seconds",
            ),
            await _vector_metric(
                client,
                base_url,
                "Exportações por formato",
                "sum by (format) (acessilia_exports_total)",
                "count",
            ),
            await _vector_metric(
                client,
                base_url,
                "Bytes por formato",
                "sum by (format) (acessilia_output_bytes_sum)",
                "bytes",
            ),
        ],
        "infra": [
            await _metric(
                client,
                base_url,
                "CPU",
                CPU_QUERY,
                "percent",
            ),
            await _metric(
                client,
                base_url,
                "RAM",
                RAM_QUERY,
                "percent",
            ),
            await _metric(
                client,
                base_url,
                "Disco /",
                DISK_ROOT_QUERY,
                "percent",
            ),
            await _metric(
                client,
                base_url,
                "Rede entrada",
                NET_RX_QUERY,
                "bytes_per_second",
            ),
            await _metric(
                client,
                base_url,
                "Rede saída",
                NET_TX_QUERY,
                "bytes_per_second",
            ),
            await _metric(
                client,
                base_url,
                "Prometheus targets",
                "sum(up)",
                "count",
            ),
            await _metric(
                client,
                base_url,
                "Alloy up",
                'up{job="alloy"}',
                "state",
            ),
            await _metric(
                client,
                base_url,
                "GPU uso",
                GPU_UTIL_QUERY,
                "percent",
            ),
            await _metric(
                client,
                base_url,
                "GPU VRAM",
                GPU_VRAM_QUERY,
                "percent",
            ),
            await _metric(
                client,
                base_url,
                "GPU watts",
                GPU_WATTS_QUERY,
                "watts",
            ),
            await _metric(
                client,
                base_url,
                "GPU temp.",
                GPU_TEMP_QUERY,
                "celsius",
            ),
        ],
        "llm": [
            await _metric(
                client,
                base_url,
                "Chamadas/min",
                LLM_CALLS_PER_MIN_QUERY,
                "per_minute",
            ),
            await _metric(
                client,
                base_url,
                "Falhas/min",
                LLM_FAILURES_PER_MIN_QUERY,
                "per_minute",
            ),
            await _metric(
                client,
                base_url,
                "Tokens/s",
                LLM_TOTAL_TOKENS_RATE_QUERY,
                "tokens_per_second",
            ),
            await _metric(
                client,
                base_url,
                "TTFT médio",
                LLM_TTFT_AVG_QUERY,
                "seconds",
            ),
            await _metric(
                client,
                base_url,
                "Duração média",
                LLM_DURATION_AVG_QUERY,
                "seconds",
            ),
            await _metric(
                client,
                base_url,
                "Custo/min",
                LLM_COST_PER_MIN_QUERY,
                "currency_per_minute",
            ),
            await _vector_metric(
                client,
                base_url,
                "Chamadas por agente",
                "sum by (agent) (acessilia_llm_calls_total)",
                "count",
            ),
            await _vector_metric(
                client,
                base_url,
                "Falhas por agente",
                "sum by (agent) (acessilia_llm_failures_total)",
                "count",
            ),
            await _vector_metric(
                client,
                base_url,
                "Duração média por agente",
                (
                    "sum by (agent) (acessilia_llm_duration_seconds_sum) "
                    "/ clamp_min(sum by (agent) (acessilia_llm_duration_seconds_count), 1)"
                ),
                "seconds",
            ),
            await _vector_metric(
                client,
                base_url,
                "TTFT por modelo",
                (
                    "sum by (agent, model_provider, model) "
                    "(rate(acessilia_llm_time_to_first_token_seconds_sum[5m])) "
                    "/ clamp_min(sum by (agent, model_provider, model) "
                    "(rate(acessilia_llm_time_to_first_token_seconds_count[5m])), 1)"
                ),
                "seconds",
            ),
            await _vector_metric(
                client,
                base_url,
                "Tokens por tipo",
                "sum by (token_type) (acessilia_llm_tokens_total)",
                "tokens",
            ),
            await _vector_metric(
                client,
                base_url,
                "Tokens por agente/tipo",
                "sum by (agent, token_type) (acessilia_llm_tokens_total)",
                "tokens",
            ),
            await _vector_metric(
                client,
                base_url,
                "Custo por agente",
                "sum by (agent, model_provider, model) (acessilia_llm_cost_total)",
                "currency",
            ),
            await _vector_metric(
                client,
                base_url,
                "Prompt/resposta médios",
                (
                    "sum by (agent, content_type) "
                    "(acessilia_llm_content_chars_sum) "
                    "/ clamp_min(sum by (agent, content_type) "
                    "(acessilia_llm_content_chars_count), 1)"
                ),
                "chars",
            ),
            await _vector_metric(
                client,
                base_url,
                "Modelos observados",
                "acessilia_llm_model_info",
                "state",
            ),
        ],
    }
    return {"available": available, "groups": groups}


async def _read_loki(client: httpx.AsyncClient, base_url: str) -> dict[str, Any]:
    try:
        response = await client.get(
            f"{base_url}/loki/api/v1/query_range",
            params={
                "query": '{job="acessilia"}',
                "limit": "80",
                "direction": "backward",
            },
        )
        response.raise_for_status()
        streams = response.json().get("data", {}).get("result", [])
    except Exception:
        return {"available": False, "entries": []}

    entries: list[dict[str, Any]] = []
    for stream in streams:
        labels = stream.get("stream", {})
        for timestamp_ns, line in stream.get("values", []):
            entries.append(
                {
                    "time": _loki_timestamp(timestamp_ns),
                    "line": line,
                    "level": labels.get("level", ""),
                    "module": labels.get("module", ""),
                    "format": labels.get("format", ""),
                }
            )
    entries.sort(key=lambda item: item["time"], reverse=True)
    return {"available": True, "entries": entries[:80]}


async def _read_metric_definitions(
    client: httpx.AsyncClient,
    base_url: str,
    definitions: list[dict[str, str]],
) -> list[dict[str, Any]]:
    return list(
        await asyncio.gather(
            *[
                _metric(
                    client,
                    base_url,
                    definition["label"],
                    definition["query"],
                    definition["unit"],
                    key=definition["key"],
                )
                for definition in definitions
            ]
        )
    )


async def _read_timeseries(
    client: httpx.AsyncClient,
    base_url: str,
    range_seconds: int,
    step_seconds: int,
) -> list[dict[str, Any]]:
    end = time.time()
    start = end - range_seconds
    results = await asyncio.gather(
        *[
            _prometheus_range_result(
                client,
                base_url,
                definition["query"],
                start=start,
                end=end,
                step=step_seconds,
            )
            for definition in TIMESERIES_METRICS
        ]
    )
    return [
        _series_payload(definition, result)
        for definition, result in zip(TIMESERIES_METRICS, results, strict=True)
    ]


def _series_payload(
    definition: dict[str, str],
    result: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    points: list[dict[str, float]] = []
    if result:
        for timestamp, raw_value in result[0].get("values", []):
            try:
                points.append(
                    {
                        "time": float(timestamp),
                        "value": float(raw_value),
                    }
                )
            except (TypeError, ValueError):
                continue
    return {
        "key": definition["key"],
        "label": definition["label"],
        "unit": definition["unit"],
        "points": points,
    }


async def _metric(
    client: httpx.AsyncClient,
    base_url: str,
    label: str,
    query: str,
    unit: str,
    key: str | None = None,
) -> dict[str, Any]:
    value = await _prometheus_scalar(client, base_url, query)
    return {"key": key, "label": label, "value": value, "unit": unit, "items": []}


async def _vector_metric(
    client: httpx.AsyncClient,
    base_url: str,
    label: str,
    query: str,
    unit: str,
) -> dict[str, Any]:
    items = await _prometheus_vector(client, base_url, query)
    return {"label": label, "value": None, "unit": unit, "items": items}


async def _prometheus_scalar(
    client: httpx.AsyncClient,
    base_url: str,
    query: str,
) -> float | None:
    result = await _prometheus_result(client, base_url, query)
    if not result:
        return None
    try:
        return float(result[0]["value"][1])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


async def _prometheus_vector(
    client: httpx.AsyncClient,
    base_url: str,
    query: str,
) -> list[dict[str, Any]]:
    result = await _prometheus_result(client, base_url, query)
    items: list[dict[str, Any]] = []
    for row in result or []:
        metric = row.get("metric", {})
        label = _prometheus_label(metric)
        try:
            value = float(row["value"][1])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        items.append({"label": label, "value": value, "metric": metric})
    return items


def _prometheus_label(metric: dict[str, Any]) -> str:
    preferred = [
        "agent",
        "token_type",
        "content_type",
        "model_provider",
        "model",
        "status",
        "stage",
        "format",
        "instance",
    ]
    parts = [str(metric[key]) for key in preferred if metric.get(key)]
    return " / ".join(parts) if parts else "total"


async def _prometheus_result(
    client: httpx.AsyncClient,
    base_url: str,
    query: str,
) -> list[dict[str, Any]] | None:
    try:
        response = await client.get(
            f"{base_url}/api/v1/query",
            params={"query": query},
        )
        response.raise_for_status()
        return response.json().get("data", {}).get("result", [])
    except Exception:
        return None


async def _prometheus_range_result(
    client: httpx.AsyncClient,
    base_url: str,
    query: str,
    start: float,
    end: float,
    step: int,
) -> list[dict[str, Any]] | None:
    try:
        response = await client.get(
            f"{base_url}/api/v1/query_range",
            params={
                "query": query,
                "start": f"{start:.3f}",
                "end": f"{end:.3f}",
                "step": str(step),
            },
        )
        response.raise_for_status()
        return response.json().get("data", {}).get("result", [])
    except Exception:
        return None


async def _json_or_none(
    client: httpx.AsyncClient,
    base_url: str,
    path: str,
) -> Any | None:
    try:
        response = await client.get(f"{base_url}{path}")
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


async def _is_http_available(
    client: httpx.AsyncClient,
    base_url: str,
    path: str,
) -> bool:
    try:
        response = await client.get(f"{base_url}{path}")
        return response.status_code < 500
    except Exception:
        return False


def _loki_timestamp(timestamp_ns: str) -> str:
    try:
        seconds = int(timestamp_ns) / 1_000_000_000
        return datetime.fromtimestamp(seconds, timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return datetime.now(timezone.utc).isoformat()


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "observability.frontend.app:app",
        host=os.getenv("OBSERVABILITY_FRONTEND_HOST", "127.0.0.1"),
        port=int(os.getenv("OBSERVABILITY_FRONTEND_PORT", "8010")),
        reload=os.getenv("OBSERVABILITY_FRONTEND_RELOAD", "false").lower() == "true",
    )
