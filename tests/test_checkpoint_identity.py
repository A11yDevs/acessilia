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
from loguru import logger

from acessilia_core.agents.model_calls import current_model_calls
from acessilia_core.pipeline import orchestrator as pddl
from acessilia_core.pipeline.checkpointing import (
    ENRICHING_STAGES,
    IDENTITY_KEY,
    PHASE_STAGES,
    RunCheckpoints,
    manifest_payload,
)
from acessilia_core.pipeline.handlers import (
    formula_recognition as formula_method,
    formula_regions as regions_method,
    pictures as picture_method,
)
from acessilia_core.ports import CHECKPOINT_PHASES, NoRegionCache, RunPorts
from acessilia_core.run_identity import PROCESSING_FIELDS, STAGE_FIELDS, stage_identity
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

    async def noop(*_args, **_kwargs):
        return None

    real_decide = pddl.toolbox_gate.decide

    async def decide(manifest, config):
        counts["planning"] += 1
        return await real_decide(manifest, replace(config, toolbox=replace(config.toolbox, availability_gate="off")))

    async def run_plan(plan, planning_manifest, execution_state, checkpoints, *_args, **_kwargs):
        """Stands in for the executor: records whether the run resumed an
        execution, then writes one step's checkpoint and stops."""
        counts.setdefault("resumed_execution", []).append(execution_state is not None)
        if checkpoints.active:
            checkpoints.execution_saver(plan)({
                "plan_id": plan.plan_id, "manifest": manifest_payload(planning_manifest),
                "results": [], "replan_required": False,
            })
        raise Stop

    monkeypatch.setattr(pddl, "_inspect_media", inspect)
    # The one enrichment step left before planning (#640, M1–M4b): the
    # pictures' preparation, which is synchronous.
    def prepare(*_args, **_kwargs):
        counts["enrichment"] += 1

    monkeypatch.setattr(pddl, "_prepare_pictures", prepare)
    monkeypatch.setattr(regions_method, "_classify_formula_regions", noop)
    monkeypatch.setattr(formula_method, "_enrich_formula_latex", noop)
    monkeypatch.setattr(picture_method, "_enrich_picture_descriptions", noop)
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


async def _resume_counts(
    monkeypatch, tmp_path, second, *, between=None, with_execution=False
) -> dict[str, int]:
    """Runs a job, then resumes it under ``second`` (a function of the first
    config), after ``between(orchestrator, checkpoints)`` if given; returns
    how many times each stage ran in the resumed run, and with
    ``with_execution`` whether it resumed the execution."""
    counts = dict.fromkeys(("media", "extraction", "enrichment", "planning"), 0)
    orchestrator = _counting_orchestrator(monkeypatch, counts)
    checkpoints = MemoryCheckpoints("job-549")
    first = core_config()

    await _run(orchestrator, tmp_path, first, checkpoints)
    first_resumed = counts.pop("resumed_execution")
    assert first_resumed == [False]
    assert counts == dict.fromkeys(counts, 1)
    counts.update(dict.fromkeys(counts, 0))
    if between is not None:
        between(orchestrator, checkpoints)
    await _run(orchestrator, tmp_path, second(first), checkpoints)
    resumed = counts.pop("resumed_execution")
    if with_execution:
        counts["execution"] = 0 if resumed == [True] else 1
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
        monkeypatch, tmp_path, lambda c: _changed(c, "toolbox", availability_gate="off"),
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


@pytest.mark.asyncio
async def test_the_same_config_resumes_the_execution(monkeypatch, tmp_path) -> None:
    counts = await _resume_counts(monkeypatch, tmp_path, lambda c: c, with_execution=True)

    assert counts == {"media": 0, "extraction": 0, "enrichment": 0, "planning": 0, "execution": 0}


@pytest.mark.asyncio
async def test_an_execution_only_field_redoes_only_the_execution(monkeypatch, tmp_path) -> None:
    """``vision.pdf_split_dpi`` is read by the inspection handlers alone
    (review of #578)."""
    counts = await _resume_counts(
        monkeypatch, tmp_path, lambda c: _changed(c, "vision", pdf_split_dpi=c.vision.pdf_split_dpi + 1),
        with_execution=True,
    )

    assert counts == {"media": 0, "extraction": 0, "enrichment": 0, "planning": 0, "execution": 1}


@pytest.mark.asyncio
async def test_a_toolbox_deployment_change_redoes_the_execution_too(monkeypatch, tmp_path) -> None:
    counts = await _resume_counts(
        monkeypatch, tmp_path, lambda c: _changed(c, "toolbox", base_url="http://elsewhere:8002"),
        with_execution=True,
    )

    assert counts == {"media": 1, "extraction": 1, "enrichment": 1, "planning": 1, "execution": 1}


@pytest.mark.asyncio
async def test_switching_to_a_dry_run_does_not_resume_a_real_execution(monkeypatch, tmp_path) -> None:
    """Review of #578: a dry run cannot resume an execution checkpoint (the
    executor refuses), so turning PDDL_EXECUTE_DRY_RUN on between two runs
    must redo the execution, not fail the job."""
    def dry(orchestrator, _checkpoints):
        orchestrator.execute_dry_run = True

    counts = await _resume_counts(monkeypatch, tmp_path, lambda c: c, between=dry, with_execution=True)

    assert counts == {"media": 0, "extraction": 0, "enrichment": 0, "planning": 0, "execution": 1}


@pytest.mark.asyncio
async def test_a_planner_change_plans_again(monkeypatch, tmp_path) -> None:
    def internal_only(orchestrator, _checkpoints):
        orchestrator.preferred_plan = "fast-downward"

    counts = await _resume_counts(monkeypatch, tmp_path, lambda c: c, between=internal_only, with_execution=True)

    assert counts == {"media": 0, "extraction": 0, "enrichment": 0, "planning": 1, "execution": 1}


