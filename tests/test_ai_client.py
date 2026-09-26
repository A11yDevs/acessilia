from __future__ import annotations

from agno.models import openrouter

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
