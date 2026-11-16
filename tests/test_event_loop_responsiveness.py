"""Regressões para inferências que não podem bloquear o event loop da API."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

import pytest

from backend.core.agents.data_agent import DataAgent
from backend.core.agents.output_schemas import DataOutput, VisionOutput
from backend.core.agents.vision_agent import VisionAgent
from tests.core_config_support import model_config, toolbox_config


BLOCK_SECONDS = 0.2
MAX_TICK_SECONDS = 0.1


class _BlockingAgent:
    def __init__(self, **kwargs: object) -> None:
        self.output_schema = kwargs["output_schema"]

    def run(self, **_kwargs: object):
        time.sleep(BLOCK_SECONDS)
        if self.output_schema is VisionOutput:
            content: Any = VisionOutput(
                kind="description",
                description="resultado",
                language="pt-BR",
                confidence=0.9,
                mentioned_elements=[],
            )
        else:
            content = DataOutput(
                kind="table",
                rows=[{"cells": [{"text": "resultado"}]}],
                language="pt-BR",
                confidence=0.9,
            )
        return type("Response", (), {"content": content})()


async def _assert_event_loop_is_responsive(
    inference: Callable[[], Awaitable[Any]],
    expected_type: type,
) -> None:
    """Confirma que outra coroutine roda enquanto a inferência está em curso."""
    tick = asyncio.create_task(asyncio.sleep(0.01))
    inference_task = asyncio.create_task(inference())

    started = time.monotonic()
    await tick
    elapsed = time.monotonic() - started
    assert elapsed < MAX_TICK_SECONDS, (
        f"A inferencia bloqueou o event loop por {elapsed:.3f}s"
    )
    assert isinstance(await inference_task, expected_type)


@pytest.mark.asyncio
async def test_vision_inference_does_not_block_event_loop(monkeypatch):
    monkeypatch.setattr("backend.core.agents.vision_agent.Agent", _BlockingAgent)
    monkeypatch.setattr("backend.core.agents.vision_agent.get_agno_model", lambda *_args, **_kwargs: object())
    agent = VisionAgent(region_cache=None, toolbox=toolbox_config(), models=model_config())

    await _assert_event_loop_is_responsive(
        lambda: agent.describe_region(b"image", "embedded_image"),
        VisionOutput,
    )


@pytest.mark.asyncio
async def test_data_inference_does_not_block_event_loop(monkeypatch):
    monkeypatch.setattr("backend.core.agents.data_agent.Agent", _BlockingAgent)
    monkeypatch.setattr("backend.core.agents.data_agent.get_agno_model", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("backend.core.agents.data_agent.load_region_prompt", lambda _key: "prompt")
    agent = DataAgent(models=model_config(), toolbox=toolbox_config())

    await _assert_event_loop_is_responsive(
        lambda: agent.process_region(b"image", "table"),
        DataOutput,
    )
