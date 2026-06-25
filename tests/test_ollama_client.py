import pytest
import respx
import httpx
from unittest.mock import patch, AsyncMock
from core.ai.ollama import OllamaClient
from config.settings import settings

TEST_OLLAMA_URL = "http://test-ollama:11434/api/chat"


@pytest.fixture
def ollama_client():
    settings.ollama_api_key = "test_key"
    settings.ollama_model = "test_model"
    settings.ollama_base_url = TEST_OLLAMA_URL
    return OllamaClient()


@respx.mock
@pytest.mark.asyncio
async def test_send_message_success(ollama_client):
    respx.post(ollama_client.base_url).mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "test_model",
                "message": {
                    "role": "assistant",
                    "content": "Teste de resposta",
                },
                "done_reason": "stop",
                "done": True,
            },
        )
    )

    result = await ollama_client.send_message("Olá", images=[b"dummy_image"])
    assert result == "Teste de resposta"


@respx.mock
@pytest.mark.asyncio
async def test_send_message_payload_config(ollama_client):
    def check_payload(request):
        import json

        payload = json.loads(request.content)
        assert payload.get("model") == "test_model"
        assert payload.get("stream") is False
        assert payload.get("keep_alive") == -1
        options = payload.get("options", {})
        assert options.get("temperature") == 1.0
        assert options.get("top_p") == 0.95
        assert options.get("top_k") == 64
        assert options.get("vision_budget") == 560
        assert options.get("seed") == 42
        return httpx.Response(
            200,
            json={
                "model": "test_model",
                "message": {"role": "assistant", "content": "OK"},
                "done_reason": "stop",
                "done": True,
            },
        )

    respx.post(ollama_client.base_url).mock(side_effect=check_payload)

    await ollama_client.send_message("Olá")


@respx.mock
@pytest.mark.asyncio
async def test_send_message_rate_limit_retry(ollama_client):
    route = respx.post(ollama_client.base_url)
    route.side_effect = [
        httpx.Response(429),
        httpx.Response(
            200,
            json={
                "model": "test_model",
                "message": {"role": "assistant", "content": "Sucesso após retry"},
                "done_reason": "stop",
                "done": True,
            },
        ),
    ]

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await ollama_client.send_message("Olá")

    assert result == "Sucesso após retry"


@respx.mock
@pytest.mark.asyncio
async def test_send_message_none_content_retry(ollama_client):
    route = respx.post(ollama_client.base_url)
    route.side_effect = [
        httpx.Response(
            200,
            json={
                "model": "test_model",
                "message": {"role": "assistant", "content": None},
                "done_reason": "stop",
                "done": True,
            },
        ),
        httpx.Response(
            200,
            json={
                "model": "test_model",
                "message": {"role": "assistant", "content": "Resposta valida"},
                "done_reason": "stop",
                "done": True,
            },
        ),
    ]

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await ollama_client.send_message("Olá")

    assert result == "Resposta valida"


@pytest.mark.asyncio
async def test_send_message_no_api_key():
    settings.ollama_api_key = ""
    client = OllamaClient()
    with pytest.raises(RuntimeError, match="OLLAMA_API_KEY"):
        await client.send_message("Olá")
