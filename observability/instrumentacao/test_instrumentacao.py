"""Testes da camada de observabilidade opt-in.

Cobre:
- setup_tracing(): permanece inerte quando desligado ou mal configurado
- _resolve_headers(): precedência entre OTLP headers e chaves do Langfuse
- /metrics: só existe quando ENABLE_METRICS está ligado

O foco é garantir que nada disso interfere no runtime quando está desligado, que é
o estado padrão e o que roda em produção hoje.
"""
from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest

from backend.config.settings import _observability_bool_from_env_alias, settings
from backend import observability


@pytest.fixture(autouse=True)
def _reset_tracing_state():
    """Zera o guard de idempotência entre os testes.

    setup_tracing() marca um global para não instrumentar duas vezes; sem resetar,
    um teste contaminaria o seguinte.
    """
    observability._tracing_active = False
    observability._domain_metrics = None
    yield
    observability._tracing_active = False
    observability._domain_metrics = None


# ---------------------------------------------------------------------------
# setup_tracing
# ---------------------------------------------------------------------------


def test_tracing_is_off_by_default(monkeypatch):
    monkeypatch.setattr(settings, "enable_tracing", False)
    assert observability.setup_tracing() is False


def test_tracing_without_endpoint_does_not_start(monkeypatch):
    """Ligar a flag sem endpoint não pode derrubar nem instrumentar pela metade."""
    monkeypatch.setattr(settings, "enable_tracing", True)
    monkeypatch.setattr(settings, "otlp_endpoint", "")
    assert observability.setup_tracing() is False


def test_tracing_is_idempotent(monkeypatch):
    """A segunda chamada retorna cedo; instrumentar duas vezes duplicaria spans."""
    monkeypatch.setattr(observability, "_tracing_active", True)
    monkeypatch.setattr(settings, "enable_tracing", False)
    assert observability.setup_tracing() is True


# ---------------------------------------------------------------------------
# _resolve_headers
# ---------------------------------------------------------------------------


def test_headers_empty_when_nothing_configured(monkeypatch):
    monkeypatch.setattr(settings, "otlp_headers", "")
    monkeypatch.setattr(settings, "langfuse_public_key", "")
    monkeypatch.setattr(settings, "langfuse_secret_key", "")
    assert observability._resolve_headers() == {}


def test_headers_parsed_from_otlp_env(monkeypatch):
    monkeypatch.setattr(settings, "otlp_headers", "Authorization=Bearer abc,X-Scope=team")
    monkeypatch.setattr(settings, "langfuse_public_key", "")
    monkeypatch.setattr(settings, "langfuse_secret_key", "")
    assert observability._resolve_headers() == {
        "Authorization": "Bearer abc",
        "X-Scope": "team",
    }


def test_headers_built_from_langfuse_keys(monkeypatch):
    monkeypatch.setattr(settings, "otlp_headers", "")
    monkeypatch.setattr(settings, "langfuse_public_key", "pk-lf-1")
    monkeypatch.setattr(settings, "langfuse_secret_key", "sk-lf-2")

    expected = base64.b64encode(b"pk-lf-1:sk-lf-2").decode()
    assert observability._resolve_headers() == {"Authorization": f"Basic {expected}"}


def test_explicit_otlp_headers_win_over_langfuse_keys(monkeypatch):
    """OTEL_EXPORTER_OTLP_HEADERS é o padrão aberto, então tem precedência."""
    monkeypatch.setattr(settings, "otlp_headers", "Authorization=Bearer manual")
    monkeypatch.setattr(settings, "langfuse_public_key", "pk-lf-1")
    monkeypatch.setattr(settings, "langfuse_secret_key", "sk-lf-2")
    assert observability._resolve_headers() == {"Authorization": "Bearer manual"}


# ---------------------------------------------------------------------------
# observability switch
# ---------------------------------------------------------------------------


def test_master_switch_enables_flag_when_specific_flag_is_unset(monkeypatch):
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
    monkeypatch.delenv("ENABLE_METRICS", raising=False)

    assert _observability_bool_from_env_alias(("ENABLE_METRICS",), False) is True


def test_specific_flag_overrides_master_switch(monkeypatch):
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
    monkeypatch.setenv("ENABLE_METRICS", "false")

    assert _observability_bool_from_env_alias(("ENABLE_METRICS",), False) is False


def test_specific_flag_can_still_be_enabled_without_master_switch(monkeypatch):
    monkeypatch.delenv("OBSERVABILITY_ENABLED", raising=False)
    monkeypatch.setenv("ENABLE_METRICS", "true")

    assert _observability_bool_from_env_alias(("ENABLE_METRICS",), False) is True


# ---------------------------------------------------------------------------
# /metrics
# ---------------------------------------------------------------------------


