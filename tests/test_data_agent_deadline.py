"""Per-call deadlines and transport failures for DataAgent (#276, step 1)."""

import asyncio
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
import pytest_asyncio

from tests.core_config_support import model_config, toolbox_config

from acessilia_core.agents import data_agent as data_module
from acessilia_core.agents import model_call_policy


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
    monkeypatch.setattr(model_call_policy, "CALL_DEADLINE_GRACE_SECONDS", 0.1)
    validation = Mock(wraps=data_module.validate_structured_run)
    monkeypatch.setattr(data_module, "validate_structured_run", validation)
    messages: list[str] = []
    sink = data_module.logger.add(messages.append, level="DEBUG", format="{message}")
    call = asyncio.create_task(
        data_module.DataAgent(models=model_config(data_agent_timeout_seconds=0), toolbox=toolbox_config()).process_region(b"image", classification, page_num=4)
    )
    try:
        await _wait_for_event(blocked_model.started)
        assert await asyncio.wait_for(call, timeout=2) is None
        assert not blocked_model.release.is_set()
        assert not blocked_model.finished.is_set()
        validation.assert_not_called()
        assert any("ModelCallTimeout" in message for message in messages)

        blocked_model.release.set()
        await _wait_for_event(blocked_model.finished)
        await asyncio.sleep(0)
        validation.assert_not_called()
    finally:
        blocked_model.release.set()
        call.cancel()
        try:
            await asyncio.gather(call, return_exceptions=True)
        finally:
            data_module.logger.remove(sink)


@pytest.mark.asyncio
async def test_cancellation_propagates_while_the_model_is_still_blocked(
    monkeypatch, blocked_model
):
    validation = Mock(wraps=data_module.validate_structured_run)
    monkeypatch.setattr(data_module, "validate_structured_run", validation)
    call = asyncio.create_task(data_module.DataAgent(models=model_config(), toolbox=toolbox_config()).process_region(b"image", "table"))
    try:
        await _wait_for_event(blocked_model.started)
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(call, timeout=2)
        assert not blocked_model.finished.is_set()
        validation.assert_not_called()
    finally:
        blocked_model.release.set()
        call.cancel()
        await asyncio.gather(call, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("classification", ["table", "formula"])
async def test_transient_error_degrades_and_requests_no_openai_retries(
    monkeypatch, model_factory, classification
):
    run = Mock(side_effect=httpx.ReadTimeout("temporary provider timeout"))
    monkeypatch.setattr(
        data_module, "Agent", lambda **_kwargs: SimpleNamespace(run=run)
    )

    result = await data_module.DataAgent(models=model_config(), toolbox=toolbox_config()).process_region(b"image", classification)

    assert result is None
    run.assert_called_once()
    model_factory.assert_called_once()
    # This checks the agent-to-factory contract. test_ai_client.py verifies
    # forwarding to OpenRouter/Toolbox; Ollama ignores this OpenAI-specific
    # option and keeps its existing retry policy.
    assert model_factory.call_args.kwargs["max_retries"] == 0
