"""Regressões para inferências que não podem bloquear o event loop da API."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

import pytest

from backend.agents.data_agent import DataAgent
from backend.agents.output_schemas import DataOutput, VisionOutput
from backend.agents.vision_agent import VisionAgent


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
    import backend.agents.vision_agent as vision_module

    monkeypatch.setattr(vision_module, "Agent", _BlockingAgent)
    monkeypatch.setattr(vision_module, "get_agno_model", lambda: object())
    agent = VisionAgent()

    await _assert_event_loop_is_responsive(
        lambda: agent.describe_region(b"image", "embedded_image"),
        VisionOutput,
    )


@pytest.mark.asyncio
async def test_data_inference_does_not_block_event_loop(monkeypatch):
    import backend.agents.data_agent as data_module

    monkeypatch.setattr(data_module, "Agent", _BlockingAgent)
    monkeypatch.setattr(data_module, "get_agno_model", lambda: object())
    monkeypatch.setattr(data_module, "load_region_prompt", lambda _key: "prompt")
    agent = DataAgent()

    await _assert_event_loop_is_responsive(
        lambda: agent.process_region(b"image", "table"),
        DataOutput,
    )
