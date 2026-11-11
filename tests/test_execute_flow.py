"""The order of the steps ``execute`` runs, and what each one receives (#402).

Characterization written on develop before ``execute`` was split. Every
enrichment step is replaced by a recorder; the plan and its execution are real.
tests/test_noncritical_obligations.py, tests/test_pddl_audit_fixes.py and
tests/test_structural_extraction_failure.py cover how a run ends.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.agents import pddl_orchestrator as pddl
from tests.pddl_support import build_element, build_manifest, build_orchestrator


def _recorders(monkeypatch):
    calls: list[tuple] = []

    def record(name):
        async def step(manifest, source, *args, **kwargs):
            calls.append((name, source.name, tuple(args), dict(kwargs)))
        return step

    async def inspect(path):
        calls.append(("inspect", path.name, (), {}))
        return None

    for name in ("_classify_formula_regions", "_enrich_picture_descriptions", "_mark_inline_math",
                 "_enrich_formula_latex", "_enrich_table_structures", "_mark_table_inline_math"):
        monkeypatch.setattr(pddl, name, record(name))
    monkeypatch.setattr(pddl, "inspect_source_media", inspect)
    return calls


async def _run(monkeypatch, tmp_path, **kwargs):
    calls = _recorders(monkeypatch)
    manifest = build_manifest([build_element("h", "heading", text="Titulo")], [])
    orchestrator = build_orchestrator(max_replans=1)
    orchestrator.information_structural = SimpleNamespace(process=lambda *a, **k: manifest)
    statuses: list[str] = []

    async def status(message):
        statuses.append(message)

    result = await orchestrator.execute(tmp_path / "doc.pdf", tmp_path, status_callback=status, **kwargs)
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
async def test_the_progress_messages_come_in_order(monkeypatch, tmp_path) -> None:
    _, _, statuses, _ = await _run(monkeypatch, tmp_path)

    from backend.i18n import t
    from backend.stage_messages import (
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
        await build_orchestrator().execute(tmp_path / "doc.pdf", tmp_path, **kwargs)
    assert calls == []
