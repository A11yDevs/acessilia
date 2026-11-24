"""A local admission rejection is retried once and stays distinct from the provider (#590).

``ModelCallRejected`` means the application's runner is full, not that the
model provider failed. The agents retry it like a timeout (one extra attempt,
without consuming an answer try) and let it reach the stage as a retryable
reason that does not open the provider breaker.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from core_config_support import model_config, toolbox_config

from acessilia_core.agents import data_agent, vision_agent
from acessilia_core.agents.model_calls import ModelCallClosed, ModelCallRejected
from acessilia_core.agents.output_schemas import (
    DataCell,
    DataOutput,
    DataRow,
    VisionOutput,
)

_TABLE = DataOutput(
    kind="table",
    rows=[
        DataRow(cells=[DataCell(text="Element", scope="col"), DataCell(text="Mass", scope="col")]),
        DataRow(cells=[DataCell(text="H"), DataCell(text="1")]),
    ],
    language="pt-BR",
    confidence=0.9,
)

_DESCRIPTION = VisionOutput(
    kind="description",
    description="An illustrated periodic table.",
    language="pt-BR",
    confidence=0.9,
)


class RejectingRunner:
    """A runner that rejects the first ``rejections`` calls with ``error``."""

    def __init__(self, rejections: int, error: type[Exception] = ModelCallRejected) -> None:
        self.rejections = rejections
        self.error = error
        self.calls = 0

    async def run(self, call, *, timeout, label):
        self.calls += 1
        if self.calls <= self.rejections:
            raise self.error("model-call execution capacity is full")
        return SimpleNamespace(content="answer")


@pytest.fixture(autouse=True)
def no_retry_wait_and_no_real_agent(monkeypatch):
    """Keep the retry immediate and avoid constructing the provider clients."""
    monkeypatch.setattr(vision_agent, "ADMISSION_RETRY_SECONDS", 0)
    monkeypatch.setattr(data_agent, "ADMISSION_RETRY_SECONDS", 0)
    monkeypatch.setattr(vision_agent, "get_agno_model", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(data_agent, "get_agno_model", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        vision_agent, "Agent", lambda **_kwargs: SimpleNamespace(run=lambda **_kwargs: None)
    )
    monkeypatch.setattr(
        data_agent, "Agent", lambda **_kwargs: SimpleNamespace(run=lambda **_kwargs: None)
    )
    monkeypatch.setattr(data_agent, "load_region_prompt", lambda _key: "prompt")


@pytest.mark.asyncio
async def test_the_vision_agent_retries_a_rejection_once_without_spending_an_answer(monkeypatch):
    runner = RejectingRunner(rejections=1)
    monkeypatch.setattr(vision_agent, "validate_structured_run", lambda *_a, **_k: _DESCRIPTION)
    agent = vision_agent.VisionAgent(
        region_cache=None,
        toolbox=toolbox_config(),
        models=model_config(),
        model_calls=runner,
    )

    assert await agent.describe_region(b"image", "embedded_image") is _DESCRIPTION
    assert runner.calls == 2


@pytest.mark.asyncio
async def test_the_vision_agent_raises_the_rejection_after_its_one_retry(monkeypatch):
    runner = RejectingRunner(rejections=2)
    monkeypatch.setattr(vision_agent, "validate_structured_run", lambda *_a, **_k: _DESCRIPTION)
    agent = vision_agent.VisionAgent(
        region_cache=None,
        toolbox=toolbox_config(),
        models=model_config(),
        model_calls=runner,
    )

    with pytest.raises(ModelCallRejected):
        await agent.describe_region(b"image", "embedded_image")
    assert runner.calls == 2


@pytest.mark.asyncio
async def test_the_data_agent_retries_a_rejection_once(monkeypatch):
    runner = RejectingRunner(rejections=1)
    monkeypatch.setattr(data_agent, "validate_structured_run", lambda *_a, **_k: _TABLE)
    agent = data_agent.DataAgent(
        models=model_config(), toolbox=toolbox_config(), model_calls=runner
    )

    assert await agent.process_region(b"image", "table") is _TABLE
    assert runner.calls == 2


@pytest.mark.asyncio
async def test_the_data_agent_raises_the_rejection_instead_of_degrading_to_none(monkeypatch):
    runner = RejectingRunner(rejections=2)
    monkeypatch.setattr(data_agent, "validate_structured_run", lambda *_a, **_k: _TABLE)
    agent = data_agent.DataAgent(
        models=model_config(), toolbox=toolbox_config(), model_calls=runner
    )

    with pytest.raises(ModelCallRejected):
        await agent.process_region(b"image", "table")
    assert runner.calls == 2


@pytest.mark.asyncio
async def test_the_vision_agent_does_not_retry_a_closed_runner(monkeypatch):
    runner = RejectingRunner(rejections=10, error=ModelCallClosed)
    monkeypatch.setattr(vision_agent, "validate_structured_run", lambda *_a, **_k: _DESCRIPTION)
    agent = vision_agent.VisionAgent(
        region_cache=None,
        toolbox=toolbox_config(),
        models=model_config(),
        model_calls=runner,
    )

    with pytest.raises(ModelCallClosed):
        await agent.describe_region(b"image", "embedded_image")
    assert runner.calls == 1


@pytest.mark.asyncio
async def test_the_data_agent_does_not_retry_a_closed_runner(monkeypatch):
    runner = RejectingRunner(rejections=10, error=ModelCallClosed)
    monkeypatch.setattr(data_agent, "validate_structured_run", lambda *_a, **_k: _TABLE)
    agent = data_agent.DataAgent(
        models=model_config(), toolbox=toolbox_config(), model_calls=runner
    )

    with pytest.raises(ModelCallClosed):
        await agent.process_region(b"image", "table")
    assert runner.calls == 1
