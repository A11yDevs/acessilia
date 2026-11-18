"""Tests for media.inspect, which runs only on the Toolbox (docs/adr/0003).

Covers the remote call, the disabled switch, failure propagation, the remote
cache choice and the orchestrator's visible degradation.
"""
from __future__ import annotations

from pathlib import Path
from acessilia_core.pipeline import payload as pipeline_payload
from types import SimpleNamespace

import pytest

from acessilia_core.toolbox import media_inspect
from acessilia_core.toolbox.media_inspect import inspect_source_media
from acessilia_core.pipeline import preflight as pipeline_preflight
from core_config_support import toolbox_config

IMAGE = Path(__file__).parent / "fixtures" / "images" / "sunset-skyline.jpeg"
INSPECTION = {
    "is_image": True,
    "artifact_nature": "standalone_image",
    "requires_visual_inspection": True,
}


class RecordingClient:
    def __init__(self, result=None, error: Exception | None = None):
        self.result = INSPECTION if result is None else result
        self.error = error
        self.calls: list[dict] = []
        self.closed = False

    async def inspect(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result

    async def close(self):
        self.closed = True


@pytest.fixture
def enabled():
    """A run whose Toolbox config turns the inspection on."""
    return toolbox_config(media_inspect_enabled=True)


@pytest.mark.asyncio
async def test_returns_the_toolbox_document(enabled) -> None:
    client = RecordingClient()

    result = await inspect_source_media(IMAGE, client=client, toolbox=enabled)

    assert result == INSPECTION
    assert client.calls[0]["file_path"] == IMAGE.resolve()
    assert client.closed is False  # a caller-owned client stays open


@pytest.mark.asyncio
async def test_owned_client_is_closed_after_a_failure(enabled, monkeypatch) -> None:
    from acessilia_core.toolbox import toolbox_client
    from acessilia_core.toolbox.toolbox_client import ToolboxError

    client = RecordingClient(error=ToolboxError("down"))
    monkeypatch.setattr(toolbox_client, "make_toolbox_client", lambda _cls, _toolbox: client)

    with pytest.raises(ToolboxError):
        await inspect_source_media(IMAGE, toolbox=enabled)

    assert client.closed is True


@pytest.mark.asyncio
async def test_disabled_skips_without_calling_the_toolbox(monkeypatch) -> None:
    from acessilia_core.toolbox import toolbox_client

    def fail(_cls):
        raise AssertionError("the Toolbox must not be called when disabled")

    monkeypatch.setattr(toolbox_client, "make_toolbox_client", fail)

    toolbox = toolbox_config(media_inspect_enabled=False)
    assert await inspect_source_media(IMAGE, toolbox=toolbox) is None


@pytest.mark.asyncio
async def test_toolbox_failure_propagates(enabled) -> None:
    from acessilia_core.toolbox.toolbox_client import ToolboxContractViolation

    client = RecordingClient(error=ToolboxContractViolation("invalid response"))

    with pytest.raises(ToolboxContractViolation):
        await inspect_source_media(IMAGE, client=client, toolbox=enabled)


@pytest.mark.asyncio
@pytest.mark.parametrize("use_remote_cache", [True, False])
async def test_forwards_the_remote_cache_choice(use_remote_cache) -> None:
    """The run's ``ToolboxConfig.use_remote_cache`` reaches the client."""
    client = RecordingClient()
    toolbox = toolbox_config(media_inspect_enabled=True, use_remote_cache=use_remote_cache)

    await inspect_source_media(IMAGE, client=client, toolbox=toolbox)

    assert client.calls[0]["use_remote_cache"] is use_remote_cache


@pytest.mark.asyncio
async def test_a_missing_document_is_a_contract_violation(enabled) -> None:
    """A client that returns no document must not crash past the client close."""
    from acessilia_core.toolbox.toolbox_client import ToolboxContractViolation

    client = RecordingClient()
    client.result = None

    with pytest.raises(ToolboxContractViolation):
        await inspect_source_media(IMAGE, client=client, toolbox=enabled)


@pytest.mark.asyncio
async def test_returns_none_for_missing_file(enabled) -> None:
    assert await inspect_source_media(Path("/tmp/does-not-exist.png"), toolbox=enabled) is None


def test_local_fallback_is_gone() -> None:
    assert not hasattr(media_inspect, "inspect_media_payload")
    assert not hasattr(media_inspect, "MEDIA_TYPE_BY_FORMAT")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("returned", "enabled_setting", "status"),
    [
        (INSPECTION, True, "toolbox"),
        (None, False, "disabled"),
        (None, True, "source_missing"),
    ],
)
async def test_orchestrator_records_the_inspection_status(
    monkeypatch, returned, enabled_setting, status
) -> None:
    toolbox = toolbox_config(media_inspect_enabled=enabled_setting)
    received = []

    async def fake(_path, *, toolbox):
        received.append(toolbox)
        return returned

    monkeypatch.setattr(pipeline_preflight, "inspect_source_media", fake)
    result, configuration = await pipeline_preflight._inspect_media(IMAGE, toolbox=toolbox)

    assert received == [toolbox]

    assert result == returned
    assert configuration == {"media_inspection": status}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "cause"),
    [
        ("toolbox", "ToolboxError: toolbox down"),
        ("other", "ValueError: bad config"),
    ],
)
async def test_orchestrator_degrades_and_records_the_cause_on_failure(
    monkeypatch, error, cause
) -> None:
    """Any exception degrades the step, not only a ToolboxError."""
    from acessilia_core.toolbox.toolbox_client import ToolboxError

    async def fail(_path, *, toolbox):
        if error == "toolbox":
            raise ToolboxError("toolbox down")
        raise ValueError("bad config")

    monkeypatch.setattr(pipeline_preflight, "inspect_source_media", fail)
    result, configuration = await pipeline_preflight._inspect_media(IMAGE, toolbox=toolbox_config())

    assert result is None
    assert configuration == {
        "media_inspection": "failed",
        "media_inspection_error": cause,
    }


