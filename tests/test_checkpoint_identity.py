"""A resumed run reuses a checkpoint only under the config it was written in (#549).

Each phase records the identity of the stages it holds. A run whose config
changed redoes the first phase holding a changed stage and every phase after
it; the earlier phases, and the model calls they hold, are kept.
"""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from acessilia_core.agents.model_calls import current_model_calls
from acessilia_core.pipeline import orchestrator as pddl
from acessilia_core.pipeline.checkpointing import (
    ENRICHING_STAGES,
    IDENTITY_KEY,
    PHASE_STAGES,
    RunCheckpoints,
)
from acessilia_core.ports import CHECKPOINT_PHASES, NoRegionCache, RunPorts
from acessilia_core.run_identity import PROCESSING_FIELDS, STAGE_FIELDS, stage_identity
from loguru import logger

from tests.core_config_support import core_config
from tests.pddl_support import build_element, build_manifest, build_orchestrator
from tests.test_run_ports import MemoryCheckpoints


class Stop(Exception):
    pass


def _counting_orchestrator(monkeypatch, counts):
    """Stages are stubs that count their runs; the plan run stops the job."""

    async def inspect(*_args, **_kwargs):
        counts["media"] += 1
        return None, {}

    def extract(*_args, **_kwargs):
        counts["extraction"] += 1
        return build_manifest([build_element("p-1", "paragraph", text="Text.")], [])

    async def enrich(*_args, **_kwargs):
        counts["enrichment"] += 1

    async def noop(*_args, **_kwargs):
        return None

    real_decide = pddl.toolbox_gate.decide

    async def decide(manifest, config):
        counts["planning"] += 1
        return await real_decide(manifest, replace(config, toolbox=replace(config.toolbox, availability_gate="off")))

    async def run_plan(*_args, **_kwargs):
        raise Stop

    monkeypatch.setattr(pddl, "_inspect_media", inspect)
    monkeypatch.setattr(pddl, "_classify_formula_regions", enrich)
    for name in (
        "_enrich_picture_descriptions", "_mark_inline_math", "_enrich_formula_latex",
        "_enrich_table_structures", "_mark_table_inline_math",
    ):
        monkeypatch.setattr(pddl, name, noop)
    monkeypatch.setattr(pddl.toolbox_gate, "decide", decide)
    orchestrator = build_orchestrator()
    orchestrator.information_structural = SimpleNamespace(process=extract)
    monkeypatch.setattr(orchestrator, "_run_plan", run_plan)
    return orchestrator


async def _run(orchestrator, tmp_path, config, checkpoints) -> None:
    with pytest.raises(Stop):
        await orchestrator.execute(
            tmp_path / "doc.pdf", tmp_path, config=config,
            model_calls=current_model_calls(),
            ports=RunPorts(region_cache=NoRegionCache(), checkpoints=checkpoints, operations=None),
        )


def _changed(config, group: str, **fields):
    return replace(config, **{group: replace(getattr(config, group), **fields)})


async def _resume_counts(monkeypatch, tmp_path, second) -> dict[str, int]:
    """Runs a job, then resumes it under ``second`` (a function of the first
    config); returns how many times each stage ran in the resumed run."""
    counts = dict.fromkeys(("media", "extraction", "enrichment", "planning"), 0)
    orchestrator = _counting_orchestrator(monkeypatch, counts)
    checkpoints = MemoryCheckpoints("job-549")
    first = core_config()

    await _run(orchestrator, tmp_path, first, checkpoints)
    assert counts == dict.fromkeys(counts, 1)
    counts.update(dict.fromkeys(counts, 0))
    await _run(orchestrator, tmp_path, second(first), checkpoints)
    return counts


def test_every_processing_field_belongs_to_a_stage() -> None:
    assert set().union(*STAGE_FIELDS.values()) == set(PROCESSING_FIELDS)
    assert STAGE_FIELDS["execution"] == PROCESSING_FIELDS


def test_each_phase_holds_the_stages_of_the_phases_before_it() -> None:
    previous: tuple[str, ...] = ()
    for phase in CHECKPOINT_PHASES:
        stages = PHASE_STAGES[phase]
        assert stages[: len(previous)] == previous and set(stages) <= set(STAGE_FIELDS)
        previous = stages
    assert set(ENRICHING_STAGES) == set(PHASE_STAGES["enriched"])


@pytest.mark.asyncio
async def test_the_same_config_resumes_every_phase(monkeypatch, tmp_path) -> None:
    counts = await _resume_counts(monkeypatch, tmp_path, lambda config: config)

    assert counts == {"media": 0, "extraction": 0, "enrichment": 0, "planning": 0}


@pytest.mark.asyncio
async def test_a_field_outside_the_processing_identity_changes_nothing(monkeypatch, tmp_path) -> None:
    """The Toolbox key, its retries and the region cache do not change what
    a phase produced."""
    counts = await _resume_counts(
        monkeypatch, tmp_path,
        lambda c: _changed(_changed(c, "toolbox", api_key="another", retries=9), "vision", region_cache_enabled=False),
    )

    assert counts == {"media": 0, "extraction": 0, "enrichment": 0, "planning": 0}


