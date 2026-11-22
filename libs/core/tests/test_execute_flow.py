"""The order of the steps ``execute`` runs, and what each one receives (#402).

Characterization written on develop before ``execute`` was split. Every
enrichment step is replaced by a recorder; the plan and its execution are real.
tests/test_noncritical_obligations.py, tests/test_pddl_audit_fixes.py and
tests/test_structural_extraction_failure.py cover how a run ends.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from core_config_support import core_config
from pddl_support import build_element, build_manifest, build_orchestrator

from acessilia_core.agents.model_calls import current_model_calls
from acessilia_core.pipeline import (
    orchestrator as pddl,
    preflight as pipeline_preflight,
)
from acessilia_core.ports import RunPorts


def _recorders(monkeypatch):
    calls: list[tuple] = []

    def record(name):
        async def step(manifest, source, *args, **kwargs):
            calls.append((name, source.name, tuple(args), dict(kwargs)))
        return step

    async def inspect(path, *, toolbox):
        calls.append(("inspect", path.name, (), {}))
        return None

    for name in ("_classify_formula_regions", "_enrich_picture_descriptions", "_mark_inline_math",
                 "_enrich_formula_latex", "_enrich_table_structures", "_mark_table_inline_math"):
        monkeypatch.setattr(pddl, name, record(name))
    monkeypatch.setattr(pipeline_preflight, "inspect_source_media", inspect)
    return calls


async def _run(monkeypatch, tmp_path, *, config=None, **kwargs):
    calls = _recorders(monkeypatch)
    manifest = build_manifest([build_element("h", "heading", text="Titulo")], [])
    orchestrator = build_orchestrator(max_replans=1)
    run_config = config or core_config()
    orchestrator.information_structural = SimpleNamespace(process=lambda *a, **k: manifest)
    statuses: list[str] = []

    async def status(message):
        statuses.append(message)

    result = await orchestrator.execute(tmp_path / "doc.pdf", tmp_path, status_callback=status, **kwargs, config=run_config, model_calls=current_model_calls(), ports=RunPorts.none())
    return result, calls, statuses, manifest


@pytest.mark.asyncio
async def test_the_steps_run_in_order_and_share_the_breaker_and_the_span_reader(monkeypatch, tmp_path) -> None:
    _, calls, _, manifest = await _run(monkeypatch, tmp_path, mode="avancado", structured_output=True)

    names = [call[0] for call in calls]
    assert names == ["inspect", "_classify_formula_regions", "_enrich_picture_descriptions", "_mark_inline_math",
                     "_enrich_formula_latex", "_enrich_table_structures", "_mark_table_inline_math"]
    by_name = {call[0]: call for call in calls}
    breakers = {id(by_name[name][3]["breaker"]) for name in
                ("_classify_formula_regions", "_enrich_picture_descriptions", "_enrich_formula_latex", "_enrich_table_structures")}
    assert len(breakers) == 1
    assert by_name["_mark_inline_math"][2][0] is by_name["_mark_table_inline_math"][2][0]
    assert {by_name[name][3].get("mode") for name in ("_classify_formula_regions", "_enrich_picture_descriptions",
                                                      "_enrich_formula_latex")} == {"avancado"}
    assert "media_inspection" in by_name["_enrich_picture_descriptions"][3]
    assert all(call[1] == "doc.pdf" for call in calls)
    assert manifest.extractor.configuration["region_inspection_mode"] == "avancado"


@pytest.mark.asyncio
async def test_the_vision_stages_get_the_vision_config_of_the_run(monkeypatch, tmp_path) -> None:
    """ADR-0016 step 3: the run's ``VisionConfig``, not the settings, reaches each stage."""
    config = core_config(vision={"breaker_threshold": 7, "concurrency": 3})

    _, calls, _, _ = await _run(monkeypatch, tmp_path, config=config)

    by_name = {call[0]: call[3] for call in calls}
    stages = ("_classify_formula_regions", "_enrich_picture_descriptions",
              "_enrich_formula_latex", "_enrich_table_structures")
    assert all(by_name[name]["vision"] is config.vision for name in stages)
    assert by_name["_enrich_table_structures"]["breaker"].threshold == 7