def _metrics_route_exists(app) -> bool:
    return any(getattr(route, "path", None) == "/metrics" for route in app.routes)


def _bare_app():
    """App mínimo, sem as rotas do projeto.

    O alvo aqui é a função de wiring, não a API inteira; montar o app real traria
    todo o grafo do backend para validar a presença de uma rota.
    """
    fastapi = pytest.importorskip("fastapi")
    return fastapi.FastAPI()


def test_metrics_route_absent_by_default(monkeypatch):
    monkeypatch.setattr(settings, "enable_metrics", False)
    app = _bare_app()

    assert observability.setup_metrics(app) is False
    assert _metrics_route_exists(app) is False


def test_metrics_route_registered_when_enabled(monkeypatch):
    pytest.importorskip(
        "prometheus_fastapi_instrumentator",
        reason="extra observability não instalado",
    )
    monkeypatch.setattr(settings, "enable_metrics", True)
    app = _bare_app()

    assert observability.setup_metrics(app) is True
    assert _metrics_route_exists(app) is True


def test_metrics_degrades_when_dependency_missing(monkeypatch):
    """Sem a lib instalada, a API sobe do mesmo jeito: só não expõe /metrics."""
    monkeypatch.setattr(settings, "enable_metrics", True)
    monkeypatch.setitem(
        __import__("sys").modules, "prometheus_fastapi_instrumentator", None
    )
    app = _bare_app()

    assert observability.setup_metrics(app) is False
    assert _metrics_route_exists(app) is False


def test_domain_metrics_are_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "enable_metrics", False)

    observability.set_queue_size(3)
    observability.record_job_status("queued", source="api", mode="normal")
    observability.record_job_started(source="api", mode="normal")
    observability.record_job_finished(
        "done",
        source="api",
        mode="normal",
        duration_seconds=1.2,
    )
    observability.record_pipeline_error("pipeline", source="api", mode="normal")
    observability.record_export("txt", 1024, source="api", mode="normal")
    observability.record_llm_call("VisionAgent")
    observability.record_llm_failure("VisionAgent")
    observability.record_llm_duration("VisionAgent", "error", 0.5)
    observability.record_llm_response(
        "VisionAgent",
        SimpleNamespace(metrics=None, content="resultado"),
        prompt="prompt",
    )

    assert observability._domain_metrics is None


def test_domain_metrics_register_when_enabled(monkeypatch):
    prometheus_client = pytest.importorskip(
        "prometheus_client",
        reason="extra observability não instalado",
    )
    registry = prometheus_client.CollectorRegistry()
    counter = prometheus_client.Counter
    gauge = prometheus_client.Gauge
    histogram = prometheus_client.Histogram

    def _counter(*args, **kwargs):
        kwargs.setdefault("registry", registry)
        return counter(*args, **kwargs)

    def _gauge(*args, **kwargs):
        kwargs.setdefault("registry", registry)
        return gauge(*args, **kwargs)

    def _histogram(*args, **kwargs):
        kwargs.setdefault("registry", registry)
        return histogram(*args, **kwargs)

    monkeypatch.setattr(prometheus_client, "Counter", _counter)
    monkeypatch.setattr(prometheus_client, "Gauge", _gauge)
    monkeypatch.setattr(prometheus_client, "Histogram", _histogram)
    monkeypatch.setattr(settings, "enable_metrics", True)

    observability.set_queue_size(2)
    observability.record_job_started(source="api", mode="normal")
    observability.record_job_finished(
        "done",
        source="api",
        mode="normal",
        duration_seconds=2.4,
    )
    observability.record_export("zip", 2048, source="api", mode="normal")
    observability.record_llm_call("DataAgent")
    observability.record_llm_response(
        "DataAgent",
        SimpleNamespace(
            model_provider="ollama",
            model="modelo-local",
            content="resposta",
            metrics=SimpleNamespace(
                input_tokens=10,
                output_tokens=5,
                total_tokens=15,
                reasoning_tokens=2,
                cache_read_tokens=3,
                cache_write_tokens=0,
                audio_input_tokens=0,
                audio_output_tokens=0,
                audio_total_tokens=0,
                cost=0.0123,
                time_to_first_token=0.42,
                details=None,
            ),
        ),
        prompt="prompt de teste",
    )

    assert observability._domain_metrics is not None
    output = prometheus_client.generate_latest(registry).decode()
    assert "acessilia_llm_tokens_total" in output
    assert 'token_type="total"' in output
    assert 'token_type="reasoning"' in output
    assert "acessilia_llm_cost_total" in output
    assert "acessilia_llm_time_to_first_token_seconds" in output
    assert "acessilia_llm_content_chars" in output
