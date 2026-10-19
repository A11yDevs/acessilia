"""Transient extraction recovery must preserve real single-provider fallback."""

from collections import Counter

import pytest

from backend.pipeline.fusion import extract_fused
from backend.tools.toolbox_client import (
    ToolboxAuthenticationError,
    ToolboxContractViolation,
    ToolboxError,
    ToolboxProviderUnavailable,
    ToolboxTimeout,
)


def install_clients(monkeypatch, fail):
    calls = Counter()

    class Client:
        def __init__(self, provider):
            self.provider = provider

        async def close(self):
            pass

        async def extract_structure(self, *args, **kwargs):
            calls[self.provider] += 1
            error = fail(self.provider, calls[self.provider])
            if error:
                raise error("synthetic extraction error")
            return {
                "status": "succeeded",
                "provider": self.provider,
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

    monkeypatch.setattr("backend.pipeline.fusion._structure_client", Client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["docling", "mineru"])
@pytest.mark.parametrize("error", [ToolboxTimeout, ToolboxProviderUnavailable])
async def test_transient_failure_recovers_without_repeating_success(
    monkeypatch, provider, error
):
    calls = install_clients(
        monkeypatch, lambda p, n: error if p == provider and n == 1 else None
    )
    result = await extract_fused(
        "synthetic.pdf", primary_provider="docling", secondary_provider="mineru"
    )
    assert result["provider"] == "docling+mineru"
    assert calls[provider] == 2
    assert calls["mineru" if provider == "docling" else "docling"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [ToolboxAuthenticationError, ToolboxContractViolation, ToolboxError],
)
async def test_permanent_failure_is_not_retried(monkeypatch, error):
    calls = install_clients(monkeypatch, lambda p, n: error if p == "docling" else None)
    result = await extract_fused(
        "synthetic.pdf", primary_provider="docling", secondary_provider="mineru"
    )
    assert result["provider"] == "mineru"
    assert calls == {"docling": 1, "mineru": 1}


@pytest.mark.asyncio
async def test_unexpected_error_is_propagated_without_retry(monkeypatch):
    calls = install_clients(
        monkeypatch, lambda p, n: RuntimeError if p == "docling" else None
    )
    with pytest.raises(RuntimeError):
        await extract_fused(
            "synthetic.pdf", primary_provider="docling", secondary_provider="mineru"
        )
    assert calls["docling"] == 1


@pytest.mark.asyncio
async def test_persistent_transient_failure_keeps_single_provider_fallback(monkeypatch):
    calls = install_clients(
        monkeypatch, lambda p, n: ToolboxTimeout if p == "docling" else None
    )
    result = await extract_fused(
        "synthetic.pdf", primary_provider="docling", secondary_provider="mineru"
    )
    assert result["provider"] == "mineru"
    assert calls == {"docling": 2, "mineru": 1}


@pytest.mark.asyncio
async def test_both_persistently_unavailable_stop_after_two_attempts(monkeypatch):
    calls = install_clients(monkeypatch, lambda p, n: ToolboxProviderUnavailable)
    with pytest.raises(ToolboxProviderUnavailable):
        await extract_fused(
            "synthetic.pdf", primary_provider="docling", secondary_provider="mineru"
        )
    assert calls == {"docling": 2, "mineru": 2}
