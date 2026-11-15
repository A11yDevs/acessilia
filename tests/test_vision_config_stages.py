"""Each vision stage reads its ``VisionConfig`` (ADR-0016, step 3).

The stages run on one element with the vision model, the breaker, the
semaphore and the retry pass replaced by recorders, so each test sees the
values the stage took from the config it was given, and none from the
settings.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.core.agents.provider_breaker import ProviderBreaker
from backend.core.pipeline.enrichment import formulas as formula_stage
from backend.core.pipeline.enrichment import pictures as picture_stage
from backend.core.pipeline.enrichment import tables as table_stage
from tests.core_config_support import document_config, model_config, toolbox_config, vision_config
from tests.pddl_support import build_element, build_manifest, install_formula_recognizer

#: Values unlike the service's defaults, so a stage that falls back on them fails.
VISION = vision_config(
    concurrency=3,
    breaker_threshold=4,
    region_cache_enabled=True,
    retry_pass_delay_seconds=6,
    table_visual_review=False,
)


def _record(monkeypatch, stage) -> dict[str, list]:
    """Record what ``stage`` builds from its config: agents, breakers, semaphores, retries."""
    seen: dict[str, list] = {"region_cache": [], "threshold": [], "slots": [], "delay": []}
    if hasattr(stage, "_tables_to_read"):
        tables_to_read = stage._tables_to_read
        seen["visual_review"] = []

        def record_tables(manifest, *, visual_review):
            seen["visual_review"].append(visual_review)
            return tables_to_read(manifest, visual_review=visual_review)

        monkeypatch.setattr(stage, "_tables_to_read", record_tables)

    class Vision:
        def __init__(self, mode, *, region_cache, toolbox, models):
            seen["region_cache"].append(region_cache)

        async def describe_region(self, **_kwargs):
            return None

    def breaker(threshold):
        seen["threshold"].append(threshold)
        return ProviderBreaker(threshold)

    def semaphore(value):
        seen["slots"].append(value)
        return asyncio.Semaphore(value)

    async def retry(_failed, _attempt, *, kind, breaker, delay_seconds):
        seen["delay"].append(delay_seconds)
        return 0

    for name, value in (
        ("VisionAgent", Vision),
        ("ProviderBreaker", breaker),
        ("_retry_failed", retry),
        ("asyncio", SimpleNamespace(**(vars(asyncio) | {"Semaphore": semaphore}))),
    ):
        if hasattr(stage, name):
            monkeypatch.setattr(stage, name, value)
    return seen


@pytest.mark.asyncio
async def test_the_picture_stage_reads_its_vision_config(monkeypatch) -> None:
    seen = _record(monkeypatch, picture_stage)
    monkeypatch.setattr(picture_stage, "_extract_picture_bytes", lambda *_args, **_kwargs: (b"png", 1))
    manifest = build_manifest([build_element("pic-1", "picture")], [])

    await picture_stage._enrich_picture_descriptions(
        manifest, Path("doc.pdf"), mode="medio", vision=VISION,
        toolbox=toolbox_config(),
        models=model_config(),
    )

    assert seen == {"region_cache": [True], "threshold": [4], "slots": [3], "delay": [6]}


@pytest.mark.asyncio
async def test_the_formula_classification_reads_its_vision_config(monkeypatch) -> None:
    seen = _record(monkeypatch, formula_stage)
    monkeypatch.setattr(formula_stage, "_formula_recognition_crop", lambda *a, **k: (b"png", 1))
    manifest = build_manifest([build_element("f-1", "formula", text="x")], [])

    await formula_stage._classify_formula_regions(
        manifest, Path("doc.pdf"), mode="medio", vision=VISION, breaker=ProviderBreaker(1),
        toolbox=toolbox_config(),
        models=model_config(),
    )

    assert seen["region_cache"] == [True]
    assert seen["slots"] == [3]


@pytest.mark.asyncio
async def test_the_formula_recognition_reads_its_vision_config(monkeypatch) -> None:
    seen = _record(monkeypatch, formula_stage)
    monkeypatch.setattr(formula_stage, "_formula_recognition_crop", lambda *a, **k: (b"png", 1))
    install_formula_recognizer(monkeypatch, lambda _image, **_kwargs: [{"latex": "x^2"}])
    manifest = build_manifest([build_element("f-1", "formula")], [])

    await formula_stage._enrich_formula_latex(
        manifest, Path("doc.pdf"), mode="medio", document=document_config(), vision=VISION,
        toolbox=toolbox_config(),
        models=model_config(),
    )

    assert seen == {"region_cache": [True], "threshold": [4], "slots": [3], "delay": []}


@pytest.mark.asyncio
async def test_the_table_stage_reads_its_vision_config(monkeypatch) -> None:
    seen = _record(monkeypatch, table_stage)

    class Data:
        def __init__(self, **_kwargs):
            pass

        async def process_region(self, **_kwargs):
            return None

    monkeypatch.setattr(table_stage, "DataAgent", Data)
    monkeypatch.setattr(table_stage, "_extract_picture_bytes", lambda *_args, **_kwargs: (b"png", 1))
    manifest = build_manifest([build_element("t-1", "table", text="")], [])

    await table_stage._enrich_table_structures(manifest, Path("doc.pdf"), vision=VISION, toolbox=toolbox_config(), models=model_config())

    assert seen["threshold"] == [4]
    assert seen["delay"] == [6]
    assert seen["visual_review"] == [False]
