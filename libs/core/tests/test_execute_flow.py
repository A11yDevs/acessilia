"""The order of the steps ``execute`` runs, and what each one receives (#402).

Characterization written on develop before ``execute`` was split. Every
enrichment step is replaced by a recorder; the plan and its execution are real.
tests/test_noncritical_obligations.py, tests/test_pddl_audit_fixes.py and
tests/test_structural_extraction_failure.py cover how a run ends.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from core_config_support import core_config
from pddl_support import (
    build_element,
    build_manifest,
    build_obligation,
    build_orchestrator,
)

from acessilia_core.agents.model_calls import current_model_calls
from acessilia_core.pipeline import preflight as pipeline_preflight
from acessilia_core.pipeline.handlers import (
    formula_recognition as formula_method,
    formula_regions as regions_method,
    inline_math as inline_method,
    pictures as picture_method,
    tables as table_method,
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

    # The prose's inline math runs inside the plan (#640, M4b).
    async def mark_inline_math(manifest, source, *args, **kwargs):
        calls.append(("_enrich_inline_math", source.name, tuple(args), dict(kwargs)))
        return {"elements": 0, "marked": 0, "unmatched": 0}

    monkeypatch.setattr(inline_method, "_enrich_inline_math", mark_inline_math)
    monkeypatch.setattr(regions_method, "_classify_formula_regions", record("_classify_formula_regions"))
    monkeypatch.setattr(formula_method, "_enrich_formula_latex", record("_enrich_formula_latex"))
    # The pictures are described inside the plan, as ``picture-description``
    # (#640, M1); the recorder describes them, so their ``describe-image`` holds.
    async def describe(manifest, source, *args, **kwargs):
        calls.append(("_enrich_picture_descriptions", source.name, tuple(args), dict(kwargs)))
        for element in manifest.elements:
            if element.id in kwargs["targets"]:
                element.text = "A description"
                element.metadata["vision_description_complete"] = True

    monkeypatch.setattr(picture_method, "_enrich_picture_descriptions", describe)
    # The table steps run inside the plan, as the ``table-enrichment`` method (#640, M2).
    monkeypatch.setattr(table_method, "_enrich_table_structures", record("_enrich_table_structures"))

    async def mark_tables(manifest, source, *args, **kwargs):
        calls.append(("_mark_table_inline_math", source.name, tuple(args), dict(kwargs)))
        return {"elements": 0, "marked": 0, "unmatched": 0}

    monkeypatch.setattr(table_method, "_mark_table_inline_math", mark_tables)
    monkeypatch.setattr(pipeline_preflight, "inspect_source_media", inspect)
    return calls


#: Enough text that the document is not mostly visual: a mostly visual one
#: without pictures has its first element described (``description_candidates``).
_PROSE = build_element(
    "prose", "paragraph",
    text="A paragraph with enough words to make the document read as text, not as a picture.",
)


async def _run(monkeypatch, tmp_path, *, config=None, elements=None, obligations=None, **kwargs):
    calls = _recorders(monkeypatch)
    manifest = build_manifest(
        [*(elements or [build_element("h", "heading", text="Titulo")]), _PROSE.model_copy(deep=True)],
        obligations or [],
    )
    orchestrator = build_orchestrator(max_replans=1)
    run_config = config or core_config()
    orchestrator.information_structural = SimpleNamespace(process=lambda *a, **k: manifest)
    statuses: list[str] = []

    async def status(message):
        statuses.append(message)

    ports = RunPorts.none()
    result = await orchestrator.execute(tmp_path / "doc.pdf", tmp_path, status_callback=status, **kwargs, config=run_config, model_calls=current_model_calls(), ports=ports)
    return result, calls, statuses, manifest


@pytest.mark.asyncio
async def test_the_steps_run_in_order_and_share_the_breaker_and_the_span_reader(monkeypatch, tmp_path) -> None:
    _, calls, _, manifest = await _run(monkeypatch, tmp_path, mode="avancado", structured_output=True)

    names = [call[0] for call in calls]
    # Without tables, pictures or formulas there is no document step inside
    # the plan (#640, M1–M4); the inline math pass runs once more after
    # execution (#599).
    assert names == ["inspect"]
    assert all(call[1] == "doc.pdf" for call in calls)
    assert manifest.extractor.configuration["region_inspection_mode"] == "avancado"


@pytest.mark.asyncio
async def test_the_tables_are_enriched_inside_the_plan_with_the_run_breaker_and_span_reader(
    monkeypatch, tmp_path
) -> None:
    """#640, M2: a document with tables gets an ``enrich-tables`` obligation;
    its ``table-enrichment`` method runs the two table steps, in order, after
    the steps before planning, with the same breaker and text-span reader."""
    config = core_config(vision={"breaker_threshold": 7})
    table = build_element("t", "table", text="a b")
    _, calls, _, manifest = await _run(monkeypatch, tmp_path, config=config, elements=[table])

    names = [call[0] for call in calls]
    assert names == ["inspect", "_enrich_table_structures", "_mark_table_inline_math"]
    by_name = {call[0]: call for call in calls}
    assert by_name["_enrich_table_structures"][3]["breaker"].threshold == 7
    assert by_name["_enrich_table_structures"][3]["vision"] is config.vision
    # The method reads the source the manifest records (the extracted file).
    assert by_name["_enrich_table_structures"][1] == Path(manifest.source.path).name


@pytest.mark.asyncio
async def test_the_pictures_are_described_inside_the_plan_with_the_run_breaker_and_mode(
    monkeypatch, tmp_path
) -> None:
    """#640, M1: a document with pictures gets a ``describe-images``
    obligation; its ``picture-description`` method describes them inside the
    plan, before their ``describe-image`` is validated, with the run's
    breaker, the mode the run recorded and the media inspection."""
    config = core_config(vision={"breaker_threshold": 7})
    picture = build_element("p", "picture", text="")
    describe_image = build_obligation("describe-image", ["p"], ["vision-description", "human-review"])
    describe_image.method_costs = {"vision-description": 20, "human-review": 100}
    _, calls, _, manifest = await _run(
        monkeypatch, tmp_path, config=config, elements=[picture], obligations=[describe_image],
        mode="avancado",
    )

    names = [call[0] for call in calls]
    assert names[:2] == ["inspect", "_enrich_picture_descriptions"]
    by_name = {call[0]: call for call in calls}
    describe = by_name["_enrich_picture_descriptions"][3]
    assert describe["breaker"].threshold == 7
    assert describe["vision"] is config.vision
    assert describe["mode"] == "avancado"
    assert describe["targets"] == frozenset({"p"})
    assert "media_inspection" in describe
    enrichment = next(item for item in manifest.obligations if item.kind == "describe-images")
    assert enrichment.target_ids == ["p"]
    assert enrichment.id in describe_image.dependencies


@pytest.mark.asyncio
async def test_the_formulas_are_recognized_inside_the_plan_with_the_run_breaker_and_mode(
    monkeypatch, tmp_path
) -> None:
    """#640, M3 and M4: a document with formulas without LaTeX gets a
    ``classify-formula-regions`` and a ``recognize-formulas`` obligation;
    their methods run inside the plan, the classification first, before
    their ``verbalize-formula``, with the run's breaker (one for both),
    document config and the mode the run recorded."""
    config = core_config(vision={"breaker_threshold": 7})
    formula = build_element("f", "formula", text="x plus y")
    verbalize = build_obligation("verbalize-formula", ["f"], ["human-review"])
    _, calls, _, manifest = await _run(
        monkeypatch, tmp_path, config=config, elements=[formula], obligations=[verbalize],
        mode="avancado",
    )

    names = [call[0] for call in calls]
    assert names[:3] == ["inspect", "_classify_formula_regions",
                         "_enrich_formula_latex"]
    by_name = {call[0]: call for call in calls}
    classify = by_name["_classify_formula_regions"][3]
    assert (classify["mode"], classify["targets"]) == ("avancado", frozenset({"f"}))
    recognize = by_name["_enrich_formula_latex"][3]
    assert recognize["breaker"] is by_name["_classify_formula_regions"][3]["breaker"]
    assert recognize["breaker"].threshold == 7
    assert recognize["vision"] is config.vision
    assert recognize["document"] is config.document
    assert recognize["mode"] == "avancado"
    assert recognize["targets"] == frozenset({"f"})
    enrichment = next(item for item in manifest.obligations if item.kind == "recognize-formulas")
    assert enrichment.target_ids == ["f"]
    assert enrichment.id in verbalize.dependencies


@pytest.mark.asyncio
async def test_the_inline_math_is_marked_inside_the_plan_before_the_formula_conversions(
    monkeypatch, tmp_path
) -> None:
    """#640, M4b: a PDF paragraph with boxes gets a ``mark-inline-math``
    obligation; its ``inline-math-marker`` method marks it inside the plan,
    and a formula's ``verbalize-formula`` waits for it although they share no
    element (the conversion reads the prose's variables)."""
    from acessilia_core.manifest.models import BoundingBox, Provenance

    paragraph = build_element("p", "paragraph", text="s ( t ) = t 3")
    paragraph.provenance = [Provenance(page_number=1, bbox=BoundingBox(
        left=50, top=100, right=500, bottom=120, coord_origin="TOPLEFT",
    ))]
    formula = build_element("f", "formula", text=r"\frac{a}{b}")
    verbalize = build_obligation("verbalize-formula", ["f"], ["human-review"])
    _, calls, _, manifest = await _run(
        monkeypatch, tmp_path, elements=[paragraph, formula], obligations=[verbalize],
    )

    mark = next(call for call in calls if call[0] == "_enrich_inline_math")
    assert mark[3]["targets"] == frozenset({"p"})
    marking = next(item for item in manifest.obligations if item.kind == "mark-inline-math")
    assert marking.id in verbalize.dependencies


@pytest.mark.asyncio
async def test_the_vision_stages_get_the_vision_config_of_the_run(monkeypatch, tmp_path) -> None:
    """ADR-0016 step 3: the run's ``VisionConfig``, not the settings, reaches each stage."""
    config = core_config(vision={"breaker_threshold": 7, "concurrency": 3})

    formula = build_element("f", "formula", text="x plus y")
    _, calls, _, _ = await _run(monkeypatch, tmp_path, config=config, elements=[formula])

    by_name = {call[0]: call[3] for call in calls}
    for stage in ("_classify_formula_regions", "_enrich_formula_latex"):
        assert by_name[stage]["vision"] is config.vision
        assert by_name[stage]["breaker"].threshold == 7


@pytest.mark.asyncio
async def test_the_toolbox_options_of_the_run_reach_each_step(monkeypatch, tmp_path) -> None:
    """ADR-0016 step 3, toolbox PR 2: media inspection, extraction, text spans, formulas."""
    from dataclasses import replace

    from core_config_support import toolbox_config

    config = replace(core_config(), toolbox=toolbox_config(use_remote_cache=False, media_inspect_enabled=False))
    _recorders(monkeypatch)
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

    assert inspected == [config.toolbox]
    assert processed == [config.toolbox, config.paths]
    assert processed[1] is config.paths
    assert manifest.extractor.configuration["media_inspection"] == "disabled"


@pytest.mark.asyncio
async def test_two_runs_at_once_each_get_their_own_vision_config(monkeypatch, tmp_path) -> None:
    """Runs share the stages, not their config: each stage call sees its own run's."""
    import asyncio

    seen: dict[frozenset, set] = {}

    async def step(manifest, source, *args, vision, targets, **kwargs):
        await asyncio.sleep(0)  # let the other run interleave
        # The plan works on a copy of the manifest: each run is told apart by
        # its own formula.
        seen.setdefault(targets, set()).add(vision)

    async def no_step(*_args, **_kwargs):
        return None

    async def inspect(path, *, toolbox):
        return None

    monkeypatch.setattr(regions_method, "_classify_formula_regions", step)
    monkeypatch.setattr(formula_method, "_enrich_formula_latex", step)
    monkeypatch.setattr(pipeline_preflight, "inspect_source_media", inspect)

    async def run(threshold):
        # A formula, so both vision steps run inside the plan.
        manifest = build_manifest([build_element(f"f-{threshold}", "formula", text="x plus y")], [])
        orchestrator = build_orchestrator(max_replans=1)
        run_config = core_config(vision={"breaker_threshold": threshold})
        orchestrator.information_structural = SimpleNamespace(process=lambda *a, **k: manifest)
        await orchestrator.execute(tmp_path / f"doc-{threshold}.pdf", tmp_path, config=run_config, model_calls=current_model_calls(), ports=RunPorts.none())
        return threshold, run_config.vision

    runs = await asyncio.gather(run(3), run(9))

    for threshold, vision in runs:
        assert seen[frozenset({f"f-{threshold}"})] == {vision}


@pytest.mark.asyncio
async def test_the_progress_messages_come_in_order(monkeypatch, tmp_path) -> None:
    _, _, statuses, _ = await _run(monkeypatch, tmp_path)

    from acessilia_core.i18n import t
    from acessilia_core.i18n.stage_messages import (
        STAGE_ANALYZING_STRUCTURAL,
        STAGE_GENERATING_PDDL_PLAN,
    )

    # Every enrichment step runs inside the plan (#640, M1–M4b): the executor
    # announces each like any other, after the plan is generated.
    expected = [t(STAGE_ANALYZING_STRUCTURAL), t(STAGE_GENERATING_PDDL_PLAN)]
    assert statuses[:2] == expected
    assert len(statuses) >= 3  # then the execution stage and its progress


@pytest.mark.asyncio
async def test_the_default_mode_is_medio_and_the_text_is_returned(monkeypatch, tmp_path) -> None:
    formula = build_element("f", "formula", text="x plus y")
    result, calls, _, manifest = await _run(monkeypatch, tmp_path, elements=[formula])

    assert isinstance(result, str) and "x plus y" in result
    assert manifest.extractor.configuration["region_inspection_mode"] == "medio"
    assert {call[3].get("mode") for call in calls if "mode" in call[3]} == {"medio"}


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [{"custom_prompt": "x"}, {"thinking_mode": True}])
async def test_custom_instructions_are_refused_before_any_step(monkeypatch, tmp_path, kwargs) -> None:
    calls = _recorders(monkeypatch)

    with pytest.raises(ValueError):
        await build_orchestrator().execute(tmp_path / "doc.pdf", tmp_path, **kwargs, config=core_config(), model_calls=current_model_calls(), ports=RunPorts.none())
    assert calls == []
