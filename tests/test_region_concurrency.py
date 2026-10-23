"""Region descriptions run concurrently, bounded by ``VISION_CONCURRENCY``.

The stage used to describe pictures strictly one after another: a document
with dozens of images paid the model latency once per image, sequentially.
The bounded gather keeps the model provider inside its accepted load while
overlapping the calls.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.agents.output_schemas import VisionOutput
from backend.agents.pddl_orchestrator import _enrich_picture_descriptions
from backend.config.settings import settings
from tests.pddl_support import (
    build_element as _element,
)
from tests.pddl_support import (
    build_manifest as _manifest,
)


@pytest.mark.asyncio
async def test_picture_descriptions_run_bounded_and_concurrently(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(settings, "vision_concurrency", 2)

    manifest = _manifest(
        [_element(f"pic-{index}", "picture") for index in range(1, 5)],
        [],
    )
    current = peak = 0

    async def fake_describe_region(**_kwargs):
        nonlocal current, peak
        current += 1
        peak = max(peak, current)
        try:
            # Long enough that every admitted call overlaps, short enough to
            # keep the suite fast.
            await asyncio.sleep(0.05)
        finally:
            current -= 1
        return VisionOutput(
            kind="description",
            description="Uma figura de teste.",
            language="pt-BR",
            confidence=0.9,
        )

    class FakeVision:
        def __init__(self, mode: str) -> None:
            self.mode = mode

        async def describe_region(self, **kwargs):
            return await fake_describe_region(**kwargs)

    def fake_extract(*_args, **_kwargs):
        return b"image-bytes", 1

    monkeypatch.setattr(
        "backend.agents.pddl_orchestrator.VisionAgent", FakeVision
    )
    monkeypatch.setattr(
        "backend.agents.pddl_orchestrator._extract_picture_bytes", fake_extract
    )

    await _enrich_picture_descriptions(manifest, tmp_path / "doc.pdf", mode="medio")

    # Two ran at once, never three: the semaphore bounds the provider load.
    assert peak == 2
    assert all(
        element.metadata.get("vision_description_complete")
        for element in manifest.elements
    )
    assert all(element.text == "Uma figura de teste." for element in manifest.elements)
