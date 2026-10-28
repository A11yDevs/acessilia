from __future__ import annotations

from agno.models import ollama, openrouter

from backend.ai.models import ai_client
from backend.config.settings import settings


def test_openrouter_model_receives_configured_max_tokens(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_openrouter(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(openrouter, "OpenRouter", fake_openrouter)
    monkeypatch.setattr(settings, "ai_client", "openrouter")
    monkeypatch.setattr(settings, "openrouter_model", "test/model")
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(settings, "openrouter_base_url", "https://example.test/v1/chat/completions")
    monkeypatch.setattr(settings, "openrouter_max_tokens", 4096)
    monkeypatch.setattr(settings, "openrouter_site_url", "")
    monkeypatch.setattr(settings, "openrouter_app_name", "")

    ai_client.get_agno_model()

    assert captured["max_tokens"] == 4096
    assert "extra_body" not in captured


def test_openrouter_model_receives_agent_specific_max_tokens(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_openrouter(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(openrouter, "OpenRouter", fake_openrouter)
    monkeypatch.setattr(settings, "ai_client", "openrouter")
    monkeypatch.setattr(settings, "openrouter_model", "test/model")
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(settings, "openrouter_base_url", "https://example.test/v1/chat/completions")
    monkeypatch.setattr(settings, "openrouter_max_tokens", 2000)
    monkeypatch.setattr(settings, "openrouter_site_url", "")
    monkeypatch.setattr(settings, "openrouter_app_name", "")

    ai_client.get_agno_model(max_tokens=8192)

    assert captured["max_tokens"] == 8192


def test_openrouter_model_can_disable_the_sdk_retries(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_openrouter(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(openrouter, "OpenRouter", fake_openrouter)
    monkeypatch.setattr(settings, "ai_client", "openrouter")
    monkeypatch.setattr(settings, "openrouter_model", "test/model")
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(settings, "openrouter_base_url", "https://example.test/v1/chat/completions")
    monkeypatch.setattr(settings, "openrouter_site_url", "")
    monkeypatch.setattr(settings, "openrouter_app_name", "")

    ai_client.get_agno_model(max_retries=0)

    assert captured["max_retries"] == 0


def test_ollama_model_receives_agent_specific_prediction_limit(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_ollama(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(ollama, "Ollama", fake_ollama)
    monkeypatch.setattr(settings, "ai_client", "ollama")
    monkeypatch.setattr(settings, "ollama_model", "test/model")
    monkeypatch.setattr(settings, "ollama_base_url", "http://localhost:11434/api/chat")
    monkeypatch.setattr(settings, "ollama_api_key", "")

    ai_client.get_agno_model(max_tokens=8192)

    assert captured["options"]["num_predict"] == 8192


def test_openrouter_recovery_can_disable_reasoning(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(openrouter, "OpenRouter", lambda **kwargs: captured.update(kwargs))
    monkeypatch.setattr(settings, "ai_client", "openrouter")

    ai_client.get_agno_model(max_tokens=2000, reasoning_enabled=False)

    assert captured["extra_body"] == {"reasoning": {"enabled": False}}
    assert captured["max_tokens"] == 2000


def test_ollama_recovery_can_disable_thinking(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(ollama, "Ollama", lambda **kwargs: captured.update(kwargs))
    monkeypatch.setattr(settings, "ai_client", "ollama")

    ai_client.get_agno_model(max_tokens=2000, reasoning_enabled=False)

    assert captured["request_params"] == {"think": False}
    assert captured["options"]["num_predict"] == 2000