@pytest.mark.asyncio
async def test_orchestrator_does_not_swallow_cancellation(monkeypatch) -> None:
    import asyncio

    async def cancelled(_path, *, toolbox):
        raise asyncio.CancelledError

    monkeypatch.setattr(pipeline_preflight, "inspect_source_media", cancelled)

    with pytest.raises(asyncio.CancelledError):
        await pipeline_preflight._inspect_media(IMAGE, toolbox=toolbox_config())


@pytest.mark.parametrize(
    ("status", "cacheable"),
    [("toolbox", True), ("disabled", True), ("failed", False), (None, True)],
)
def test_payload_records_the_status_and_skips_the_cache_on_failure(
    monkeypatch, status, cacheable
) -> None:

    configuration = {} if status is None else {"media_inspection": status}
    if status == "failed":
        configuration["media_inspection_error"] = "ToolboxError: down"
    manifest = SimpleNamespace(
        extractor=SimpleNamespace(configuration=configuration),
        manifest_id="m-1",
        revision=1,
        obligations=[],
    )
    plan = SimpleNamespace(plan_id="p-1", planner="internal", expected_total_cost=0)
    monkeypatch.setattr(pipeline_payload, "_manifest_pages_to_payload", lambda _manifest: [])

    payload = pipeline_payload.build_pddl_structured_payload(
        file_path=IMAGE, manifest=manifest, plan=plan,
        planner_backend="internal",
        execution_report=SimpleNamespace(status="completed", execution_id="test"),
        comparison=None,
    )

    expected = (
        None
        if status is None
        else {
            "status": status,
            "error": "ToolboxError: down" if status == "failed" else None,
            "document_genre": None,
            "genre_signals": [],
        }
    )
    assert payload["canonical_metadata"]["pddl_media_inspection"] == expected
    assert payload["cacheable"] is cacheable
