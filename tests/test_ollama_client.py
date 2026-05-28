import pytest
import respx
import httpx
from unittest.mock import patch, AsyncMock
from bot.clients.ollama import OllamaClient
from config.settings import settings

@pytest.fixture
def ollama_client():
    settings.ollama_api_key = "test_key"
    settings.ollama_model = "test_model"
    return OllamaClient()

@respx.mock
@pytest.mark.asyncio
async def test_send_message_success(ollama_client):
    respx.post("http://172.16.109.33:11434/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [
                {
                    "message": {
                        "content": "Teste de resposta"
                    }
                }
            ]
        })
    )

    result = await ollama_client.send_message("Olá", images=[b"dummy_image"])
    assert result == "Teste de resposta"

@respx.mock
@pytest.mark.asyncio
async def test_send_message_payload_config(ollama_client):
    def check_payload(request):
        import json
        payload = json.loads(request.content)
        assert payload.get("temperature") == 0
        assert payload.get("seed") == 42
        assert payload.get("max_tokens") == 300
        assert payload.get("num_predict") == 300
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "OK"}}]
        })

    respx.post("http://172.16.109.33:11434/v1/chat/completions").mock(side_effect=check_payload)

    await ollama_client.send_message("Olá")

@respx.mock
@pytest.mark.asyncio
async def test_send_message_rate_limit_retry(ollama_client):
    # Mock first call as 429, then success
    route = respx.post("http://172.16.109.33:11434/v1/chat/completions")
    route.side_effect = [
        httpx.Response(429),
        httpx.Response(200, json={
            "choices": [{"message": {"content": "Sucesso após retry"}}]
        })
    ]

    # Patch asyncio.sleep to avoid waiting in tests
    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await ollama_client.send_message("Olá")
    
    assert result == "Sucesso após retry"


@respx.mock
@pytest.mark.asyncio
async def test_send_message_none_content_retry(ollama_client):
    route = respx.post("http://172.16.109.33:11434/v1/chat/completions")
    route.side_effect = [
        httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                        }
                    }
                ]
            },
        ),
        httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "Resposta valida"}}
                ]
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
