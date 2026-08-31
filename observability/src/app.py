from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
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
from starlette.background import BackgroundTask

from observability.src.correlation import CorrelationContext
from observability.src.dashboard import DashboardService
from observability.src.events import (
    consume_agno_event_buffer,
    sanitize_agno_event_for_console,
)
from observability.src.integrations.agno import AgnoClient
from observability.src.integrations.loki import LokiLogsProvider
from observability.src.integrations.project_api import ProjectApiClient
from observability.src.integrations.prometheus import PrometheusMetricsProvider
from observability.src.metrics_catalog import build_metrics_catalog
from observability.src.settings import ObservabilitySettings
from observability.src.storage.sqlite import (
    create_annotation,
    create_agno_message,
    create_agno_run,
    create_agno_run_event,
    create_agno_tool_call,
    delete_annotation,
    delete_agno_session,
    get_agent_metrics_summary,
    get_agno_run_details,
    get_agno_session_details,
    get_comparative_metrics,
    list_annotations,
    list_agno_runs,
    list_agno_sessions,
    upsert_agno_session,
)
from observability.src.telemetry import (
    configure_opentelemetry,
    get_agno_prom_metrics,
    record_agno_chat_metrics,
    start_observability_span,
)


OBSERVABILITY_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = OBSERVABILITY_DIR / "frontend"
TEMPLATES = Jinja2Templates(directory=str(FRONTEND_DIR / "templates"))


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
    model: str = Field(default="", max_length=200)
    model_provider: str = Field(default="", max_length=200)


def _friendly_agno_error(
    message: str,
    *,
    model_provider: str = "",
    model: str = "",
) -> str:
    lower = message.lower()
    config_markers = (
        "porta-aqui-se-diferente-da-padrao",
        "port could not be cast",
    )
    connection_markers = (
        "all connection attempts failed",
        "connection refused",
        "name or service not known",
        "connecterror",
    )
    if any(marker in lower for marker in config_markers):
        return (
            "Configuração inválida do modelo Agno. Verifique OLLAMA_BASE_URL ou "
            "OPENROUTER_BASE_URL no .env e remova placeholders de exemplo."
        )
    if any(marker in lower for marker in connection_markers):
        provider = model_provider or "LLM"
        model_hint = f" e se o modelo '{model}' existe" if model else ""
        return (
            f"{provider} não está acessível a partir do runtime Agno. "
            f"Verifique se o serviço do modelo está rodando, se a URL está correta{model_hint}."
        )
    return message


