"""The run's ``ModelConfig`` reaches every model call (ADR-0016, step 3).

The orchestrator gives it to the stages, the stages and the inspection
helpers to the agents they build, and the agents to the model factory. The
run's config is a distinct object here, unlike one built from the settings,
so only identity passes.
"""

from __future__ import annotations

from backend.core.agents.model_calls import current_model_calls

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.core.agents.provider_breaker import ProviderBreaker
from backend.core.pipeline.enrichment import formulas as formula_stage
from backend.core.pipeline.enrichment import pictures as picture_stage
from backend.core.pipeline.enrichment import tables as table_stage
from backend.core.pipeline.handlers import inspection as inspection_handlers
from tests.core_config_support import (
    core_config,
    document_config,
    model_config,
    toolbox_config,
    vision_config,
)
from tests.pddl_support import build_element, build_manifest

#: The run's model config: its own object, unlike one built from the settings.
MODELS = model_config(openrouter_max_tokens=7)
TOOLBOX = toolbox_config()
VISION = vision_config(region_cache_enabled=False, retry_pass_delay_seconds=0)


def _agents(monkeypatch, *modules, seen):
    class Vision:
        def __init__(self, mode="medio", *, region_cache, toolbox, models):
            seen.append(models)

        async def describe_region(self, **_kwargs):
            return None

        async def inspect_page(self, **_kwargs):
            return None

    for module in modules:
        monkeypatch.setattr(module, "VisionAgent", Vision)


def _crops(monkeypatch):
    monkeypatch.setattr(picture_stage, "_extract_picture_bytes", lambda *_a, **_k: (b"png", 1))
    monkeypatch.setattr(table_stage, "_extract_picture_bytes", lambda *_a, **_k: (b"png", 1))
    monkeypatch.setattr(formula_stage, "_formula_recognition_crop", lambda *_a, **_k: (b"png", 1))
    monkeypatch.setattr(formula_stage, "toolbox_recognize_formula", lambda *_a, **_k: [])


@pytest.mark.asyncio
async def test_the_picture_stage_builds_its_agent_with_the_run_models(monkeypatch) -> None:
    seen: list = []
    _agents(monkeypatch, picture_stage, seen=seen)
    _crops(monkeypatch)

    await picture_stage._enrich_picture_descriptions(
        build_manifest([build_element("pic-1", "picture")], []), Path("doc.pdf"),
        mode="medio", vision=VISION, toolbox=TOOLBOX, models=MODELS,
    )

    assert seen == [MODELS] and seen[0] is MODELS


@pytest.mark.asyncio
async def test_the_formula_stages_build_their_agents_with_the_run_models(monkeypatch) -> None:
    seen: list = []
    _agents(monkeypatch, formula_stage, seen=seen)
    _crops(monkeypatch)

    await formula_stage._classify_formula_regions(
        build_manifest([build_element("f-1", "formula", text="x")], []), Path("doc.pdf"),
        mode="medio", vision=VISION, toolbox=TOOLBOX, models=MODELS,
        breaker=ProviderBreaker(3),
    )
    await formula_stage._enrich_formula_latex(
        build_manifest([build_element("f-2", "formula")], []), Path("doc.pdf"),
        mode="medio", document=document_config(), vision=VISION, toolbox=TOOLBOX,
        models=MODELS,
    )

    assert len(seen) == 2 and all(models is MODELS for models in seen)


@pytest.mark.asyncio
async def test_the_table_stage_builds_its_data_agent_with_the_run_models(monkeypatch) -> None:
    seen: list = []

    class Data:
        def __init__(self, *, models, toolbox):
            seen.append(models)

        async def process_region(self, **_kwargs):
            return None

    monkeypatch.setattr(table_stage, "DataAgent", Data)
    _crops(monkeypatch)

    await table_stage._enrich_table_structures(
        build_manifest([build_element("t-1", "table", text="")], []), Path("doc.pdf"),
        vision=VISION, toolbox=TOOLBOX, models=MODELS,
    )

    assert seen == [MODELS] and seen[0] is MODELS


@pytest.mark.parametrize("helper", ["_inspect_region", "_inspect_page"])
def test_the_inspection_helpers_build_their_agent_with_the_run_models(
    monkeypatch, helper
) -> None:
    seen: list = []
    _agents(monkeypatch, inspection_handlers, seen=seen)

    getattr(inspection_handlers, helper)(
        b"png", 1, 1, "medio", region_cache=False, toolbox=TOOLBOX, models=MODELS
    )

    assert seen == [MODELS] and seen[0] is MODELS


@pytest.mark.asyncio
async def test_the_orchestrator_gives_every_agent_stage_the_run_models(
    monkeypatch, tmp_path
) -> None:
    from backend.core.pipeline import orchestrator as pddl
    from backend.core.pipeline import preflight
    from tests.pddl_support import build_orchestrator

    seen: dict[str, object] = {}

    def record(name):
        async def step(*_args, **kwargs):
            seen[name] = kwargs.get("models")
        return step

    async def no_inspection(*_args, **_kwargs):
        return None

    stages = ("_classify_formula_regions", "_enrich_picture_descriptions",
              "_enrich_formula_latex", "_enrich_table_structures")
    for name in (*stages, "_mark_inline_math", "_mark_table_inline_math"):
        monkeypatch.setattr(pddl, name, record(name))
    monkeypatch.setattr(preflight, "inspect_source_media", no_inspection)
    manifest = build_manifest([build_element("h", "heading", text="Title")], [])
    orchestrator = build_orchestrator(max_replans=1)
    run_config = replace(core_config(), models=MODELS)
    orchestrator.information_structural = SimpleNamespace(process=lambda *a, **k: manifest)

    await orchestrator.execute(tmp_path / "doc.pdf", tmp_path, config=run_config, model_calls=current_model_calls())

    assert all(seen[name] is MODELS for name in stages), seen


class Built(Exception):
    """Raised by the recording model factory once it has seen the configs."""


@pytest.mark.asyncio
@pytest.mark.parametrize("agent", ["vision", "data"])
async def test_each_agent_builds_its_model_from_its_configs(monkeypatch, agent) -> None:
    from backend.core.agents import data_agent, vision_agent

    seen: list = []

    def factory(models, toolbox, **_options):
        seen.append((models, toolbox))
        raise Built

    for module in (vision_agent, data_agent):
        monkeypatch.setattr(module, "get_agno_model", factory)
    monkeypatch.setattr(data_agent, "load_region_prompt", lambda _key: "prompt")

    if agent == "vision":
        await vision_agent.VisionAgent(
            region_cache=False, toolbox=TOOLBOX, models=MODELS
        ).describe_region(b"png", "embedded_image")
    else:
        await data_agent.DataAgent(models=MODELS, toolbox=TOOLBOX).process_region(
            b"png", "table"
        )

    assert seen, "no model was built"
    assert all(models is MODELS and toolbox is TOOLBOX for models, toolbox in seen)
