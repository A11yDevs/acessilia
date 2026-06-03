import pytest
import respx
import httpx
from unittest.mock import patch, AsyncMock
from core.ai.ollama import OllamaClient
from config.settings import settings

TEST_OLLAMA_URL = "http://test-ollama:11434/v1/chat/completions"


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

    respx.post(ollama_client.base_url).mock(side_effect=check_payload)

    await ollama_client.send_message("Olá")


@respx.mock
@pytest.mark.asyncio
async def test_send_message_rate_limit_retry(ollama_client):
    route = respx.post(ollama_client.base_url)
    route.side_effect = [
        httpx.Response(429),
        httpx.Response(200, json={
            "choices": [{"message": {"content": "Sucesso após retry"}}]
        })
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
