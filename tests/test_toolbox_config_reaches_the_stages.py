"""Each stage and handler hands the run's ``ToolboxConfig`` down (ADR-0016, step 3).

``test_toolbox_config_reaches_the_factory.py`` checks that each helper builds
its client from the config it is given. These check the step above: that the
orchestrator, the stages, the handlers, the vision agent and the canonical
enricher give the helpers the run's config, and not one built from the
settings. The run's config is a distinct object, so only identity passes.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.core.agents.provider_breaker import ProviderBreaker
from backend.core.pipeline.enrichment import formulas as formula_stage
from backend.core.pipeline.enrichment import pictures as picture_stage
from backend.core.pipeline.enrichment import tables as table_stage
from tests.core_config_support import core_config, document_config, model_config, toolbox_config, vision_config
from tests.pddl_support import build_element, build_manifest

#: The run's Toolbox config: its own object, unlike one built from the settings.
RUN = toolbox_config(retries=7)
VISION = vision_config(region_cache_enabled=False, retry_pass_delay_seconds=0)


def _vision(monkeypatch, *stages, seen):
    class Vision:
        def __init__(self, mode, *, region_cache, toolbox, models):
            seen.append(("agent", toolbox))

        async def describe_region(self, **_kwargs):
            return None

    for stage in stages:
        monkeypatch.setattr(stage, "VisionAgent", Vision)


@pytest.mark.asyncio
async def test_the_picture_stage_gives_its_agent_and_crops_the_run_config(monkeypatch) -> None:
    seen: list = []
    _vision(monkeypatch, picture_stage, seen=seen)

    def crop(*_args, toolbox):
        seen.append(("crop", toolbox))
        return b"png", 1

    monkeypatch.setattr(picture_stage, "_extract_picture_bytes", crop)
    manifest = build_manifest([build_element("pic-1", "picture")], [])

    await picture_stage._enrich_picture_descriptions(
        manifest, Path("doc.pdf"), mode="medio", vision=VISION, toolbox=RUN,
        models=model_config(),
    )

    assert {kind for kind, _ in seen} == {"agent", "crop"}
    assert all(toolbox is RUN for _, toolbox in seen)


@pytest.mark.asyncio
async def test_the_table_stage_gives_its_crops_the_run_config(monkeypatch) -> None:
    seen: list = []

    class Data:
        def __init__(self, **_kwargs):
            pass

        async def process_region(self, **_kwargs):
            return None

    def crop(*_args, toolbox):
        seen.append(toolbox)
        return b"png", 1

    monkeypatch.setattr(table_stage, "DataAgent", Data)
    monkeypatch.setattr(table_stage, "_extract_picture_bytes", crop)
    manifest = build_manifest([build_element("t-1", "table", text="")], [])

    await table_stage._enrich_table_structures(
        manifest, Path("doc.pdf"), vision=VISION, toolbox=RUN,
        models=model_config(),
    )

    assert seen and all(toolbox is RUN for toolbox in seen)


@pytest.mark.asyncio
async def test_the_formula_classification_gives_its_agent_and_crops_the_run_config(
    monkeypatch,
) -> None:
    seen: list = []
    _vision(monkeypatch, formula_stage, seen=seen)

    def crop(*_args, toolbox, **_kwargs):
        seen.append(("crop", toolbox))
        return b"png", 1

    monkeypatch.setattr(formula_stage, "_formula_recognition_crop", crop)
    manifest = build_manifest([build_element("f-1", "formula", text="x")], [])

    await formula_stage._classify_formula_regions(
        manifest, Path("doc.pdf"), mode="medio", vision=VISION, toolbox=RUN,
        breaker=ProviderBreaker(3),
        models=model_config(),
    )

    assert {kind for kind, _ in seen} == {"agent", "crop"}
    assert all(toolbox is RUN for _, toolbox in seen)


@pytest.mark.asyncio
async def test_the_formula_recognition_gives_its_agent_crops_and_recognizer_the_run_config(
    monkeypatch,
) -> None:
    seen: list = []
    _vision(monkeypatch, formula_stage, seen=seen)

    def crop(*_args, toolbox, **_kwargs):
        seen.append(("crop", toolbox))
        return b"png", 1

    def recognize(image, *, toolbox, **_kwargs):
        seen.append(("recognize", toolbox))
        return []

    monkeypatch.setattr(formula_stage, "_formula_recognition_crop", crop)
    monkeypatch.setattr(formula_stage, "toolbox_recognize_formula", recognize)
    manifest = build_manifest([build_element("f-1", "formula")], [])

    await formula_stage._enrich_formula_latex(
        manifest, Path("doc.pdf"), mode="medio", document=document_config(),
        vision=VISION, toolbox=RUN,
        models=model_config(),
    )

    assert {kind for kind, _ in seen} == {"agent", "crop", "recognize"}
    assert all(toolbox is RUN for _, toolbox in seen)


def test_a_formula_crop_renders_with_the_run_config(monkeypatch) -> None:
    from docstruct.geometry.boxes import PageBox  # noqa: F401 - the type the box has

    from backend.core.manifest.models import BoundingBox, Provenance

    seen: list = []

    def formula_crop(*_args, toolbox, **_kwargs):
        seen.append(toolbox)
        return SimpleNamespace(image=b"png")

    monkeypatch.setattr(formula_stage, "_toolbox_formula_crop", formula_crop)
    element = build_element("f-1", "formula")
    element.provenance = [Provenance(page_number=1, bbox=BoundingBox(
        left=10, top=20, right=90, bottom=70, coord_origin="TOPLEFT",
    ))]

    formula_stage._formula_recognition_crop(Path("doc.pdf"), element, toolbox=RUN)

    assert seen == [RUN]
    assert seen[0] is RUN


@pytest.mark.asyncio
async def test_the_orchestrator_gives_every_toolbox_stage_the_run_config(
    monkeypatch, tmp_path
) -> None:
    from backend.core.pipeline import orchestrator as pddl
    from backend.core.pipeline import preflight
    from tests.pddl_support import build_orchestrator

    seen: dict[str, object] = {}

    def record(name):
        async def step(*_args, **kwargs):
            seen[name] = kwargs.get("toolbox")
        return step

    async def no_inspection(*_args, **_kwargs):
        return None

    for name in ("_classify_formula_regions", "_enrich_picture_descriptions",
                 "_enrich_formula_latex", "_enrich_table_structures"):
        monkeypatch.setattr(pddl, name, record(name))
    for name in ("_mark_inline_math", "_mark_table_inline_math"):
        monkeypatch.setattr(pddl, name, record(name))
    monkeypatch.setattr(preflight, "inspect_source_media", no_inspection)
    manifest = build_manifest([build_element("h", "heading", text="Title")], [])
    orchestrator = build_orchestrator(max_replans=1)
    orchestrator.config = replace(core_config(), toolbox=RUN)
    orchestrator.information_structural = SimpleNamespace(process=lambda *a, **k: manifest)

    await orchestrator.execute(tmp_path / "doc.pdf", tmp_path)

    for name in ("_classify_formula_regions", "_enrich_picture_descriptions",
                 "_enrich_formula_latex", "_enrich_table_structures"):
        assert seen[name] is RUN, name


def test_the_judge_renders_and_asks_with_the_run_config(monkeypatch) -> None:
    from backend.core.pipeline import judge

    seen: list = []

    def render(*_args, toolbox):
        seen.append(("render", toolbox))
        return b"png"

    def ask(_image, _a, _b, *, toolbox):
        seen.append(("judge", toolbox))
        return {"document": {"pB": 0.1}}

    monkeypatch.setattr(judge, "_render_page_png", render)
    monkeypatch.setattr(judge, "_judge_page", ask)
    manifest = build_manifest([build_element("p-1", "paragraph", text="x")], [])

    judge._judge_one_page(manifest, 1, "a", "b", "a", "b", toolbox=RUN)

    assert [kind for kind, _ in seen] == ["render", "judge"]
    assert all(toolbox is RUN for _, toolbox in seen)


def test_the_judge_handler_gives_the_judge_the_run_config(monkeypatch) -> None:
    from backend.core.pipeline.handlers import judge as judge_handlers

    seen: list = []

    def judge_one_page(*_args, toolbox):
        seen.append(toolbox)
        return {"content": "a", "choice": "a", "pB": 0.1}, None

    monkeypatch.setattr(judge_handlers, "_target_elements", lambda *_a: [
        SimpleNamespace(page_number=1)
    ])
    monkeypatch.setattr(judge_handlers, "_secondary_or_failure", lambda _m: ({}, None))
    monkeypatch.setattr(judge_handlers, "_judge_texts", lambda *_a: ("a", "b", "x", "y"))
    monkeypatch.setattr(judge_handlers, "should_judge", lambda *_a: True, raising=False)
    monkeypatch.setattr(judge_handlers, "_judge_one_page", judge_one_page)
    monkeypatch.setattr(judge_handlers, "_judgement_result", lambda *_a: "result")
    monkeypatch.setattr("docstruct.fusion.judge.should_judge", lambda *_a: True)

    config = replace(core_config(), toolbox=RUN)
    assert judge_handlers._handle_vlm_pairwise_judge_method(
        build_manifest([], []), "o-1", config=config
    ) == "result"
    assert seen == [RUN] and seen[0] is RUN


@pytest.mark.parametrize(
    ("handler", "helper"),
    [
        ("_handle_mathml_method", "toolbox_convert_latex"),
        ("_handle_latex_verbalizer_method", "toolbox_verbalize_latex"),
    ],
)
def test_the_math_handlers_call_the_toolbox_with_the_run_config(
    monkeypatch, handler, helper
) -> None:
    from backend.core.pipeline.handlers import formula as formula_handlers

    seen: list = []

    def call(_latex, *, toolbox):
        seen.append(toolbox)
        return "x"

    monkeypatch.setattr(formula_handlers, helper, call)
    monkeypatch.setattr(
        formula_handlers, "_formula_elements_for_obligation",
        lambda *_a: [build_element("f-1", "formula", text="x")],
    )

    getattr(formula_handlers, handler)(
        build_manifest([], []), "o-1", config=replace(core_config(), toolbox=RUN)
    )

    assert seen == [RUN] and seen[0] is RUN


def test_the_canonical_enricher_calls_the_toolbox_with_the_run_config(monkeypatch) -> None:
    from backend.core.pipeline import canonical_builder

    seen: list = []

    def convert(_latex, toolbox):
        seen.append(toolbox)
        return "<math/>"

    monkeypatch.setattr(canonical_builder, "latex_to_mathml", convert)

    canonical_builder._ToolboxMathEnricher(RUN).to_mathml("x")

    assert seen == [RUN] and seen[0] is RUN


def test_the_canonical_builder_refuses_to_enrich_without_a_toolbox_config() -> None:
    from backend.core.pipeline.canonical_builder import build_canonical_document

    with pytest.raises(TypeError, match="ToolboxConfig"):
        build_canonical_document("# Title\n\n$x$\n", title="Title")
