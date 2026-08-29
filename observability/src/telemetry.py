from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class AgnoPrometheusMetrics:
    calls: Any
    failures: Any
    duration: Any
    ttft: Any
    tokens: Any
    tool_calls: Any
    reasoning_steps: Any
    cost: Any
    content_chars: Any


_agno_prom_metrics: AgnoPrometheusMetrics | None = None
_otel_configured = False


def configure_opentelemetry(
    *,
    service_name: str,
    otlp_endpoint: str = "",
    otlp_headers: str = "",
) -> bool:
    global _otel_configured
    if _otel_configured or not otlp_endpoint:
        return _otel_configured

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        exporter_kwargs: dict[str, Any] = {"endpoint": otlp_endpoint}
        if otlp_headers:
            exporter_kwargs["headers"] = _parse_otlp_headers(otlp_headers)
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(**exporter_kwargs)))
        trace.set_tracer_provider(provider)
        _otel_configured = True
    except Exception:
        return False

    return True


def record_observability_span(
    name: str,
    *,
    attributes: dict[str, Any],
    status: str = "completed",
) -> None:
    try:
        from opentelemetry import trace

        tracer = trace.get_tracer("observability")
        with tracer.start_as_current_span(name) as span:
            for key, value in attributes.items():
                if value is not None:
                    span.set_attribute(key, value)
            span.set_attribute("run.status", status)
    except Exception:
        return


def get_agno_prom_metrics() -> AgnoPrometheusMetrics | None:
    global _agno_prom_metrics
    if _agno_prom_metrics is not None:
        return _agno_prom_metrics
    try:
        from prometheus_client import Counter, Histogram

        _agno_prom_metrics = AgnoPrometheusMetrics(
            calls=Counter(
                "acessilia_agno_chat_calls_total",
                "Total de chamadas de chat para entidades Agno.",
                ["entity_type", "entity_id", "model_provider", "model", "status"],
            ),
            failures=Counter(
                "acessilia_agno_chat_failures_total",
                "Total de falhas em chamadas de chat Agno.",
                ["entity_type", "entity_id", "model_provider", "model", "error_type"],
            ),
            duration=Histogram(
                "acessilia_agno_chat_duration_seconds",
                "Duração das execuções de chat Agno em segundos.",
                ["entity_type", "entity_id", "model_provider", "model", "status"],
                buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0),
            ),
            ttft=Histogram(
                "acessilia_agno_chat_ttft_seconds",
                "Time To First Token das respostas de chat Agno.",
                ["entity_type", "entity_id", "model_provider", "model"],
                buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0),
            ),
            tokens=Counter(
                "acessilia_agno_chat_tokens_total",
                "Tokens consumidos nas conversas com Agno por tipo.",
                ["entity_type", "entity_id", "model_provider", "model", "token_type"],
            ),
            tool_calls=Counter(
                "acessilia_agno_chat_tool_calls_total",
                "Total de chamadas de ferramentas executadas por agentes Agno.",
                ["entity_type", "entity_id", "tool_name", "status"],
            ),
            reasoning_steps=Counter(
                "acessilia_agno_chat_reasoning_steps_total",
                "Total de passos/eventos de raciocínio observados.",
                ["entity_type", "entity_id", "model_provider", "model"],
            ),
            cost=Counter(
                "acessilia_agno_chat_cost_total",
                "Custo acumulado reportado pelo provedor para conversas Agno.",
                ["entity_type", "entity_id", "model_provider", "model"],
            ),
            content_chars=Histogram(
                "acessilia_agno_chat_content_chars",
                "Tamanho do conteúdo de mensagens em caracteres.",
                ["entity_type", "entity_id", "content_type"],
                buckets=(50, 150, 500, 1500, 5000, 15000, 50000),
            ),
        )
    except Exception:
        return None
    return _agno_prom_metrics


def record_agno_chat_metrics(
    *,
    entity_type: str,
    entity_id: str,
    model_provider: str,
    model: str,
    status: str,
    duration_seconds: float,
    ttft_seconds: float | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    reasoning_tokens: int = 0,
    cost: float | None = None,
    error_type: str = "",
    tool_calls_list: list[dict[str, Any]] | None = None,
    reasoning_steps: int = 0,
    user_chars: int = 0,
    assistant_chars: int = 0,
) -> None:
    prom = get_agno_prom_metrics()
    if prom is None:
        return

    safe_entity_type = entity_type or "agent"
    safe_entity_id = entity_id or "unknown"
    safe_provider = model_provider or "unknown"
    safe_model = model or "unknown"
    safe_status = status or "completed"

    prom.calls.labels(
        entity_type=safe_entity_type,
        entity_id=safe_entity_id,
        model_provider=safe_provider,
        model=safe_model,
        status=safe_status,
    ).inc()

    if status == "error":
        prom.failures.labels(
            entity_type=safe_entity_type,
            entity_id=safe_entity_id,
            model_provider=safe_provider,
            model=safe_model,
            error_type=error_type or "UnknownError",
        ).inc()

    prom.duration.labels(
        entity_type=safe_entity_type,
        entity_id=safe_entity_id,
        model_provider=safe_provider,
        model=safe_model,
        status=safe_status,
    ).observe(max(duration_seconds, 0.0))

    if ttft_seconds is not None and ttft_seconds > 0:
        prom.ttft.labels(
            entity_type=safe_entity_type,
            entity_id=safe_entity_id,
            model_provider=safe_provider,
            model=safe_model,
        ).observe(ttft_seconds)

    if input_tokens > 0:
        prom.tokens.labels(
            entity_type=safe_entity_type,
            entity_id=safe_entity_id,
            model_provider=safe_provider,
            model=safe_model,
            token_type="input",
        ).inc(input_tokens)

    if output_tokens > 0:
        prom.tokens.labels(
            entity_type=safe_entity_type,
            entity_id=safe_entity_id,
            model_provider=safe_provider,
            model=safe_model,
            token_type="output",
        ).inc(output_tokens)

    if reasoning_tokens > 0:
        prom.tokens.labels(
            entity_type=safe_entity_type,
            entity_id=safe_entity_id,
            model_provider=safe_provider,
            model=safe_model,
            token_type="reasoning",
        ).inc(reasoning_tokens)

    if cost is not None and cost > 0:
        prom.cost.labels(
            entity_type=safe_entity_type,
            entity_id=safe_entity_id,
            model_provider=safe_provider,
            model=safe_model,
        ).inc(cost)

    if reasoning_steps > 0:
        prom.reasoning_steps.labels(
            entity_type=safe_entity_type,
            entity_id=safe_entity_id,
            model_provider=safe_provider,
            model=safe_model,
        ).inc(reasoning_steps)

    if user_chars > 0:
        prom.content_chars.labels(
            entity_type=safe_entity_type,
            entity_id=safe_entity_id,
            content_type="user_prompt",
        ).observe(user_chars)

    if assistant_chars > 0:
        prom.content_chars.labels(
            entity_type=safe_entity_type,
            entity_id=safe_entity_id,
            content_type="assistant_response",
        ).observe(assistant_chars)

    for tc in tool_calls_list or []:
        tool_name = str(tc.get("tool_name") or "unknown")
        tc_status = str(tc.get("status") or "completed")
        prom.tool_calls.labels(
            entity_type=safe_entity_type,
            entity_id=safe_entity_id,
            tool_name=tool_name,
            status=tc_status,
        ).inc()


def _parse_otlp_headers(raw_headers: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for part in raw_headers.split(","):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        if key:
            headers[key] = value.strip()
    return headers