@pytest.mark.asyncio
async def test_the_toolbox_options_of_the_run_reach_each_step(monkeypatch, tmp_path) -> None:
    """ADR-0016 step 3, toolbox PR 2: media inspection, extraction, text spans, formulas."""
    from dataclasses import replace

    from core_config_support import toolbox_config

    config = replace(core_config(), toolbox=toolbox_config(use_remote_cache=False, media_inspect_enabled=False))
    calls = _recorders(monkeypatch)
    inspected = []

    async def inspect(path, *, toolbox):
        inspected.append(toolbox)
        return None

    monkeypatch.setattr(pipeline_preflight, "inspect_source_media", inspect)
    manifest = build_manifest([build_element("h", "heading", text="Titulo")], [])
    processed = []

    def process(*_args, **kwargs):
        processed.append(kwargs["toolbox"])
        processed.append(kwargs["paths"])
        return manifest

    orchestrator = build_orchestrator(max_replans=1)
    run_config = config
    orchestrator.information_structural = SimpleNamespace(process=process)

    await orchestrator.execute(tmp_path / "doc.pdf", tmp_path, config=run_config, model_calls=current_model_calls(), ports=RunPorts.none())

    by_name = {call[0]: call for call in calls}
    assert inspected == [config.toolbox]
    assert processed == [config.toolbox, config.paths]
    assert processed[1] is config.paths
    assert by_name["_enrich_formula_latex"][3]["toolbox"] is config.toolbox
    assert by_name["_mark_inline_math"][2][1]._toolbox is config.toolbox
    assert manifest.extractor.configuration["media_inspection"] == "disabled"


@pytest.mark.asyncio
async def test_two_runs_at_once_each_get_their_own_vision_config(monkeypatch, tmp_path) -> None:
    """Runs share the stages, not their config: each stage call sees its own run's."""
    import asyncio

    seen: dict[int, set] = {}

    async def step(manifest, source, *args, vision, **kwargs):
        await asyncio.sleep(0)  # let the other run interleave
        seen.setdefault(id(manifest), set()).add(vision)

    async def no_step(*_args, **_kwargs):
        return None

    async def inspect(path, *, toolbox):
        return None

    for name in ("_classify_formula_regions", "_enrich_picture_descriptions",
                 "_enrich_formula_latex", "_enrich_table_structures"):
        monkeypatch.setattr(pddl, name, step)
    for name in ("_mark_inline_math", "_mark_table_inline_math"):
        monkeypatch.setattr(pddl, name, no_step)
    monkeypatch.setattr(pipeline_preflight, "inspect_source_media", inspect)

    async def run(threshold):
        manifest = build_manifest([build_element("h", "heading", text="Title")], [])
        orchestrator = build_orchestrator(max_replans=1)
        run_config = core_config(vision={"breaker_threshold": threshold})
        orchestrator.information_structural = SimpleNamespace(process=lambda *a, **k: manifest)
        await orchestrator.execute(tmp_path / f"doc-{threshold}.pdf", tmp_path, config=run_config, model_calls=current_model_calls(), ports=RunPorts.none())
        return manifest, run_config.vision

    runs = await asyncio.gather(run(3), run(9))

    for manifest, vision in runs:
        assert seen[id(manifest)] == {vision}


@pytest.mark.asyncio
async def test_the_progress_messages_come_in_order(monkeypatch, tmp_path) -> None:
    _, _, statuses, _ = await _run(monkeypatch, tmp_path)

    from acessilia_core.i18n import t
    from acessilia_core.i18n.stage_messages import (
        STAGE_ANALYZING_STRUCTURAL,
        STAGE_ENRICHING_IMAGE_DESCRIPTIONS,
        STAGE_ENRICHING_TABLES_OCR,
        STAGE_GENERATING_PDDL_PLAN,
    )

    expected = [t(STAGE_ANALYZING_STRUCTURAL), t(STAGE_ENRICHING_IMAGE_DESCRIPTIONS),
                t(STAGE_ENRICHING_TABLES_OCR), t(STAGE_GENERATING_PDDL_PLAN)]
    assert statuses[:4] == expected
    assert len(statuses) >= 5  # then the execution stage and its progress


@pytest.mark.asyncio
async def test_the_default_mode_is_medio_and_the_text_is_returned(monkeypatch, tmp_path) -> None:
    result, calls, _, _ = await _run(monkeypatch, tmp_path)

    assert isinstance(result, str) and "Titulo" in result
    assert {call[3].get("mode") for call in calls if "mode" in call[3]} == {"medio"}


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [{"custom_prompt": "x"}, {"thinking_mode": True}])
async def test_custom_instructions_are_refused_before_any_step(monkeypatch, tmp_path, kwargs) -> None:
    calls = _recorders(monkeypatch)

    with pytest.raises(ValueError):
        await build_orchestrator().execute(tmp_path / "doc.pdf", tmp_path, **kwargs, config=core_config(), model_calls=current_model_calls(), ports=RunPorts.none())
    assert calls == []