def create_app() -> FastAPI:
    settings = ObservabilitySettings.from_env()
    metrics_catalog = build_metrics_catalog(
        metric_prefix=settings.metric_prefix,
        api_job_name=settings.prometheus_api_job,
        observability_job_name=settings.prometheus_observability_job,
    )

    app = FastAPI(title=f"{settings.project_name} Observability", version="1.0.0")
    app.mount(
        "/static",
        StaticFiles(directory=str(FRONTEND_DIR / "static")),
        name="static",
    )

    app.state.settings = settings
    app.state.api_url = settings.api_url
    app.state.prometheus_url = settings.prometheus_url
    app.state.loki_url = settings.loki_url
    app.state.langfuse_url = settings.langfuse_url
    app.state.tempo_url = settings.tempo_url
    app.state.locust_url = settings.locust_url
    app.state.agno_os_url = settings.agno_os_url
    app.state.agno_os_security_key = settings.agno_os_security_key
    app.state.db_path = settings.db_path
    app.state.public_links = settings.public_links
    app.state.store_reasoning = settings.store_reasoning
    app.state.project_api = ProjectApiClient(
        base_url=settings.api_url,
        health_path=settings.api_health_path,
        stats_path=settings.api_stats_path,
        history_path=settings.api_history_path,
    )
    app.state.metrics_provider = PrometheusMetricsProvider(
        base_url=settings.prometheus_url,
        catalog=metrics_catalog,
    )
    app.state.logs_provider = LokiLogsProvider(
        base_url=settings.loki_url,
        query=settings.loki_query,
    )
    app.state.dashboard = DashboardService(
        settings=settings,
        project_api=app.state.project_api,
        metrics_provider=app.state.metrics_provider,
        logs_provider=app.state.logs_provider,
    )

    app.state.otel_enabled = (
        settings.frontend_tracing_enabled
        and configure_opentelemetry(
            service_name=settings.otel_service_name,
            otlp_endpoint=settings.otel_exporter_otlp_endpoint,
            otlp_headers=settings.otel_exporter_otlp_headers,
        )
    )
    get_agno_prom_metrics()

    @app.get("/metrics")
    async def metrics_endpoint() -> Response:
        try:
            from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
            return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
        except Exception:
            return Response(content=b"", media_type="text/plain")

    @app.get("/api/health")
    async def panel_health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": settings.otel_service_name,
            "otel_enabled": app.state.otel_enabled,
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

    @app.get("/api/agno/sessions")
    async def get_sessions(
        entity_type: str | None = None,
        entity_id: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        sessions = list_agno_sessions(
            entity_type=entity_type,
            entity_id=entity_id,
            limit=limit,
            db_path=app.state.db_path,
        )
        return {"sessions": sessions}

    @app.get("/api/agno/sessions/{session_id}")
    async def get_session_details(session_id: str) -> dict[str, Any]:
        details = get_agno_session_details(session_id, db_path=app.state.db_path)
        if not details:
            raise HTTPException(status_code=404, detail="Sessão não encontrada.")
        return details

    @app.delete("/api/agno/sessions/{session_id}")
    async def delete_session(session_id: str) -> dict[str, Any]:
        deleted = delete_agno_session(session_id, db_path=app.state.db_path)
        return {"deleted": deleted}

    @app.get("/api/investigations/runs")
    async def investigation_runs(
        status: str = Query(default="", pattern="^(completed|error|cancelled)?$"),
        search: str = Query(default="", max_length=200),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        runs = list_agno_runs(
            status=status,
            search=search,
            limit=limit,
            db_path=app.state.db_path,
        )
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "items": [{"source": "agno", **run} for run in runs],
        }

    @app.get("/api/investigations/runs/{run_id}")
    async def investigation_run_details(run_id: str) -> dict[str, Any]:
        details = get_agno_run_details(run_id, db_path=app.state.db_path)
        if not details:
            raise HTTPException(status_code=404, detail="Execução não encontrada.")
        return {"source": "agno", **details}

    @app.get("/api/agno/metrics/summary")
    async def get_agent_summary(
        entity_id: str,
        entity_type: str = "agent",
        days: int = Query(default=30, ge=1, le=365),
    ) -> dict[str, Any]:
        return get_agent_metrics_summary(
            entity_type=entity_type,
            entity_id=entity_id,
            days=days,
            db_path=app.state.db_path,
        )

    @app.get("/api/agno/metrics/compare")
    async def get_comparison(
        group_by: str = Query(default="agent", pattern="^(agent|model)$"),
        days: int = Query(default=30, ge=1, le=365),
    ) -> dict[str, Any]:
        items = get_comparative_metrics(
            group_by=group_by,
            days=days,
            db_path=app.state.db_path,
        )
        return {"group_by": group_by, "days": days, "items": items}

    @app.get("/api/agno/metrics/report")
    async def get_metrics_report(
        days: int = Query(default=30, ge=1, le=365),
    ) -> dict[str, Any]:
        agents = get_comparative_metrics(group_by="agent", days=days, db_path=app.state.db_path)
        models = get_comparative_metrics(group_by="model", days=days, db_path=app.state.db_path)

        # Gera relatório em Markdown
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines = [
            f"# Relatório de Observabilidade Agno — {now_str}",
            "",
            f"**Janela de análise:** Últimos {days} dias",
            "",
            "## Comparativo por Agente",
            "",
            "| Agente | Chamadas | Sucesso (%) | Duração Média | TTFT Médio | Tokens Médios | Custo Total |",
            "|---|---|---|---|---|---|---|",
        ]
        for a in agents:
            dur = f"{a['avg_duration']}s" if a['avg_duration'] is not None else "-"
            ttft = f"{a['avg_ttft']}s" if a['avg_ttft'] is not None else "-"
            cost = f"US$ {a['total_cost']:.6f}" if a['total_cost'] is not None else "Sem dado"
            lines.append(
                f"| `{a['group_key']}` | {a['total_calls']} | {a['success_rate']}% | {dur} | {ttft} | {a['avg_tokens']} | {cost} |"
            )

        lines.extend([
            "",
            "## Comparativo por Modelo",
            "",
            "| Modelo | Provedor | Chamadas | Sucesso (%) | Duração Média | TTFT Médio | Tokens Médios | Custo Total |",
            "|---|---|---|---|---|---|---|---|",
        ])
        for m in models:
            dur = f"{m['avg_duration']}s" if m['avg_duration'] is not None else "-"
            ttft = f"{m['avg_ttft']}s" if m['avg_ttft'] is not None else "-"
            cost = f"US$ {m['total_cost']:.6f}" if m['total_cost'] is not None else "Sem dado"
            prov = m.get('model_provider') or '-'
            lines.append(
                f"| `{m['group_key']}` | {prov} | {m['total_calls']} | {m['success_rate']}% | {dur} | {ttft} | {m['avg_tokens']} | {cost} |"
            )

        report_md = "\n".join(lines)
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "markdown": report_md,
            "agents": agents,
            "models": models,
        }

    @app.post("/api/agno/runs")
    async def agno_run(payload: AgnoRunPayload) -> StreamingResponse:
        agno = AgnoClient(
            app.state.agno_os_url,
            app.state.agno_os_security_key,
        )

        session_id = payload.session_id.strip() or f"ses_{uuid.uuid4().hex[:12]}"
        correlation = CorrelationContext.for_agno_run(
            entity_type=payload.entity_type,
            entity_id=payload.entity_id,
            session_id=session_id,
        )
        run_id = correlation.run_id
        db_path = app.state.db_path

        def attach_correlation(chunk_data: dict[str, Any]) -> dict[str, Any]:
            enriched = dict(chunk_data)
            if enriched.get("run_id") and enriched["run_id"] != correlation.run_id:
                enriched["agentos_run_id"] = str(enriched["run_id"])
            if enriched.get("session_id") and enriched["session_id"] != session_id:
                enriched["agentos_session_id"] = str(enriched["session_id"])
            enriched.update(correlation.event_fields())
            return enriched

        # Garante sessão e mensagem do usuário registradas
        upsert_agno_session(
            session_id=session_id,
            entity_type=payload.entity_type,
            entity_id=payload.entity_id,
            model=payload.model,
            model_provider=payload.model_provider,
            db_path=db_path,
        )
        create_agno_message(
            session_id=session_id,
            role="user",
            content=payload.message,
            run_id=run_id,
            db_path=db_path,
        )
        run_span = start_observability_span(
            "agno.run",
            attributes={
                "run_id": correlation.run_id,
                "session_id": correlation.session_id,
                "entity_type": correlation.entity_type,
                "entity_id": correlation.entity_id,
            },
        )
        correlation = correlation.with_trace_id(run_span.trace_id)

        async def stream() -> Any:
            t0 = time.perf_counter()
            first_token_time: float | None = None
            full_assistant_text = ""
            run_status = "completed"
            error_message = ""
            error_type = ""

            input_tokens = 0
            output_tokens = 0
            total_tokens = 0
            reasoning_tokens = 0
            cache_read_tokens = 0
            cache_write_tokens = 0
            cost: float | None = None
            detected_model = payload.model
            detected_provider = payload.model_provider

            events_collected: list[dict[str, Any]] = []
            tool_calls_collected: list[dict[str, Any]] = []
            reasoning_steps_count = 0
            event_buffer = ""

            def collect_event(chunk_data: dict[str, Any]) -> None:
                nonlocal first_token_time
                nonlocal full_assistant_text
                nonlocal reasoning_steps_count
                nonlocal input_tokens
                nonlocal output_tokens
                nonlocal total_tokens
                nonlocal reasoning_tokens
                nonlocal cache_read_tokens
                nonlocal cache_write_tokens
                nonlocal cost
                nonlocal detected_model
                nonlocal detected_provider
                nonlocal run_status
                nonlocal error_type
                nonlocal error_message

                event_name = chunk_data.get("event") or "RunEvent"

                data_obj = chunk_data
                if "data" in chunk_data and isinstance(chunk_data["data"], dict):
                    data_obj = chunk_data["data"]

                is_content_event = event_name in ("RunContent", "TeamRunContent")
                is_completion_event = (
                    event_name.endswith("Completed")
                    and "ToolCall" not in event_name
                    and "Reasoning" not in event_name
                )

                if first_token_time is None and (
                    is_content_event
                    or (is_completion_event and data_obj.get("content"))
                ):
                    first_token_time = time.perf_counter()

                if (
                    (is_content_event or is_completion_event)
                    and "content" in data_obj
                    and data_obj["content"] is not None
                ):
                    cnt = data_obj["content"]
                    if isinstance(cnt, str):
                        if is_content_event:
                            full_assistant_text += cnt
                        elif not full_assistant_text:
                            full_assistant_text = cnt

                if "reasoning" in event_name.lower() or "reasoning" in data_obj:
                    reasoning_steps_count += 1

                is_terminal_tool_event = (
                    "ToolCall" in event_name
                    and (
                        event_name.endswith("Completed")
                        or event_name.endswith("Error")
                        or event_name == "ToolCall"
                    )
                )
                if is_terminal_tool_event:
                    tc_name = data_obj.get("tool_name") or data_obj.get("name") or "tool"
                    tc_args = data_obj.get("tool_args") or data_obj.get("args") or {}
                    tc_res = data_obj.get("tool_result") or data_obj.get("result")
                    tc_status = "error" if "Error" in event_name else "completed"
                    tool_calls_collected.append(
                        {
                            "tool_name": str(tc_name),
                            "tool_args": tc_args,
                            "tool_result": tc_res,
                            "status": tc_status,
                        }
                    )

                usage = data_obj.get("usage") or data_obj.get("metrics") or {}
                if usage:
                    input_tokens = int(
                        usage.get("input_tokens")
                        or usage.get("prompt_tokens")
                        or input_tokens
                    )
                    output_tokens = int(
                        usage.get("output_tokens")
                        or usage.get("completion_tokens")
                        or output_tokens
                    )
                    total_tokens = int(usage.get("total_tokens") or total_tokens)
                    reasoning_tokens = int(
                        usage.get("reasoning_tokens") or reasoning_tokens
                    )
                    cache_read_tokens = int(
                        usage.get("cache_read_tokens") or cache_read_tokens
                    )
                    cache_write_tokens = int(
                        usage.get("cache_write_tokens") or cache_write_tokens
                    )
                    if "cost" in usage and usage["cost"] is not None:
                        try:
                            cost = float(usage["cost"])
                        except (ValueError, TypeError):
                            pass

                if "model" in data_obj and isinstance(data_obj["model"], str) and data_obj["model"]:
                    detected_model = data_obj["model"]
                if "provider" in data_obj and isinstance(data_obj["provider"], str) and data_obj["provider"]:
                    detected_provider = data_obj["provider"]

                if "Error" in event_name:
                    run_status = "error"
                    error_type = event_name
                    raw_error_message = str(
                        data_obj.get("content")
                        or data_obj.get("error")
                        or "Erro na execução"
                    )
                    error_message = _friendly_agno_error(
                        raw_error_message,
                        model_provider=detected_provider,
                        model=detected_model,
                    )
                    data_obj["content"] = error_message
                    data_obj["error"] = error_message

                events_collected.append(
                    {
                        "event_name": event_name,
                        "event_data": data_obj,
                    }
                )

            try:
                with run_span.activate():
                    async for raw_chunk in agno.stream_run(
                        entity_type=payload.entity_type,
                        entity_id=payload.entity_id,
                        message=payload.message,
                        session_id=session_id,
                    ):
                        event_buffer += raw_chunk.decode("utf-8", errors="replace")
                        parsed_events, event_buffer = consume_agno_event_buffer(
                            event_buffer
                        )
                        for chunk_data in parsed_events:
                            chunk_data = attach_correlation(
                                sanitize_agno_event_for_console(
                                    chunk_data,
                                    store_full_reasoning=app.state.store_reasoning,
                                )
                            )
                            collect_event(chunk_data)
                            yield (
                                json.dumps(chunk_data, ensure_ascii=False) + "\n"
                            ).encode("utf-8")

                if event_buffer.strip():
                    parsed_events, event_buffer = consume_agno_event_buffer(
                        f"{event_buffer}\n\n"
                    )
                    for chunk_data in parsed_events:
                        chunk_data = attach_correlation(
                            sanitize_agno_event_for_console(
                                chunk_data,
                                store_full_reasoning=app.state.store_reasoning,
                            )
                        )
                        collect_event(chunk_data)
                        yield (
                            json.dumps(chunk_data, ensure_ascii=False) + "\n"
                        ).encode("utf-8")

            except asyncio.CancelledError:
                run_status = "cancelled"
                error_type = "CancelledError"
                error_message = "Stream encerrado antes da conclusão."
                raise
            except Exception as exc:
                run_status = "error"
                error_type = type(exc).__name__
                error_message = _friendly_agno_error(
                    str(exc),
                    model_provider=detected_provider,
                    model=detected_model,
                )
                err_chunk = {
                    "event": "RunError",
                    **correlation.event_fields(),
                    "content": error_message,
                    "created_at": int(time.time()),
                }
                yield (json.dumps(err_chunk, ensure_ascii=False) + "\n").encode("utf-8")

            finally:
                duration_seconds = time.perf_counter() - t0
                ttft_seconds = (first_token_time - t0) if first_token_time else None
                if not total_tokens:
                    total_tokens = input_tokens + output_tokens

                # Persiste run no SQLite
                create_agno_run(
                    run_id=run_id,
                    session_id=session_id,
                    entity_type=payload.entity_type,
                    entity_id=payload.entity_id,
                    model=detected_model,
                    model_provider=detected_provider,
                    status=run_status,
                    duration_seconds=duration_seconds,
                    ttft_seconds=ttft_seconds,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    reasoning_tokens=reasoning_tokens,
                    cache_read_tokens=cache_read_tokens,
                    cache_write_tokens=cache_write_tokens,
                    cost=cost,
                    error_type=error_type,
                    error=error_message,
                    trace_id=correlation.trace_id,
                    db_path=db_path,
                )

                # Persiste resposta do assistente
                if full_assistant_text or error_message:
                    resp_content = full_assistant_text if run_status != "error" else (full_assistant_text or error_message)
                    create_agno_message(
                        session_id=session_id,
                        role="assistant",
                        content=resp_content,
                        run_id=run_id,
                        db_path=db_path,
                    )

                # Persiste eventos
                for ev in events_collected:
                    create_agno_run_event(
                        run_id=run_id,
                        session_id=session_id,
                        event_name=ev["event_name"],
                        event_data=ev["event_data"],
                        db_path=db_path,
                        store_full_reasoning=app.state.store_reasoning,
                    )

                # Persiste tool calls
                for tc in tool_calls_collected:
                    create_agno_tool_call(
                        run_id=run_id,
                        session_id=session_id,
                        tool_name=tc["tool_name"],
                        tool_args=tc["tool_args"],
                        tool_result=tc["tool_result"],
                        status=tc["status"],
                        db_path=db_path,
                    )

                # Emite métricas no Prometheus com labels seguras
                record_agno_chat_metrics(
                    entity_type=payload.entity_type,
                    entity_id=payload.entity_id,
                    model_provider=detected_provider,
                    model=detected_model,
                    status=run_status,
                    duration_seconds=duration_seconds,
                    ttft_seconds=ttft_seconds,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    reasoning_tokens=reasoning_tokens,
                    cost=cost,
                    error_type=error_type,
                    tool_calls_list=tool_calls_collected,
                    reasoning_steps=reasoning_steps_count,
                    user_chars=len(payload.message),
                    assistant_chars=len(full_assistant_text),
                )
                run_span.finish(
                    status=run_status,
                    error=error_message,
                    attributes={
                        **correlation.attributes(),
                        "model": detected_model,
                        "model_provider": detected_provider,
                        "duration_seconds": duration_seconds,
                        "ttft_seconds": ttft_seconds,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "total_tokens": total_tokens,
                        "reasoning_tokens": reasoning_tokens,
                        "cost": cost,
                        "error_type": error_type,
                    },
                )

                # Notifica conclusão com resumo das métricas registradas
                final_meta = {
                    "event": "RunFinished",
                    "trace_id": correlation.trace_id,
                    "run_id": run_id,
                    "session_id": session_id,
                    "status": run_status,
                    "duration_seconds": round(duration_seconds, 3),
                    "ttft_seconds": round(ttft_seconds, 3) if ttft_seconds else None,
                    "tokens": {
                        "input": input_tokens,
                        "output": output_tokens,
                        "total": total_tokens,
                        "reasoning": reasoning_tokens,
                    },
                    "cost": cost,
                }
                yield ("\n" + json.dumps(final_meta)).encode("utf-8")

        return StreamingResponse(
            stream(),
            media_type="application/x-ndjson",
            background=BackgroundTask(
                run_span.finish,
                status="cancelled",
                error="Stream encerrado antes da conclusão.",
            ),
        )


    @app.get("/api/logs")
    async def logs(
        search: str = Query(default="", max_length=500),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        timeout = httpx.Timeout(8.0, connect=2.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            result = await app.state.logs_provider.entries(
                client,
                search=search,
                limit=limit,
            )
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            **result,
        }

    @app.get("/api/snapshot")
    async def snapshot() -> dict[str, Any]:
        timeout = httpx.Timeout(6.0, connect=2.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            payload = await app.state.dashboard.snapshot(client)
        payload["annotations"] = list_annotations(app.state.db_path, limit=20)
        return payload

    @app.get("/api/realtime")
    async def realtime() -> dict[str, Any]:
        timeout = httpx.Timeout(4.0, connect=1.5)
        async with httpx.AsyncClient(timeout=timeout) as client:
            metrics = await app.state.metrics_provider.realtime(client)
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
            series = await app.state.metrics_provider.timeseries(
                client,
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
    async def annotations(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
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


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "observability.src.app:app",
        host=os.getenv("OBSERVABILITY_FRONTEND_HOST", "127.0.0.1"),
        port=int(os.getenv("OBSERVABILITY_FRONTEND_PORT", "8010")),
        reload=os.getenv("OBSERVABILITY_FRONTEND_RELOAD", "false").lower() == "true",
    )
