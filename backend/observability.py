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
from typing import TYPE_CHECKING

from backend.config.settings import settings
from backend.tools.logger import logger


if TYPE_CHECKING:
    from fastapi import FastAPI


_tracing_active = False


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