@pytest.mark.asyncio
async def test_a_gate_change_plans_again_from_the_enriched_manifest(monkeypatch, tmp_path) -> None:
    counts = await _resume_counts(
        monkeypatch, tmp_path, lambda c: _changed(c, "toolbox", availability_gate="enforce"),
    )

    assert counts == {"media": 0, "extraction": 0, "enrichment": 0, "planning": 1}


@pytest.mark.asyncio
async def test_a_model_change_enriches_again_from_a_new_extraction(monkeypatch, tmp_path) -> None:
    """The enrichment writes its progress into the manifest checkpoint
    (#407), which then holds no clean extraction: a model change redoes the
    extraction too, and keeps the media inspection."""
    counts = await _resume_counts(
        monkeypatch, tmp_path, lambda c: _changed(c, "models", openrouter_model="another-model"),
    )

    assert counts == {"media": 0, "extraction": 1, "enrichment": 1, "planning": 1}


@pytest.mark.asyncio
async def test_an_extraction_change_keeps_only_the_media_inspection(monkeypatch, tmp_path) -> None:
    counts = await _resume_counts(
        monkeypatch, tmp_path, lambda c: _changed(c, "fusion", judge_max_pages=c.fusion.judge_max_pages + 1),
    )

    assert counts == {"media": 0, "extraction": 1, "enrichment": 1, "planning": 1}


@pytest.mark.asyncio
async def test_a_toolbox_deployment_change_redoes_every_phase(monkeypatch, tmp_path) -> None:
    counts = await _resume_counts(
        monkeypatch, tmp_path, lambda c: _changed(c, "toolbox", base_url="http://elsewhere:8002"),
    )

    assert counts == {"media": 1, "extraction": 1, "enrichment": 1, "planning": 1}


def test_a_manifest_holding_enrichment_progress_depends_on_the_enrichment() -> None:
    """Written after the extraction, the manifest checkpoint survives a model
    change; written during the enrichment, it does not."""
    import asyncio

    config = core_config()
    other = _changed(config, "models", openrouter_model="another-model")
    manifest = build_manifest([build_element("p-1", "paragraph", text="Text.")], [])

    for enriching, reused in ((False, True), (True, False)):
        store = MemoryCheckpoints()
        asyncio.run(RunCheckpoints(store, config).save_manifest(manifest, enriching=enriching))

        assert (RunCheckpoints(store, other).load("manifest") is not None) is reused


def test_a_stale_phase_makes_the_later_ones_stale(monkeypatch) -> None:
    store = MemoryCheckpoints()
    config = core_config()
    stamps = {stage: stage_identity(config, stage) for stage in STAGE_FIELDS}
    store.phases["manifest"] = {"manifest": {}, IDENTITY_KEY: {"media": "old", "extraction": stamps["extraction"]}}
    store.phases["plan"] = {"plan": {}, IDENTITY_KEY: {s: stamps[s] for s in PHASE_STAGES["plan"]}}
    checkpoints = RunCheckpoints(store, config)

    assert checkpoints.load("manifest") is None
    assert checkpoints.load("plan") is None


def test_a_checkpoint_without_identities_is_reused_with_a_warning() -> None:
    """Written before #549: reused as it was, and said so."""
    store = MemoryCheckpoints("legacy-job")
    store.phases["plan"] = {"plan": {"steps": []}}
    messages: list[str] = []
    sink = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    try:
        payload = RunCheckpoints(store, core_config()).load("plan")
    finally:
        logger.remove(sink)

    assert payload == {"plan": {"steps": []}}
    assert any("legacy-job" in m and "predates" in m for m in messages)


def test_a_mismatch_is_logged_with_the_changed_stages() -> None:
    store = MemoryCheckpoints("job-log")
    config = core_config()
    import asyncio

    asyncio.run(RunCheckpoints(store, config).save("media", lambda: {"inspection": None}))
    messages: list[str] = []
    sink = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    try:
        loaded = RunCheckpoints(store, _changed(config, "toolbox", media_inspect_enabled=not config.toolbox.media_inspect_enabled)).load("media")
    finally:
        logger.remove(sink)

    assert loaded is None
    assert any("job-log" in m and "media" in m and "another configuration" in m for m in messages)


def test_the_identities_hold_no_credential() -> None:
    import asyncio

    store = MemoryCheckpoints()
    config = _changed(core_config(), "toolbox", api_key="sk-secret-value")
    asyncio.run(RunCheckpoints(store, config).save("media", lambda: {"inspection": None}))

    assert "sk-secret-value" not in json.dumps(store.phases)
    assert stage_identity(config, "media") == stage_identity(core_config(), "media")


def test_the_execution_checkpoint_carries_every_stage() -> None:
    """Written by the executor after each step, from its thread."""
    store = MemoryCheckpoints()
    config = core_config()
    plan = SimpleNamespace(plan_id="plan-1")

    RunCheckpoints(store, config).execution_saver(plan)({"plan_id": "plan-1", "results": []})

    stored = store.phases["execution"][IDENTITY_KEY]
    assert set(stored) == set(PHASE_STAGES["execution"])
    assert RunCheckpoints(store, config).load("execution") is not None
    assert RunCheckpoints(store, _changed(config, "vision", pdf_split_dpi=99)).load("execution") is None
