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


def test_base_urls_take_precedence_over_base_url(monkeypatch):
    monkeypatch.setattr(settings, "toolbox_base_url", "http://balancer.test")
    monkeypatch.setattr(settings, "toolbox_base_urls", f"{PRIMARY},{SECONDARY}")

    assert [e.base_url for e in toolbox_endpoints()] == [PRIMARY, SECONDARY]


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_a_blank_list_falls_back_to_base_url(monkeypatch, blank):
    monkeypatch.setattr(settings, "toolbox_base_urls", blank)

    assert toolbox_endpoints() == (ToolboxEndpoint(PRIMARY),)


@pytest.mark.parametrize(
    "base_url", ["http://toolbox.test:bad", "http://toolbox.test:99999"]
)
def test_a_port_httpx_cannot_use_is_a_value_error(monkeypatch, base_url):
    monkeypatch.setattr(settings, "toolbox_base_url", base_url)

    with pytest.raises(ValueError, match="port between 0 and 65535"):
        toolbox_endpoints()


def test_a_malformed_entry_in_the_list_fails_loudly(monkeypatch):
    monkeypatch.setattr(settings, "toolbox_base_urls", f"{PRIMARY},localhost:8002")

    with pytest.raises(ValueError, match="absolute http"):
        toolbox_endpoints()


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


def test_retries_come_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "toolbox_retries", 3)
    monkeypatch.setattr(settings, "toolbox_retry_backoff_seconds", 0.25)

    client = make_toolbox_client(ToolboxOcrClient)

    assert (client.retries, client.retry_backoff_seconds) == (3, 0.25)
    assert make_toolbox_client(ToolboxOcrClient, retries=0).retries == 0


# ── Parity with the factory before the move to the SDK (#402, step 1) ──────
#
# ``_legacy_kwargs`` is the constructor-argument logic make_toolbox_client had
# before it delegated to acessilia_sdk.toolbox.make_client, kept here verbatim
# as the reference. Every SDK client class is built both ways, under settings
# that cover the cases the review of #402 listed, and must come out the same.

import inspect  # noqa: E402

from acessilia_sdk.toolbox import PROVIDER_DEFAULTS, ToolboxCapabilityClient  # noqa: E402
from acessilia_sdk.toolbox import clients as sdk_clients  # noqa: E402

CLIENT_CLASSES = sorted(
    (
        value
        for value in vars(sdk_clients).values()
        if inspect.isclass(value) and issubclass(value, ToolboxCapabilityClient)
    ),
    key=lambda cls: cls.__name__,
)


def _legacy_kwargs(client_cls, **overrides):
    kwargs = {
        "endpoints": toolbox_endpoints(),
        "provider": (
            getattr(settings, client_cls.provider_key) if client_cls.provider_key else None
        ),
        "timeout_seconds": settings.toolbox_timeout_seconds,
        "api_key": settings.toolbox_api_key,
        "on_failover": toolbox_client._log_failover,
        "retries": settings.toolbox_retries,
        "retry_backoff_seconds": settings.toolbox_retry_backoff_seconds,
    }
    if issubclass(client_cls, ToolboxMathClient):
        kwargs["transform_provider"] = settings.toolbox_math_provider
    if client_cls.timeout_key:
        kwargs["timeout_seconds"] = getattr(settings, client_cls.timeout_key)
    overrides = {key: value for key, value in overrides.items() if value is not None}
    if "base_url" in overrides:
        kwargs.pop("endpoints")
    kwargs.update(overrides)
    return kwargs


def _observable(client) -> dict:
    state = {
        name: value
        for name, value in vars(client).items()
        if name not in ("_clients", "_client", "_catalogs")
    }
    state["http"] = [
        (str(http.base_url), repr(http.timeout), sorted(http.headers.items()))
        for http in client._clients
    ]
    state["catalogs"] = [
        None if cache is None else (cache.refresh_seconds, cache.stale_seconds)
        for cache in client._catalogs
    ]
    return state


SETTINGS_CASES = {
    "defaults": {},
    "base_urls_win": {"toolbox_base_urls": f"{PRIMARY}, {SECONDARY}"},
    "providers": {key: f"custom-{key}" for key in PROVIDER_DEFAULTS},
    "export_timeouts": {
        "toolbox_docx_timeout_seconds": 11,
        "toolbox_pdf_ua_timeout_seconds": 22,
        "toolbox_pdf_validate_timeout_seconds": 33,
    },
    "retries": {"toolbox_retries": 3, "toolbox_retry_backoff_seconds": 0.25},
    "no_api_key": {"toolbox_api_key": ""},
}

OVERRIDE_CASES = {
    "none": {},
    "none_values": {"provider": None, "timeout_seconds": None, "retries": None},
    "base_url": {"base_url": "http://override.test"},
    "explicit": {"provider": "explicit", "timeout_seconds": 7, "retries": 0},
}


@pytest.mark.parametrize("overrides", OVERRIDE_CASES.values(), ids=OVERRIDE_CASES)
@pytest.mark.parametrize("values", SETTINGS_CASES.values(), ids=SETTINGS_CASES)
@pytest.mark.parametrize("client_cls", CLIENT_CLASSES, ids=lambda cls: cls.__name__)
def test_the_sdk_factory_builds_the_client_the_core_used_to_build(
    monkeypatch, client_cls, values, overrides
):
    for key, value in values.items():
        monkeypatch.setattr(settings, key, value)

    built = make_toolbox_client(client_cls, **overrides)
    reference = client_cls(**_legacy_kwargs(client_cls, **overrides))

    assert _observable(built) == _observable(reference)


def test_every_provider_key_and_timeout_key_is_a_setting():
    """The config maps settings by name; a missing attribute would fail late."""
    for key in PROVIDER_DEFAULTS:
        assert hasattr(settings, key), key
    assert toolbox_client.TIMEOUT_KEYS == {
        "toolbox_docx_timeout_seconds",
        "toolbox_pdf_ua_timeout_seconds",
        "toolbox_pdf_validate_timeout_seconds",
    }
    for key in toolbox_client.TIMEOUT_KEYS:
        assert hasattr(settings, key), key


def test_the_config_is_read_from_settings_on_every_call(monkeypatch):
    monkeypatch.setattr(settings, "toolbox_retries", 2)
    before = toolbox_client.toolbox_client_config()
    monkeypatch.setattr(settings, "toolbox_retries", 4)

    assert before.retries == 2
    assert toolbox_client.toolbox_client_config().retries == 4


def test_run_sync_is_imported_from_the_sdk_not_re_exported_here():
    """#402 step 2: callers import acessilia_sdk.runtime.run_sync directly."""
    assert not hasattr(toolbox_client, "run_sync")
    assert "run_sync" not in toolbox_client.__all__
