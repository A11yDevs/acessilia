"""Faz a aplicação em execução relatar o que está acontecendo dentro dela.

Duas coisas, ambas desligadas por padrão:

- `setup_tracing()` liga o envio de traces das chamadas de LLM (prompt, resposta,
  tokens, custo, duração) para o Langfuse ou outro coletor OpenTelemetry.
- `setup_metrics()` expõe /metrics para o Prometheus ler contagem de requisições,
  status HTTP e latência.

É código de produção, não de teste: roda junto com o servidor e observa o tráfego
real dos usuários. Teste de carga (tests/testes_de_carga) é o contrário — gera
tráfego artificial para medir limite. Os dois se combinam bem, mas são coisas
diferentes, e isto aqui funciona sozinho, sem teste nenhum rodando.

Sobre `telemetry=False` nos agentes: aquele parâmetro controla a analítica de
produto do próprio Agno (dados anônimos de uso enviados para os servidores deles) e
não tem relação com OpenTelemetry. Quem gera os spans é o AgnoInstrumentor, que
instrumenta a biblioteca por fora e funciona independente dele.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from backend.config.settings import settings
from backend.tools.logger import logger


if TYPE_CHECKING:
    from fastapi import FastAPI


_tracing_active = False
_domain_metrics: "_DomainMetrics | None" = None
_KNOWN_SOURCES = {"api", "web", "telegram", "cli", "load-test"}
_KNOWN_MODES = {"normal", "medio", "detalhado", "baixo", "ocr"}


@dataclass
class _DomainMetrics:
    queue_size: object
    jobs_active: object
    jobs_total: object
    conversion_duration: object
    pipeline_errors: object
    exports_total: object
    output_bytes: object
    llm_calls: object
    llm_failures: object
    llm_duration: object
    llm_tokens: object
    llm_cost: object
    llm_ttft: object
    llm_content_chars: object
    llm_model_info: object


def _get_domain_metrics() -> "_DomainMetrics | None":
    global _domain_metrics

    if not settings.enable_metrics:
        return None

    if _domain_metrics is not None:
        return _domain_metrics

    try:
        from prometheus_client import Counter, Gauge, Histogram
    except ImportError:
        return None

    try:
        _domain_metrics = _DomainMetrics(
            queue_size=Gauge(
                "acessilia_queue_size",
                "Quantidade de jobs aguardando na fila unificada.",
            ),
            jobs_active=Gauge(
                "acessilia_jobs_active",
                "Quantidade de jobs em processamento.",
                ["source", "mode"],
            ),
            jobs_total=Counter(
                "acessilia_jobs_total",
                "Jobs observados por status.",
                ["status", "source", "mode"],
            ),
            conversion_duration=Histogram(
                "acessilia_conversion_duration_seconds",
                "Tempo de processamento dos jobs da API.",
                ["source", "mode", "status"],
                buckets=(1, 5, 15, 30, 60, 120, 300, 600, 1200, 3600),
            ),
            pipeline_errors=Counter(
                "acessilia_pipeline_errors_total",
                "Erros observados por etapa da pipeline.",
                ["stage", "source", "mode"],
            ),
            exports_total=Counter(
                "acessilia_exports_total",
                "Arquivos exportados por formato.",
                ["format", "source", "mode"],
            ),
            output_bytes=Histogram(
                "acessilia_output_bytes",
                "Tamanho dos outputs gerados pela pipeline.",
                ["format", "source", "mode"],
                buckets=(
                    1_024,
                    10_240,
                    102_400,
                    1_048_576,
                    5_242_880,
                    10_485_760,
                    52_428_800,
                ),
            ),
            llm_calls=Counter(
                "acessilia_llm_calls_total",
                "Chamadas de LLM por agente.",
                ["agent"],
            ),
            llm_failures=Counter(
                "acessilia_llm_failures_total",
                "Falhas em chamadas de LLM por agente.",
                ["agent"],
            ),
            llm_duration=Histogram(
                "acessilia_llm_duration_seconds",
                "Tempo de chamadas de LLM por agente.",
                ["agent", "status"],
                buckets=(0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600),
            ),
            llm_tokens=Counter(
                "acessilia_llm_tokens_total",
                "Tokens consumidos por agente, modelo e tipo.",
                ["agent", "model_provider", "model", "token_type"],
            ),
            llm_cost=Counter(
                "acessilia_llm_cost_total",
                "Custo reportado pelo provedor por agente e modelo.",
                ["agent", "model_provider", "model"],
            ),
            llm_ttft=Histogram(
                "acessilia_llm_time_to_first_token_seconds",
                "Tempo ate o primeiro token reportado pelo modelo.",
                ["agent", "model_provider", "model"],
                buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
            ),
            llm_content_chars=Histogram(
                "acessilia_llm_content_chars",
                "Tamanho de prompts e respostas de LLM em caracteres.",
                ["agent", "model_provider", "model", "content_type"],
                buckets=(100, 500, 1_000, 2_500, 5_000, 10_000, 25_000, 50_000),
            ),
            llm_model_info=Gauge(
                "acessilia_llm_model_info",
                "Modelo observado em chamadas de LLM.",
                ["agent", "model_provider", "model"],
            ),
        )
    except ValueError:
        # Pode acontecer em reload de testes quando o registry global do Prometheus
        # já recebeu as métricas. Manter no-op é mais seguro que derrubar a API.
        logger.warning("Métricas de domínio já registradas; mantendo coleta inativa.")
        return None

    return _domain_metrics


def set_queue_size(size: int) -> None:
    metrics = _get_domain_metrics()
    if metrics is not None:
        metrics.queue_size.set(max(size, 0))


def record_job_status(status: str, source: str = "api", mode: str = "normal") -> None:
    metrics = _get_domain_metrics()
    if metrics is not None:
        source = _safe_source(source)
        mode = _safe_mode(mode)
        metrics.jobs_total.labels(status=status, source=source, mode=mode).inc()


def record_job_started(source: str = "api", mode: str = "normal") -> None:
    metrics = _get_domain_metrics()
    if metrics is None:
        return
    source = _safe_source(source)
    mode = _safe_mode(mode)
    metrics.jobs_active.labels(source=source, mode=mode).inc()
    metrics.jobs_total.labels(status="processing", source=source, mode=mode).inc()


def record_job_finished(
    status: str,
    source: str = "api",
    mode: str = "normal",
    duration_seconds: float = 0.0,
) -> None:
    metrics = _get_domain_metrics()
    if metrics is None:
        return
    source = _safe_source(source)
    mode = _safe_mode(mode)
    metrics.jobs_active.labels(source=source, mode=mode).dec()
    metrics.jobs_total.labels(status=status, source=source, mode=mode).inc()
    metrics.conversion_duration.labels(
        source=source,
        mode=mode,
        status=status,
    ).observe(max(duration_seconds, 0.0))


def record_pipeline_error(
    stage: str,
    source: str = "api",
    mode: str = "normal",
) -> None:
    metrics = _get_domain_metrics()
    if metrics is not None:
        source = _safe_source(source)
        mode = _safe_mode(mode)
        metrics.pipeline_errors.labels(stage=stage, source=source, mode=mode).inc()


def record_export(
    format_name: str,
    output_bytes: int,
    source: str = "api",
    mode: str = "normal",
) -> None:
    metrics = _get_domain_metrics()
    if metrics is None:
        return
    source = _safe_source(source)
    mode = _safe_mode(mode)
    metrics.exports_total.labels(
        format=format_name,
        source=source,
        mode=mode,
    ).inc()
    metrics.output_bytes.labels(
        format=format_name,
        source=source,
        mode=mode,
    ).observe(max(output_bytes, 0))


def record_llm_call(agent: str) -> None:
    metrics = _get_domain_metrics()
    if metrics is not None:
        metrics.llm_calls.labels(agent=agent).inc()


def record_llm_failure(agent: str) -> None:
    metrics = _get_domain_metrics()
    if metrics is not None:
        metrics.llm_failures.labels(agent=agent).inc()


def record_llm_duration(agent: str, status: str, duration_seconds: float) -> None:
    metrics = _get_domain_metrics()
    if metrics is not None:
        metrics.llm_duration.labels(agent=agent, status=status).observe(
            max(duration_seconds, 0.0)
        )


def record_llm_response(
    agent: str,
    response: Any,
    *,
    prompt: str = "",
) -> None:
    """Extrai métricas do RunOutput do Agno sem depender de um provedor específico."""
    metrics = _get_domain_metrics()
    if metrics is None or response is None:
        return

    run_metrics = getattr(response, "metrics", None)
    model_provider, model = _llm_identity(response, run_metrics)

    metrics.llm_model_info.labels(
        agent=agent,
        model_provider=model_provider,
        model=model,
    ).set(1)

    for token_type in (
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "reasoning_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "audio_input_tokens",
        "audio_output_tokens",
        "audio_total_tokens",
    ):
        value = _numeric_attr(run_metrics, token_type)
        if value > 0:
            metrics.llm_tokens.labels(
                agent=agent,
                model_provider=model_provider,
                model=model,
                token_type=token_type.removesuffix("_tokens"),
            ).inc(value)

    cost = _optional_float_attr(run_metrics, "cost")
    if cost is not None and cost > 0:
        metrics.llm_cost.labels(
            agent=agent,
            model_provider=model_provider,
            model=model,
        ).inc(cost)

    ttft = _optional_float_attr(run_metrics, "time_to_first_token")
    if ttft is not None and ttft >= 0:
        metrics.llm_ttft.labels(
            agent=agent,
            model_provider=model_provider,
            model=model,
        ).observe(ttft)

    if prompt:
        metrics.llm_content_chars.labels(
            agent=agent,
            model_provider=model_provider,
            model=model,
            content_type="prompt",
        ).observe(len(prompt))

    content = getattr(response, "content", None)
    if content is not None:
        metrics.llm_content_chars.labels(
            agent=agent,
            model_provider=model_provider,
            model=model,
            content_type="response",
        ).observe(len(str(content)))


def _llm_identity(response: Any, run_metrics: Any) -> tuple[str, str]:
    provider = str(getattr(response, "model_provider", "") or "").strip()
    model = str(getattr(response, "model", "") or "").strip()

    details = getattr(run_metrics, "details", None)
    if isinstance(details, dict):
        for entries in details.values():
            for item in entries or []:
                if isinstance(item, dict):
                    provider = provider or str(item.get("provider", "") or "").strip()
                    model = model or str(item.get("id", "") or "").strip()
                else:
                    provider = provider or str(getattr(item, "provider", "") or "").strip()
                    model = model or str(getattr(item, "id", "") or "").strip()
                if provider or model:
                    break
            if provider or model:
                break

    return _safe_label(provider or "unknown"), _safe_label(model or "unknown")


def _numeric_attr(source: Any, name: str) -> float:
    value = _optional_float_attr(source, name)
    return max(value or 0.0, 0.0)


def _optional_float_attr(source: Any, name: str) -> float | None:
    if source is None:
        return None
    try:
        value = getattr(source, name)
    except Exception:
        return None
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _safe_label(value: str) -> str:
    normalized = str(value or "unknown").strip()
    return normalized[:120] if normalized else "unknown"


def _safe_source(source: str) -> str:
    normalized = str(source or "api").strip().lower()
    return normalized if normalized in _KNOWN_SOURCES else "custom"


def _safe_mode(mode: str) -> str:
    normalized = str(mode or "normal").strip().lower()
    return normalized if normalized in _KNOWN_MODES else "custom"


def _resolve_headers() -> dict[str, str]:
    """Cabeçalhos de autenticação do exporter.

    OTEL_EXPORTER_OTLP_HEADERS tem precedência por ser o padrão do OpenTelemetry e
    atender qualquer coletor. As chaves do Langfuse são um atalho para o caso comum,
    já que ele autentica com Basic auth de public:secret.
    """
    if settings.otlp_headers:
        headers: dict[str, str] = {}
        for pair in settings.otlp_headers.split(","):
            key, _, value = pair.partition("=")
            if key.strip():
                headers[key.strip()] = value.strip()
        return headers

    if settings.langfuse_public_key and settings.langfuse_secret_key:
        credentials = f"{settings.langfuse_public_key}:{settings.langfuse_secret_key}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return {"Authorization": f"Basic {encoded}"}

    return {}


def setup_tracing() -> bool:
    """Instrumenta o runtime para exportar traces dos agentes via OTLP.

    Retorna True se o tracing ficou ativo. Chamar mais de uma vez é seguro: a
    segunda chamada não faz nada, porque instrumentar duas vezes duplicaria spans.

    Falhas aqui nunca derrubam a aplicação. Observabilidade é acessório: se o
    coletor estiver fora do ar ou faltar dependência, o processamento de documento
    tem que seguir normalmente.
    """
    global _tracing_active

    if _tracing_active:
        return True

    if not settings.enable_tracing:
        return False

    if not settings.otlp_endpoint:
        logger.warning(
            "ENABLE_TRACING ativo mas OTEL_EXPORTER_OTLP_ENDPOINT está vazio; "
            "tracing não foi iniciado."
        )
        return False

    try:
        # Importados aqui porque são dependências opcionais (extra "observability").
        from openinference.instrumentation.agno import AgnoInstrumentor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry import trace
    except ImportError as exc:
        logger.warning(
            "Tracing pedido mas as dependências não estão instaladas ({}). "
            "Rode: poetry install --extras observability",
            exc,
        )
        return False

    try:
        provider = TracerProvider(
            resource=Resource.create({"service.name": settings.otel_service_name})
        )
        # Batch em vez de Simple: o Simple exporta a cada span e bloqueia a thread do
        # agente esperando a rede, o que somaria latência a cada chamada de LLM.
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(
                    endpoint=settings.otlp_endpoint,
                    headers=_resolve_headers(),
                )
            )
        )
        trace.set_tracer_provider(provider)
        AgnoInstrumentor().instrument(tracer_provider=provider)
    except Exception as exc:
        logger.warning("Falha ao iniciar o tracing: {}", exc)
        return False

    _tracing_active = True
    logger.info(
        "Tracing ativo | serviço: {} | endpoint: {}",
        settings.otel_service_name,
        settings.otlp_endpoint,
    )
    return True


def setup_metrics(app: "FastAPI") -> bool:
    """Expõe /metrics no formato Prometheus quando ENABLE_METRICS estiver ligado.

    A rota fica fora de /api/v1 porque não faz parte do contrato público da API: é a
    porta de scraping do Prometheus, que por convenção procura /metrics na raiz.

    Retorna True se a rota foi registrada.
    """
    if not settings.enable_metrics:
        return False

    try:
        from prometheus_fastapi_instrumentator import Instrumentator
    except ImportError:
        logger.warning(
            "ENABLE_METRICS ativo mas prometheus-fastapi-instrumentator não está "
            "instalado. Rode: poetry install --extras observability"
        )
        return False

    # instrument() registra o middleware que mede as requisições; expose() cria a
    # rota de leitura. Fora do schema porque não é endpoint de uso do cliente.
    Instrumentator().instrument(app).expose(
        app, endpoint="/metrics", include_in_schema=False
    )
    logger.info("Métricas Prometheus expostas em /metrics")
    return True
