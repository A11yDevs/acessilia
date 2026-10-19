"""Transient extraction recovery must preserve real single-provider fallback.

Retries come from the SDK client (``TOOLBOX_RETRIES``, docs/adr/0006), so
these tests drive real ``ToolboxStructureClient``s over mocked HTTP instead of
fakes that would bypass the retry.
"""

from collections import Counter

import httpx
import pytest
import respx

from backend.config.settings import settings
from backend.pipeline.fusion import extract_fused
from backend.tools.toolbox_client import ToolboxProviderUnavailable

BASE_URL = "http://toolbox.test"
EXECUTE = f"{BASE_URL}/v1/capabilities/document.structure.extract:execute"


@pytest.fixture(autouse=True)
def toolbox_settings(monkeypatch):
    from acessilia_sdk.toolbox import client as client_module

    async def no_wait(_delay):
        return None

    monkeypatch.setattr(client_module, "_sleep", no_wait)
    monkeypatch.setattr(settings, "toolbox_base_url", BASE_URL)
    monkeypatch.setattr(settings, "toolbox_base_urls", "")
    monkeypatch.setattr(settings, "toolbox_api_key", "")
    monkeypatch.setattr(settings, "toolbox_retries", 1)


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(b"%PDF-1.4 synthetic")
    return path


def _payload(provider: str) -> dict:
    return {
        "status": "succeeded",
        "provider": provider,
        "document": {
            "elements": [
                {
                    "type": "paragraph",
                    "text": "Shared accessible text",
                    "reading_order": 1,
                    "page": 0,
                    "bbox": [0, 0, 100, 30],
                    "page_size": [100, 100],
                }
            ]
        },
    }


def _provider_of(request: httpx.Request) -> str:
    body = request.content.decode(errors="ignore")
    for provider in ("docling", "mineru"):
        if f"\r\n\r\n{provider}\r\n" in body:
            return provider
    raise AssertionError("request without a known provider")


def mock_toolbox(router, respond):
    """``respond(provider, attempt)`` returns the response for each call."""
    calls = Counter()

    def handler(request: httpx.Request) -> httpx.Response:
        provider = _provider_of(request)
        calls[provider] += 1
        return respond(provider, calls[provider])

    router.post(EXECUTE).mock(side_effect=handler)
    return calls


def _ok(provider: str) -> httpx.Response:
    return httpx.Response(200, json=_payload(provider))


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["docling", "mineru"])
@pytest.mark.parametrize("status", [503, 504])
async def test_transient_failure_recovers_without_repeating_success(
    source, provider, status
):
    with respx.mock() as router:
        calls = mock_toolbox(
            router,
            lambda p, n: httpx.Response(status, json={"detail": "busy"})
            if p == provider and n == 1
            else _ok(p),
        )
        result = await extract_fused(
            source, primary_provider="docling", secondary_provider="mineru"
        )
    assert result["provider"] == "docling+mineru"
    assert calls[provider] == 2
    assert calls["mineru" if provider == "docling" else "docling"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 422])
async def test_permanent_failure_is_not_retried(source, status):
    with respx.mock() as router:
        calls = mock_toolbox(
            router,
            lambda p, n: httpx.Response(status, json={"detail": "no"})
            if p == "docling"
            else _ok(p),
        )
        result = await extract_fused(
            source, primary_provider="docling", secondary_provider="mineru"
        )
    assert result["provider"] == "mineru"
    assert calls == {"docling": 1, "mineru": 1}


@pytest.mark.asyncio
async def test_unexpected_error_is_propagated_without_retry(monkeypatch, source):
    calls = Counter()

    class Client:
        def __init__(self, provider):
            self.provider = provider

        async def close(self):
            pass

        async def extract_structure(self, *args, **kwargs):
            calls[self.provider] += 1
            if self.provider == "docling":
                raise RuntimeError("synthetic bug")
            return _payload(self.provider)

    monkeypatch.setattr("backend.pipeline.fusion._structure_client", Client)
    with pytest.raises(RuntimeError):
        await extract_fused(
            source, primary_provider="docling", secondary_provider="mineru"
        )
    assert calls["docling"] == 1


@pytest.mark.asyncio
async def test_persistent_transient_failure_keeps_single_provider_fallback(source):
    with respx.mock() as router:
        calls = mock_toolbox(
            router,
            lambda p, n: httpx.Response(504, json={"detail": "slow"})
            if p == "docling"
            else _ok(p),
        )
        result = await extract_fused(
            source, primary_provider="docling", secondary_provider="mineru"
        )
    assert result["provider"] == "mineru"
    assert calls == {"docling": 2, "mineru": 1}


@pytest.mark.asyncio
async def test_both_persistently_unavailable_stop_after_the_retries(source):
    with respx.mock() as router:
        calls = mock_toolbox(
            router, lambda p, n: httpx.Response(503, json={"detail": "down"})
        )
        with pytest.raises(ToolboxProviderUnavailable):
            await extract_fused(
                source, primary_provider="docling", secondary_provider="mineru"
            )
    assert calls == {"docling": 2, "mineru": 2}


@pytest.mark.asyncio
async def test_retries_follow_the_setting(monkeypatch, source):
    monkeypatch.setattr(settings, "toolbox_retries", 0)
    with respx.mock() as router:
        calls = mock_toolbox(
            router,
            lambda p, n: httpx.Response(503, json={"detail": "down"})
            if p == "docling"
            else _ok(p),
        )
        result = await extract_fused(
            source, primary_provider="docling", secondary_provider="mineru"
        )
    assert result["provider"] == "mineru"
    assert calls == {"docling": 1, "mineru": 1}
