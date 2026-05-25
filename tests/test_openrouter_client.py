import pytest
import respx
import httpx
from unittest.mock import patch, AsyncMock
from bot.clients.openrouter import OpenRouterClient
from config.settings import settings

@pytest.fixture
def openrouter_client():
    settings.openrouter_api_key = "test_key"
    settings.openrouter_model = "test_model"
    return OpenRouterClient()

@respx.mock
@pytest.mark.asyncio
async def test_send_message_success(openrouter_client):
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
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

    result = await openrouter_client.send_message("Olá", images=[b"dummy_image"])
    assert result == "Teste de resposta"

@respx.mock
@pytest.mark.asyncio
async def test_send_message_rate_limit_retry(openrouter_client):
    # Mock first call as 429, then success
    route = respx.post("https://openrouter.ai/api/v1/chat/completions")
    route.side_effect = [
        httpx.Response(429),
        httpx.Response(200, json={
            "choices": [{"message": {"content": "Sucesso após retry"}}]
        })
    ]

    # Patch asyncio.sleep to avoid waiting in tests
    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await openrouter_client.send_message("Olá")
    
    assert result == "Sucesso após retry"


@respx.mock
@pytest.mark.asyncio
async def test_send_message_none_content_retry(openrouter_client):
    route = respx.post("https://openrouter.ai/api/v1/chat/completions")
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
        result = await openrouter_client.send_message("Olá")

    assert result == "Resposta valida"

@pytest.mark.asyncio
async def test_send_message_no_api_key():
    settings.openrouter_api_key = ""
    client = OpenRouterClient()
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        await client.send_message("Olá")
