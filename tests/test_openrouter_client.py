import pytest
import respx
import httpx
from unittest.mock import patch, AsyncMock
from core.ai.openrouter import OpenRouterClient
from config.settings import settings

TEST_OPENROUTER_URL = "https://test-openrouter.ai/api/v1/chat/completions"


@pytest.fixture
def openrouter_client():
    settings.openrouter_api_key = "test_key"
    settings.openrouter_model = "test_model"
    settings.openrouter_base_url = TEST_OPENROUTER_URL
    return OpenRouterClient()


@respx.mock
@pytest.mark.asyncio
async def test_send_message_success(openrouter_client):
    respx.post(openrouter_client.base_url).mock(
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

    result = await openrouter_client.send_message("Ola", images=[b"dummy_image"])
    assert result == "Teste de resposta"


@respx.mock
@pytest.mark.asyncio
async def test_send_message_payload_config(openrouter_client):
    def check_payload(request):
        import json
        payload = json.loads(request.content)
        assert payload.get("temperature") == 0
        assert payload.get("seed") == 42
        assert payload.get("max_tokens") == 4096
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "OK"}}]
        })

    respx.post(openrouter_client.base_url).mock(side_effect=check_payload)
    await openrouter_client.send_message("Ola")


@respx.mock
@pytest.mark.asyncio
async def test_send_message_rate_limit_retry(openrouter_client):
    route = respx.post(openrouter_client.base_url)
    route.side_effect = [
        httpx.Response(429),
        httpx.Response(200, json={
            "choices": [{"message": {"content": "Sucesso apos retry"}}]
        })
    ]

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await openrouter_client.send_message("Ola")

    assert result == "Sucesso apos retry"


@respx.mock
@pytest.mark.asyncio
async def test_send_message_none_content_retry(openrouter_client):
    route = respx.post(openrouter_client.base_url)
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
        result = await openrouter_client.send_message("Ola")

    assert result == "Resposta valida"


@respx.mock
@pytest.mark.asyncio
async def test_send_message_finish_reason_length_retry(openrouter_client):
    route = respx.post(openrouter_client.base_url)
    route.side_effect = [
        httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": "Resposta truncada"}
                    }
                ]
            },
        ),
        httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "Resposta completa"}}
                ]
            },
        ),
    ]

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await openrouter_client.send_message("Ola")

    assert result == "Resposta completa"


@respx.mock
@pytest.mark.asyncio
async def test_send_message_server_error_retry(openrouter_client):
    route = respx.post(openrouter_client.base_url)
    route.side_effect = [
        httpx.Response(502),
        httpx.Response(200, json={
            "choices": [{"message": {"content": "Recuperado apos 502"}}]
        })
    ]

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await openrouter_client.send_message("Ola")

    assert result == "Recuperado apos 502"


@pytest.mark.asyncio
async def test_send_message_no_api_key():
    settings.openrouter_api_key = ""
    settings.openrouter_base_url = TEST_OPENROUTER_URL
    client = OpenRouterClient()
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        await client.send_message("Ola")