@pytest.mark.asyncio
async def test_an_injected_planning_engine_plans_again(monkeypatch, tmp_path) -> None:
    """A job resumed with another planning engine (#632) does not reuse the
    plan of the first one."""
    from acessilia_core.planning.engine import PddlPlanningEngine

    class OtherEngine(PddlPlanningEngine):
        @property
        def identity(self) -> str:
            return "other"

    def inject(orchestrator, _checkpoints):
        orchestrator.planning_engine = OtherEngine()

    counts = await _resume_counts(monkeypatch, tmp_path, lambda c: c, between=inject, with_execution=True)

    assert counts == {"media": 0, "extraction": 0, "enrichment": 0, "planning": 1, "execution": 1}


@pytest.mark.asyncio
async def test_a_new_domain_version_plans_again(monkeypatch, tmp_path) -> None:
    """A saved plan is bound to its domain, which the executor checks; after a
    domain change the job plans again instead of failing on resume (#640)."""
    from acessilia_core.planning.domain_bundle import DEFAULT_DOMAIN_DIR, DomainBundle

    def older_domain(orchestrator, _checkpoints):
        orchestrator.executor.domain = DomainBundle.load(
            DEFAULT_DOMAIN_DIR / "domain_v2.3.pddl", DEFAULT_DOMAIN_DIR / "domain_description_v2.3.md"
        )

    counts = await _resume_counts(monkeypatch, tmp_path, lambda c: c, between=older_domain, with_execution=True)

    assert counts == {"media": 0, "extraction": 0, "enrichment": 0, "planning": 1, "execution": 1}


@pytest.mark.asyncio
async def test_a_new_model_revision_enriches_again(monkeypatch, tmp_path) -> None:
    """The service's model revision, declared on its checkpoint port, is part
    of the enrichment's and the execution's identity."""
    def bump(_orchestrator, checkpoints):
        checkpoints.options = {"enrichment": {"processing_model_revision": "weights-2"},
                               "execution": {"processing_model_revision": "weights-2"}}

    counts = await _resume_counts(monkeypatch, tmp_path, lambda c: c, between=bump, with_execution=True)

    assert counts == {"media": 0, "extraction": 1, "enrichment": 1, "planning": 1, "execution": 1}


def test_the_service_declares_its_model_revision(monkeypatch) -> None:
    from backend.config.settings import settings
    from backend.services.run_ports import service_run_ports

    monkeypatch.setattr(settings, "processing_model_revision", "weights-7")
    options = service_run_ports("job-7").checkpoints.options

    assert options["enrichment"] == {"processing_model_revision": "weights-7"}
    assert options["execution"] == {"processing_model_revision": "weights-7"}


def test_a_stamped_execution_snapshot_still_resumes() -> None:
    """The identity rides along in the payload; the executor's resume reads
    the same fields as before."""
    from acessilia_core.execution.executor import ExecutionResume
    from acessilia_core.execution.models import ExecutionStepResult
    from acessilia_core.manifest.models import ProcessingManifest

    store = MemoryCheckpoints()
    config = core_config()
    manifest = build_manifest([build_element("p-1", "paragraph", text="Text.")], [])
    RunCheckpoints(store, config).execution_saver(SimpleNamespace(plan_id="plan-1"))(
        {"plan_id": "plan-1", "manifest": manifest_payload(manifest), "results": [], "replan_required": False}
    )
    state = RunCheckpoints(store, config).load("execution")

    resume = ExecutionResume(
        manifest=ProcessingManifest.model_validate(state["manifest"]),
        results=[ExecutionStepResult.model_validate(item) for item in state.get("results") or []],
        replan_required=bool(state.get("replan_required")),
    )
    assert resume.manifest.manifest_id == manifest.manifest_id


@pytest.mark.parametrize(
    "identity",
    [{"media": "x"}, "not-a-mapping", ["media"], None],
    ids=["partial", "string", "list", "null"],
)
def test_a_partial_or_unreadable_identity_is_not_a_match(identity) -> None:
    """Review of #578: only a complete identity for the phase's stages is
    reused; a partial or malformed one is redone."""
    config = core_config()
    store = MemoryCheckpoints("job-bad")
    store.phases["manifest"] = {"manifest": {}, IDENTITY_KEY: identity}
    if isinstance(identity, dict):
        identity["media"] = stage_identity(config, "media")

    assert RunCheckpoints(store, config).load("manifest") is None


def test_the_planning_stage_holds_what_the_gate_reads() -> None:
    """The gate resolves the dual fusion's secondary provider (review of #578)."""
    assert "fusion.secondary_provider" in STAGE_FIELDS["planning"]
    assert "toolbox.availability_gate" in STAGE_FIELDS["planning"]


def test_normalizer_upgrade_changes_cache_key_and_invalidates_all_stamped_phases():
    from backend.service import _cache_version

    config = core_config()
    old_providers = dict(config.toolbox.providers)
    old_providers.pop("toolbox_text_normalize_provider")
    previous = replace(config, toolbox=replace(config.toolbox, providers=old_providers))
    assert _cache_version(previous) != _cache_version(config)
    store = MemoryCheckpoints("normalization-upgrade")
    for phase, stages in PHASE_STAGES.items():
        store.phases[phase] = {IDENTITY_KEY: {stage: stage_identity(previous, stage) for stage in stages}}
    resumed = RunCheckpoints(store, config)
    assert all(resumed.load(phase) is None for phase in CHECKPOINT_PHASES)
