"""ToolboxClientConfig and make_client: explicit configuration, no settings."""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError

import pytest

from acessilia_sdk.toolbox import (
    PROVIDER_DEFAULTS,
    ToolboxClientConfig,
    ToolboxEndpoint,
    ToolboxTimeout,
    make_client,
)
from acessilia_sdk.toolbox.clients import (
    ToolboxDatasetClient,
    ToolboxDocxClient,
    ToolboxMathClient,
    ToolboxOcrClient,
    ToolboxPdfUaClient,
    ToolboxStructureClient,
)

PRIMARY = "http://toolbox-a.test"
SECONDARY = "http://toolbox-b.test"


def _close(client) -> None:
    asyncio.run(client.close())


def test_endpoints_accept_a_comma_separated_string_and_urls():
    from_string = ToolboxClientConfig(endpoints=f"{PRIMARY}, {SECONDARY}")
    from_urls = ToolboxClientConfig(endpoints=[PRIMARY, ToolboxEndpoint(SECONDARY, "b-key")])

    assert from_string.endpoints == (ToolboxEndpoint(PRIMARY), ToolboxEndpoint(SECONDARY))
    assert from_urls.endpoints == (ToolboxEndpoint(PRIMARY), ToolboxEndpoint(SECONDARY, "b-key"))


@pytest.mark.parametrize("endpoints", ["", " , ", []])
def test_a_config_without_endpoints_fails_loudly(endpoints):
    with pytest.raises(ValueError):
        ToolboxClientConfig(endpoints=endpoints)


def test_a_malformed_url_fails_loudly():
    with pytest.raises(ValueError, match="absolute http"):
        ToolboxClientConfig(endpoints="localhost:8002")


@pytest.mark.parametrize(
    "base_url",
    [
        "http://toolbox.test:bad",
        "http://toolbox.test:bad/",
        "http://toolbox.test:99999",
        "http://toolbox.test:99999/",
    ],
)
def test_a_port_httpx_cannot_use_fails_loudly(base_url):
    with pytest.raises(ValueError, match="port between 0 and 65535"):
        ToolboxEndpoint(base_url)


@pytest.mark.parametrize(
    ("base_url", "normalized"),
    [
        ("http://toolbox.test:0", "http://toolbox.test:0"),
        ("http://toolbox.test:0/", "http://toolbox.test:0"),
        ("http://toolbox.test:65535", "http://toolbox.test:65535"),
        ("http://toolbox.test:65535/", "http://toolbox.test:65535"),
    ],
)
def test_the_port_range_boundaries_are_accepted(base_url, normalized):
    assert ToolboxEndpoint(base_url).base_url == normalized


def test_a_config_rejects_an_invalid_port_before_any_client():
    with pytest.raises(ValueError, match="port between 0 and 65535"):
        ToolboxClientConfig(endpoints="http://toolbox.test:99999")


def test_the_config_is_read_only():
    providers = {"toolbox_ocr_provider": "mineru-ocr"}
    config = ToolboxClientConfig(endpoints=PRIMARY, providers=providers)

    providers["toolbox_ocr_provider"] = "changed"
    with pytest.raises(FrozenInstanceError):
        config.retries = 3
    with pytest.raises(TypeError):
        config.providers["toolbox_ocr_provider"] = "changed"
    assert config.providers["toolbox_ocr_provider"] == "mineru-ocr"


def test_the_provider_comes_from_the_class_provider_key():
    config = ToolboxClientConfig(
        endpoints=PRIMARY,
        providers={"toolbox_provider": "mineru", "toolbox_ocr_provider": "mineru-ocr"},
    )

    structure = make_client(ToolboxStructureClient, config)
    ocr = make_client(ToolboxOcrClient, config)

    assert (structure.provider, ocr.provider) == ("mineru", "mineru-ocr")
    _close(structure)
    _close(ocr)


def test_a_missing_provider_keeps_the_sdk_default_and_routes_get_none():
    config = ToolboxClientConfig(endpoints=PRIMARY)

    ocr = make_client(ToolboxOcrClient, config)
    dataset = make_client(ToolboxDatasetClient, config)

    assert ocr.provider == PROVIDER_DEFAULTS["toolbox_ocr_provider"]
    assert dataset.provider is None
    _close(ocr)
    _close(dataset)


def test_the_math_client_takes_its_transform_provider():
    config = ToolboxClientConfig(
        endpoints=PRIMARY,
        providers={"toolbox_math_recognize_provider": "rapid", "toolbox_math_provider": "custom"},
    )

    client = make_client(ToolboxMathClient, config)

    assert (client.provider, client.transform_provider) == ("rapid", "custom")
    _close(client)


def test_exports_use_their_own_timeout_or_fall_back_to_the_shared_one():
    config = ToolboxClientConfig(
        endpoints=PRIMARY,
        timeout_seconds=3600,
        timeouts={"toolbox_pdf_ua_timeout_seconds": 300},
    )

    pdf_ua = make_client(ToolboxPdfUaClient, config)
    docx = make_client(ToolboxDocxClient, config)
    ocr = make_client(ToolboxOcrClient, config)

    assert (pdf_ua.timeout_seconds, docx.timeout_seconds, ocr.timeout_seconds) == (300, 3600, 3600)
    for client in (pdf_ua, docx, ocr):
        _close(client)


def test_shared_values_reach_every_client():
    def on_failover(endpoint, error):
        return None

    config = ToolboxClientConfig(
        endpoints=[PRIMARY, SECONDARY],
        api_key="key",
        timeout_seconds=120,
        retries=2,
        retry_backoff_seconds=0.25,
        on_failover=on_failover,
    )

    client = make_client(ToolboxOcrClient, config)

    assert [endpoint.base_url for endpoint in client.endpoints] == [PRIMARY, SECONDARY]
    assert (client.api_key, client.timeout_seconds) == ("key", 120)
    assert (client.retries, client.retry_backoff_seconds) == (2, 0.25)
    assert client.on_failover is on_failover
    _close(client)


def test_overrides_win_none_is_ignored_and_base_url_replaces_the_endpoints():
    config = ToolboxClientConfig(
        endpoints=[PRIMARY, SECONDARY],
        api_key="key",
        providers={"toolbox_ocr_provider": "mineru-ocr"},
        retries=1,
    )

    client = make_client(
        ToolboxOcrClient,
        config,
        base_url="http://override.test",
        provider=None,
        timeout_seconds=5,
        retries=0,
    )

    assert client.endpoints == (ToolboxEndpoint("http://override.test", "key"),)
    assert client.provider == "mineru-ocr"
    assert (client.timeout_seconds, client.retries) == (5, 0)
    _close(client)


def test_one_config_builds_independent_clients():
    config = ToolboxClientConfig(endpoints=PRIMARY, retries=1)

    first = make_client(ToolboxOcrClient, config, retries=0)
    second = make_client(ToolboxOcrClient, config)

    assert (first.retries, second.retries, config.retries) == (0, 1, 1)
    assert first._client is not second._client
    _close(first)
    _close(second)


def test_the_failover_hook_is_called_as_given():
    calls = []
    config = ToolboxClientConfig(
        endpoints=PRIMARY, on_failover=lambda endpoint, error: calls.append((endpoint, error))
    )
    client = make_client(ToolboxOcrClient, config)
    error = ToolboxTimeout("slow")

    client.on_failover(client.endpoints[0], error)

    assert calls == [(ToolboxEndpoint(PRIMARY), error)]
    _close(client)
