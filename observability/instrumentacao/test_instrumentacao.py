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
    yield
    observability._tracing_active = False


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
