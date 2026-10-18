"""make_toolbox_client: SDK capability clients configured from the core settings."""

from __future__ import annotations

import pytest

from acessilia_sdk.toolbox import ToolboxEndpoint, ToolboxTimeout
from acessilia_sdk.toolbox.clients import (
    ToolboxMathClient,
    ToolboxOcrClient,
    ToolboxPdfUaClient,
)
from backend.config.settings import settings
from backend.tools import toolbox_client
from backend.tools.toolbox_client import make_toolbox_client, toolbox_endpoints

PRIMARY = "http://toolbox-a.test"
SECONDARY = "http://toolbox-b.test"


@pytest.fixture(autouse=True)
def toolbox_settings(monkeypatch):
    monkeypatch.setattr(settings, "toolbox_base_url", PRIMARY)
    monkeypatch.setattr(settings, "toolbox_base_urls", "")
    monkeypatch.setattr(settings, "toolbox_api_key", "core-key")
    monkeypatch.setattr(settings, "toolbox_timeout_seconds", 120)


def test_takes_endpoint_provider_key_and_timeout_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "toolbox_ocr_provider", "mineru-ocr")

    client = make_toolbox_client(ToolboxOcrClient)

    assert client.endpoints == (ToolboxEndpoint(PRIMARY),)
    assert client.provider == "mineru-ocr"
    assert client.api_key == "core-key"
    assert client.timeout_seconds == 120


def test_base_urls_list_independent_deployments(monkeypatch):
    monkeypatch.setattr(settings, "toolbox_base_urls", f"{PRIMARY}, {SECONDARY}")

    assert [e.base_url for e in toolbox_endpoints()] == [PRIMARY, SECONDARY]
    assert len(make_toolbox_client(ToolboxOcrClient).endpoints) == 2


def test_overrides_win_and_none_is_ignored():
    client = make_toolbox_client(
        ToolboxOcrClient, base_url=SECONDARY, provider=None, timeout_seconds=5
    )

    assert client.endpoints == (ToolboxEndpoint(SECONDARY, "core-key"),)
    assert client.provider == settings.toolbox_ocr_provider
    assert client.timeout_seconds == 5


def test_math_transform_provider_comes_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "toolbox_math_provider", "custom-math")

    assert make_toolbox_client(ToolboxMathClient).transform_provider == "custom-math"


def test_pdf_ua_uses_its_own_timeout(monkeypatch):
    monkeypatch.setattr(settings, "toolbox_pdf_ua_timeout_seconds", 300)

    assert make_toolbox_client(ToolboxPdfUaClient).timeout_seconds == 300


def test_failovers_are_logged(monkeypatch):
    warnings: list[tuple] = []
    monkeypatch.setattr(
        toolbox_client.logger, "warning", lambda *args: warnings.append(args)
    )
    client = make_toolbox_client(ToolboxOcrClient)

    client.on_failover(ToolboxEndpoint(PRIMARY), ToolboxTimeout("slow"))

    (message, url, error_type, error), = warnings
    assert "failed" in message
    assert (url, error_type, str(error)) == (PRIMARY, "ToolboxTimeout", "slow")


def test_a_malformed_base_url_fails_loudly(monkeypatch):
    monkeypatch.setattr(settings, "toolbox_base_url", "localhost:8002")

    with pytest.raises(ValueError, match="absolute http"):
        make_toolbox_client(ToolboxOcrClient)
