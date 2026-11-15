"""Per-call deadlines and transport failures for DataAgent (#276, step 1)."""

import asyncio
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
import pytest_asyncio

from backend.core.agents import data_agent as data_module


async def _wait_for_event(event: Event) -> None:
    async with asyncio.timeout(2):
        while not event.is_set():
            await asyncio.sleep(0.001)


@pytest.fixture(autouse=True)
def model_factory(monkeypatch):
    factory = Mock(return_value=object())
    monkeypatch.setattr(data_module, "get_agno_model", factory)
    monkeypatch.setattr(data_module, "load_region_prompt", lambda _key: "transcribe")
    return factory


@pytest_asyncio.fixture
async def blocked_model(monkeypatch):
    started, release, finished = Event(), Event(), Event()

    def run(**_kwargs):
        started.set()
        try:
            release.wait()
            return SimpleNamespace(content="late model answer")
        finally:
            finished.set()

    monkeypatch.setattr(
        data_module, "Agent", lambda **_kwargs: SimpleNamespace(run=run)
    )
    try:
        yield SimpleNamespace(started=started, release=release, finished=finished)
    finally:
        release.set()
        if started.is_set():
            await _wait_for_event(finished)


@pytest.mark.asyncio
@pytest.mark.parametrize("classification", ["table", "formula"])
async def test_deadline_degrades_while_the_model_is_still_blocked(
    monkeypatch, blocked_model, classification
):
    monkeypatch.setattr(data_module.settings, "data_agent_timeout_seconds", 0)
    monkeypatch.setattr(data_module, "CALL_DEADLINE_GRACE_SECONDS", 0.1)
    validation = Mock(wraps=data_module.validate_structured_run)
    critical = Mock()
    monkeypatch.setattr(data_module, "validate_structured_run", validation)
    monkeypatch.setattr(data_module.logger, "critical", critical)
    call = asyncio.create_task(
        data_module.DataAgent().process_region(b"image", classification, page_num=4)
    )
    try:
        await _wait_for_event(blocked_model.started)
        assert await asyncio.wait_for(call, timeout=2) is None
        assert not blocked_model.release.is_set()
        assert not blocked_model.finished.is_set()
        validation.assert_not_called()
        critical.assert_called_once()
        assert "TimeoutError" in critical.call_args.args[0]

        blocked_model.release.set()
        await _wait_for_event(blocked_model.finished)
        await asyncio.sleep(0)
        validation.assert_not_called()
    finally:
        call.cancel()
        await asyncio.gather(call, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancellation_propagates_while_the_model_is_still_blocked(
    monkeypatch, blocked_model
):
    validation = Mock(wraps=data_module.validate_structured_run)
    monkeypatch.setattr(data_module, "validate_structured_run", validation)
    call = asyncio.create_task(data_module.DataAgent().process_region(b"image", "table"))
    try:
        await _wait_for_event(blocked_model.started)
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(call, timeout=2)
        assert not blocked_model.finished.is_set()
        validation.assert_not_called()
    finally:
        call.cancel()
        await asyncio.gather(call, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("classification", ["table", "formula"])
async def test_transient_transport_error_degrades_without_sdk_retries(
    monkeypatch, model_factory, classification
):
    run = Mock(side_effect=httpx.ReadTimeout("temporary provider timeout"))
    monkeypatch.setattr(
        data_module, "Agent", lambda **_kwargs: SimpleNamespace(run=run)
    )

    result = await data_module.DataAgent().process_region(b"image", classification)

    assert result is None
    run.assert_called_once()
    model_factory.assert_called_once()
    assert model_factory.call_args.kwargs["max_retries"] == 0
