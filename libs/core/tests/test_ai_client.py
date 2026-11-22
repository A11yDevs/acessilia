from __future__ import annotations

from agno.models import ollama, openrouter
from core_config_support import model_config, toolbox_config

from acessilia_core.agents import ai_client


def test_openrouter_model_receives_configured_max_tokens(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_openrouter(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(openrouter, "OpenRouter", fake_openrouter)

    ai_client.get_agno_model(model_config(ai_client="openrouter", openrouter_model="test/model", openrouter_api_key="test-key", openrouter_base_url="https://example.test/v1/chat/completions", openrouter_max_tokens=4096, openrouter_site_url="", openrouter_app_name=""), toolbox_config())

    assert captured["max_tokens"] == 4096
    assert "extra_body" not in captured


def test_openrouter_model_receives_agent_specific_max_tokens(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_openrouter(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(openrouter, "OpenRouter", fake_openrouter)

    ai_client.get_agno_model(model_config(ai_client="openrouter", openrouter_model="test/model", openrouter_api_key="test-key", openrouter_base_url="https://example.test/v1/chat/completions", openrouter_max_tokens=2000, openrouter_site_url="", openrouter_app_name=""), toolbox_config(), max_tokens=8192)

    assert captured["max_tokens"] == 8192


def test_openrouter_model_can_disable_the_sdk_retries(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_openrouter(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(openrouter, "OpenRouter", fake_openrouter)

    ai_client.get_agno_model(model_config(ai_client="openrouter", openrouter_model="test/model", openrouter_api_key="test-key", openrouter_base_url="https://example.test/v1/chat/completions", openrouter_site_url="", openrouter_app_name=""), toolbox_config(), max_retries=0)

    assert captured["max_retries"] == 0


def test_ollama_model_receives_agent_specific_prediction_limit(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_ollama(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(ollama, "Ollama", fake_ollama)

    ai_client.get_agno_model(model_config(ai_client="ollama", ollama_model="test/model", ollama_base_url="http://localhost:11434/api/chat", ollama_api_key=""), toolbox_config(), max_tokens=8192)

    assert captured["options"]["num_predict"] == 8192


def test_openrouter_recovery_can_disable_reasoning(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(openrouter, "OpenRouter", lambda **kwargs: captured.update(kwargs))

    ai_client.get_agno_model(model_config(ai_client="openrouter"), toolbox_config(), max_tokens=2000, reasoning_enabled=False)

    assert captured["extra_body"] == {"reasoning": {"enabled": False}}
    assert captured["max_tokens"] == 2000


def test_ollama_recovery_can_disable_thinking(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(ollama, "Ollama", lambda **kwargs: captured.update(kwargs))

    ai_client.get_agno_model(model_config(ai_client="ollama"), toolbox_config(), max_tokens=2000, reasoning_enabled=False)

    assert captured["request_params"] == {"think": False}
    assert captured["options"]["num_predict"] == 2000


def _capture_openai_like(monkeypatch) -> dict[str, object]:
    from agno.models.openai import like

    captured: dict[str, object] = {}

    def fake_openai_like(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(like, "OpenAILike", fake_openai_like)
    return captured


def _toolbox_run(**toolbox_fields):
    """A run that sends its chats to the Toolbox VLM gateway."""
    models = model_config(
        ai_client="toolbox",
        toolbox_vlm_provider="qwen3-vl-8b",
        openrouter_max_tokens=4096,
        model_call_timeout_seconds=600,
    )
    toolbox = toolbox_config(
        **({"base_url": "http://toolbox:8002/", "base_urls": "", "api_key": "toolbox-key"}
           | toolbox_fields)
    )
    return models, toolbox


def test_toolbox_model_targets_the_vlm_gateway_with_the_toolbox_key(monkeypatch) -> None:
    captured = _capture_openai_like(monkeypatch)

    ai_client.get_agno_model(*_toolbox_run(), max_tokens=2000, max_retries=0)

    assert captured["base_url"] == "http://toolbox:8002/v1/vlm"
    assert captured["api_key"] == "toolbox-key"
    assert captured["id"] == "qwen3-vl-8b"
    assert captured["max_tokens"] == 2000
    assert captured["max_retries"] == 0
    assert captured["timeout"] == 600.0
    assert ai_client.active_model_name(_toolbox_run()[0]) == "qwen3-vl-8b"


def test_toolbox_model_falls_back_to_the_shared_budget_and_takes_the_call_timeout(
    monkeypatch,
) -> None:
    captured = _capture_openai_like(monkeypatch)

    ai_client.get_agno_model(*_toolbox_run(), max_tokens=None, timeout_seconds=42)

    assert captured["max_tokens"] == 4096
    assert captured["timeout"] == 42.0


def test_toolbox_model_uses_the_first_endpoint_of_the_failover_list(monkeypatch) -> None:
    captured = _capture_openai_like(monkeypatch)
    ai_client.get_agno_model(
        *_toolbox_run(base_urls="http://primary:8002, http://secondary:8002")
    )

    assert captured["base_url"] == "http://primary:8002/v1/vlm"
