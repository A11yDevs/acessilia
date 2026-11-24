"""The Toolbox availability gate for planning methods.

Methods whose handlers call the Toolbox are checked against one catalogue
snapshot per document. ``observe`` only reports; ``enforce`` keeps the methods
out of the plan and fails closed without a catalogue.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import replace
from pathlib import Path

import pytest
from core_config_support import core_config, toolbox_config
from pddl_support import (
    build_element as _element,
    build_manifest as _manifest,
    build_obligation as _obligation,
    build_orchestrator as _orchestrator,
)

from acessilia_core.agents.model_calls import current_model_calls
from acessilia_core.manifest.builder import DEFAULT_METHOD_COSTS
from acessilia_core.planning import toolbox_gate
from acessilia_core.ports import RunPorts
from acessilia_sdk.toolbox import snapshot_from_payloads

CONTRACT_SNAPSHOT = Path(__file__).parent / "fixtures" / "toolbox-contract.json"
FUSE_METHODS = ["dual-provider-fusion", "single-provider", "human-review"]


def _staging_snapshot():
    """The captured staging catalogue (tests/fixtures/toolbox-contract.json)."""
    payload = json.loads(CONTRACT_SNAPSHOT.read_text(encoding="utf-8"))
    return snapshot_from_payloads(
        payload["capabilities"], payload["providers"], fetched_at=0.0
    )


def _fuse_manifest(methods=FUSE_METHODS):
    obligation = _obligation("fuse-providers", ["el-1"], methods)
    obligation.method_costs = {m: DEFAULT_METHOD_COSTS[m] for m in methods}
    return _manifest([_element("el-1", "paragraph", text="texto")], [obligation])


def _config(*, secondary="mineru", gate="observe"):
    """The default providers, whatever the environment says."""
    return replace(
        core_config(fusion={"secondary_provider": secondary}),
        toolbox=toolbox_config(
            providers={"toolbox_provider": "docling"}, availability_gate=gate
        ),
    )


def test_default_providers_pass_against_the_staging_catalogue() -> None:
    """Expects ``docling`` and ``mineru`` registered in the fixture.

    The fixture is shared with ``test_toolbox_contract_drift.py``: when
    regenerating it from a staging where either provider is not registered,
    this test fails for that reason, not because the gate regressed.
    """
    decision = toolbox_gate.evaluate(
        FUSE_METHODS, _staging_snapshot(), mode="enforce", config=_config()
    )

    assert decision.blocked == {}
    assert decision.unavailable_methods == []


def test_unregistered_secondary_provider_blocks_only_dual_fusion() -> None:
    decision = toolbox_gate.evaluate(
        FUSE_METHODS, _staging_snapshot(), mode="enforce",
        config=_config(secondary="qwen3-vl-page"),
    )

    assert list(decision.blocked) == ["dual-provider-fusion"]
    assert "qwen3-vl-page não registrado" in decision.blocked["dual-provider-fusion"][0]


def test_methods_without_toolbox_requirements_are_never_blocked() -> None:
    decision = toolbox_gate.evaluate(
        ["pandoc-table", "rep-guard", "human-review"], None, mode="enforce", config=_config()
    )
    assert decision.blocked == {}


def test_observe_reports_without_removing() -> None:
    decision = toolbox_gate.evaluate(FUSE_METHODS, None, mode="observe", config=_config())

    assert set(decision.blocked) == {"dual-provider-fusion", "single-provider"}
    assert decision.unavailable_methods == []
    assert decision.to_metadata()["applied"] is False


def test_enforce_without_a_catalogue_fails_closed() -> None:
    decision = toolbox_gate.evaluate(
        FUSE_METHODS, None, mode="enforce", config=_config(),
        catalog_error="ToolboxTimeout: slow",
    )

    # Since domain 2.4 the restriction is a problem fact: nothing is offered.
    assert decision.unavailable_methods == []
    assert sorted(decision.blocked) == ["dual-provider-fusion", "single-provider"]
    assert set(decision.requirements) == {"dual-provider-fusion", "single-provider"}
    assert decision.offered == []
    metadata = decision.to_metadata()
    assert metadata["applied"] is True
    assert metadata["catalog_revision"] is None
    assert metadata["catalog_error"] == "ToolboxTimeout: slow"


def test_enforced_gate_moves_the_plan_to_the_next_method() -> None:
    orchestrator = _orchestrator()
    manifest = _fuse_manifest()

    plan, _ = orchestrator._build_plan(
        manifest, extra_unavailable=["dual-provider-fusion"]
    )
    assert [s.method for s in plan.steps if s.method] == ["single-provider"]

    plan, _ = orchestrator._build_plan(
        manifest, extra_unavailable=["dual-provider-fusion", "single-provider"]
    )
    assert [s.method for s in plan.steps if s.method] == ["human-review"]


class _CountingCache:
    def __init__(self, snapshot=None):
        self.snapshot = snapshot
        self.calls = 0
        self.last_error = None

    async def get(self):
        self.calls += 1
        return self.snapshot


@pytest.mark.asyncio
async def test_decide_skips_the_catalogue_when_nothing_needs_it(monkeypatch) -> None:
    cache = _CountingCache()
    monkeypatch.setattr(toolbox_gate, "catalog_cache", lambda _toolbox: cache)
    manifest = _manifest(
        [_element("el-1", "table")],
        [_obligation("linearize-table", ["el-1"], ["pandoc-table", "human-review"])],
    )

    decision = await toolbox_gate.decide(manifest, _config(gate="enforce"))

    assert cache.calls == 0
    assert decision.blocked == {}


@pytest.mark.asyncio
async def test_decide_is_a_no_op_when_off(monkeypatch) -> None:
    cache = _CountingCache()
    monkeypatch.setattr(toolbox_gate, "catalog_cache", lambda _toolbox: cache)
    decision = await toolbox_gate.decide(_fuse_manifest(), _config(gate="off"))

    assert cache.calls == 0
    assert decision.mode == "off"
    assert decision.unavailable_methods == []


@pytest.mark.asyncio
async def test_decide_reads_the_cache_once(monkeypatch) -> None:
    cache = _CountingCache(_staging_snapshot())
    monkeypatch.setattr(toolbox_gate, "catalog_cache", lambda _toolbox: cache)
    decision = await toolbox_gate.decide(_fuse_manifest(), _config(gate="enforce"))

    assert cache.calls == 1
    assert decision.catalog_revision == _staging_snapshot().revision
    assert decision.blocked == {}


def test_unknown_mode_falls_back_to_observe() -> None:
    assert toolbox_gate.gate_mode(toolbox_config(availability_gate="strict")) == "observe"


def test_every_gated_method_has_a_handler() -> None:
    """A requirement for a method nobody runs would be dead configuration."""
    registered = set(_orchestrator().executor.registry.names())
    assert set(toolbox_gate.METHOD_TOOLBOX_REQUIREMENTS) <= registered


def test_runs_with_one_catalogue_source_share_its_cache(monkeypatch) -> None:
    monkeypatch.setattr(toolbox_gate, "_caches", OrderedDict())

    first = toolbox_gate.catalog_cache(toolbox_config(base_url="http://a.test"))
    again = toolbox_gate.catalog_cache(toolbox_config(base_url="http://a.test", retries=9))

    assert again is first


@pytest.mark.parametrize(
    "fields",
    [
        {"base_url": "http://b.test"},
        {"base_urls": "http://b.test,http://a.test"},
        {"api_key": "another-key"},
        {"catalog_refresh_seconds": 1},
        {"catalog_stale_seconds": 1},
    ],
)
def test_a_run_with_another_catalogue_source_gets_its_own_cache(monkeypatch, fields) -> None:
    """A snapshot is never read for a run that calls another deployment, or on other timings."""
    monkeypatch.setattr(toolbox_gate, "_caches", OrderedDict())
    base = {"base_url": "http://a.test", "base_urls": "", "api_key": "key",
            "catalog_refresh_seconds": 300, "catalog_stale_seconds": 900}

    first = toolbox_gate.catalog_cache(toolbox_config(**base))
    other = toolbox_gate.catalog_cache(toolbox_config(**(base | fields)))

    assert other is not first


@pytest.mark.asyncio
async def test_decide_reads_the_cache_of_the_run_config(monkeypatch) -> None:
    caches = []

    def cache_for(toolbox):
        caches.append(toolbox)
        return _CountingCache(_staging_snapshot())

    monkeypatch.setattr(toolbox_gate, "catalog_cache", cache_for)
    config = _config(gate="enforce")

    await toolbox_gate.decide(_fuse_manifest(), config)

    assert caches == [config.toolbox]


@pytest.mark.asyncio
async def test_a_run_takes_the_gate_decision_with_its_config(monkeypatch, tmp_path) -> None:
    """Through ``execute``: the gate gets the run's ``CoreConfig``, not the settings."""
    from types import SimpleNamespace

    from acessilia_core.pipeline import orchestrator as pddl

    class Stop(Exception):
        pass

    received = []

    async def decide(manifest, config):
        received.append(config)
        raise Stop

    async def no_step(*_args, **_kwargs):
        return None

    async def no_media(*_args, **_kwargs):
        return None, {}

    monkeypatch.setattr(pddl, "_inspect_media", no_media)
    for name in ("_classify_formula_regions", "_enrich_picture_descriptions", "_mark_inline_math",
                 "_enrich_formula_latex"):
        monkeypatch.setattr(pddl, name, no_step)
    monkeypatch.setattr(toolbox_gate, "decide", decide)
    orchestrator = _orchestrator()
    run_config = _config(gate="enforce")
    orchestrator.information_structural = SimpleNamespace(process=lambda *a, **k: _fuse_manifest())

    with pytest.raises(Stop):
        await orchestrator.execute(tmp_path / "doc.pdf", tmp_path, config=run_config, model_calls=current_model_calls(), ports=RunPorts.none())

    assert received == [run_config]


def test_a_checkpoint_without_the_mode_gets_the_mode_of_the_run() -> None:
    decision = toolbox_gate.AvailabilityDecision.from_metadata({}, toolbox_config(availability_gate="enforce"))

    assert decision.mode == "enforce"


@pytest.mark.parametrize(
    ("key", "method"),
    [
        ("toolbox_provider", "single-provider"),
        ("toolbox_pdf_provider", "vision-page-inspection"),
        ("toolbox_pdf_provider", "pymupdf-region"),
        ("toolbox_adjudicate_provider", "vlm-pairwise-judge"),
    ],
)
def test_the_providers_checked_are_the_run_config_ones(key, method) -> None:
    config = replace(
        _config(), toolbox=toolbox_config(providers={key: "not-registered-anywhere"})
    )

    decision = toolbox_gate.evaluate([method], _staging_snapshot(), mode="enforce", config=config)

    assert "not-registered-anywhere" in " ".join(decision.blocked[method])


def test_equivalent_spellings_of_the_primary_share_a_cache(monkeypatch) -> None:
    monkeypatch.setattr(toolbox_gate, "_caches", OrderedDict())

    first = toolbox_gate.catalog_cache(toolbox_config(base_url="http://a.test", base_urls=""))
    again = toolbox_gate.catalog_cache(
        toolbox_config(base_url="http://other.test", base_urls="http://a.test/,http://b.test")
    )

    assert again is first


def test_a_rotated_key_gets_its_own_cache_and_no_key_is_kept_in_the_table(monkeypatch) -> None:
    monkeypatch.setattr(toolbox_gate, "_caches", OrderedDict())

    old = toolbox_gate.catalog_cache(toolbox_config(base_url="http://a.test", api_key="old-secret"))
    new = toolbox_gate.catalog_cache(toolbox_config(base_url="http://a.test", api_key="new-secret"))

    assert new is not old
    assert not any("secret" in str(part) for key in toolbox_gate._caches for part in key)


def test_the_least_recently_used_cache_goes_past_the_bound(monkeypatch) -> None:
    monkeypatch.setattr(toolbox_gate, "_caches", OrderedDict())
    monkeypatch.setattr(toolbox_gate, "CATALOG_CACHES_MAX", 2)

    def cache(name):
        return toolbox_gate.catalog_cache(toolbox_config(base_url=f"http://{name}.test"))

    a, b = cache("a"), cache("b")
    assert cache("a") is a  # used again: "b" is now the oldest
    cache("c")

    assert len(toolbox_gate._caches) == 2
    assert cache("a") is a
    assert cache("b") is not b


def test_observe_offers_every_requirement_so_the_plan_does_not_change() -> None:
    """Option (a) of #640: the catalogue is visible in the problem, not applied."""
    decision = toolbox_gate.evaluate(FUSE_METHODS, None, mode="observe", config=_config())

    assert decision.requirements
    assert decision.offered is None
    facts = decision.catalogue_facts()
    assert all(facts.offers(pair) for pairs in facts.requirements.values() for pair in pairs)


def test_the_catalogue_facts_survive_the_checkpoint() -> None:
    decision = toolbox_gate.evaluate(
        FUSE_METHODS, None, mode="enforce", config=_config(), catalog_error="down"
    )
    restored = toolbox_gate.AvailabilityDecision.from_metadata(
        json.loads(json.dumps(decision.to_metadata())), toolbox_config()
    )

    assert restored.catalogue_facts() == decision.catalogue_facts()


def test_a_checkpoint_from_before_the_catalogue_facts_adds_none() -> None:
    restored = toolbox_gate.AvailabilityDecision.from_metadata(
        {"mode": "enforce", "blocked_methods": {"single-provider": ["x"]}}, toolbox_config()
    )

    assert restored.requirements == {}
    assert restored.catalogue_facts().requirements == {}


def test_observed_facts_are_marked_assumed_not_evidence() -> None:
    """Review of #781: in observe the offered facts are an assumption, and the
    metadata says so, naming the methods the snapshot rules out."""
    observed = toolbox_gate.evaluate(FUSE_METHODS, None, mode="observe", config=_config())
    enforced = toolbox_gate.evaluate(FUSE_METHODS, None, mode="enforce", config=_config())

    assert observed.to_metadata()["offered_source"] == "assumed"
    assert observed.to_metadata()["assumed_runnable_methods"] == ["dual-provider-fusion", "single-provider"]
    assert enforced.to_metadata()["offered_source"] == "catalogue_snapshot"
    assert enforced.to_metadata()["assumed_runnable_methods"] == []
    assert toolbox_gate.AvailabilityDecision(mode="off", catalog_revision=None).offered_source == "none"


@pytest.mark.asyncio
async def test_a_resumed_plan_keeps_the_snapshot_it_was_built_under(monkeypatch) -> None:
    """The current policy (review of #781): a resumed run reproduces the plan
    checkpoint's decision and does not read the catalogue again, so its
    replans see the same Toolbox even if the catalogue changed meanwhile.
    Revalidating on resume is #640, PR 3."""
    from types import SimpleNamespace

    from acessilia_core.pipeline.checkpointing import PHASE_PLAN, manifest_payload
    from acessilia_core.planning.planner_agent import PlannerAgent

    async def must_not_read(*_args, **_kwargs):
        raise AssertionError("a resumed plan read the catalogue again")

    monkeypatch.setattr(toolbox_gate, "decide", must_not_read)
    manifest = _fuse_manifest()
    built_under = toolbox_gate.evaluate(
        FUSE_METHODS, _staging_snapshot(), mode="enforce", config=_config()
    )
    _, plan = PlannerAgent().plan(manifest, catalogue=built_under.catalogue_facts())
    state = {
        "plan": plan.model_dump(mode="json", by_alias=True),
        "manifest": manifest_payload(manifest),
        "availability": json.loads(json.dumps(built_under.to_metadata())),
    }
    ctx = SimpleNamespace(
        checkpoints=SimpleNamespace(load=lambda phase: state if phase == PHASE_PLAN else None),
        config=_config(gate="enforce"),
    )

    restored = await _orchestrator()._load_or_build_plan(ctx, manifest)

    assert restored.availability.catalogue_facts() == built_under.catalogue_facts()
    assert restored.availability.catalog_revision == built_under.catalog_revision


#: The transitional methods when #801 classified them. The set only shrinks
#: (ADR-0028, #804): a new local document method fails here unless this baseline
#: is edited in review, with the reason.
TRANSITIONAL_BASELINE = frozenset({
    "deterministic-heading-repair", "latex-normalizer", "line-number-extractor", "norm-fix",
    "pandoc-code", "rep-guard", "tailjoin", "tailjoin-positioned", "unicode-repair",
    "verse-chunker", "xycut-order", "agreement-rule", "rescue-omitted", "skeleton-order",
    "table-smart-fusion",
    # #640 M2: the table enrichment that ran before planning, now a method of
    # the plan. The same computation, moved, not added.
    "table-enrichment",
})


def _every_method() -> set[str]:
    from acessilia_core.pipeline.handlers.registry import METHOD_HANDLERS

    return set(DEFAULT_METHOD_COSTS) | set(METHOD_HANDLERS)


def test_every_method_is_declared_or_classified() -> None:
    """A method missing from the requirements table is runnable under
    ``enforce`` whatever the catalogue says, so each one must be classified.
    Every method counts, with a cost or with a handler: the planner gives an
    unknown method the default cost."""
    undeclared = _every_method() - set(toolbox_gate.METHOD_TOOLBOX_REQUIREMENTS)
    classified = set(toolbox_gate.LOCAL_METHODS) | set(toolbox_gate.NEVER_AVAILABLE_METHODS)

    assert undeclared == classified, (
        f"declare or classify: {sorted(undeclared - classified)}; "
        f"declared or gone, unclassify: {sorted(classified - undeclared)}"
    )
    assert not set(toolbox_gate.LOCAL_METHODS) & set(toolbox_gate.NEVER_AVAILABLE_METHODS)
    assert {role for role, _ in toolbox_gate.LOCAL_METHODS.values()} <= set(toolbox_gate.LOCAL_ROLES)


def test_costs_and_handlers_match_but_for_the_never_available() -> None:
    from acessilia_core.pipeline.handlers.registry import METHOD_HANDLERS

    assert set(METHOD_HANDLERS) - set(DEFAULT_METHOD_COSTS) == set()
    assert set(DEFAULT_METHOD_COSTS) - set(METHOD_HANDLERS) == set(toolbox_gate.NEVER_AVAILABLE_METHODS)


def test_the_transitional_methods_only_shrink() -> None:
    transitional = {
        method for method, (role, _) in toolbox_gate.LOCAL_METHODS.items() if role == "transitional"
    }

    assert transitional <= TRANSITIONAL_BASELINE, sorted(transitional - TRANSITIONAL_BASELINE)


def test_every_obligation_can_escalate_to_human_review() -> None:
    """Why ruling a method out never leaves an obligation unplannable: every
    kind admits ``human-review``, last."""
    from acessilia_core.manifest.builder import (
        OBLIGATION_BY_TYPE,
        V23_OBLIGATION_BY_KIND,
    )

    admissible = [methods for _, _, methods in OBLIGATION_BY_TYPE.values()]
    admissible += [methods for _, methods in V23_OBLIGATION_BY_KIND.values()]
    assert all(methods[-1] == "human-review" for methods in admissible)


@pytest.mark.parametrize(
    ("method", "capability"),
    [("mathml", "math.convert"), ("latex-verbalizer", "math.verbalize")],
)
def test_the_formula_methods_need_the_math_transform_provider(method, capability) -> None:
    """#789: the formula handler calls the Toolbox, so enforce rules the
    methods out when the math provider does not offer the capability."""
    config = replace(
        _config(), toolbox=toolbox_config(providers={"toolbox_math_provider": "not-registered"})
    )

    offered = toolbox_gate.evaluate([method], _staging_snapshot(), mode="enforce", config=_config())
    missing = toolbox_gate.evaluate([method], _staging_snapshot(), mode="enforce", config=config)

    assert offered.requirements[method] == [(f"{capability}@1", "math-speech")]
    assert method not in offered.blocked
    assert "not-registered" in " ".join(missing.blocked[method])


@pytest.mark.parametrize(
    ("kind", "methods", "fallback"),
    [
        ("verbalize-formula", ["mathml", "latex-verbalizer", "human-review"], "human-review"),
        ("normalize-formula", ["latex-normalizer", "mathml", "human-review"], "latex-normalizer"),
    ],
)
def test_enforce_without_the_math_provider_plans_the_fallback(kind, methods, fallback) -> None:
    """The formula methods need math-speech; without it each formula kind
    plans its fallback instead of becoming unplannable."""
    from acessilia_core.planning.planner_agent import PlannerAgent

    obligation = _obligation(f"{kind}-1", ["el-1"], methods)
    obligation.kind = kind
    obligation.method_costs = {m: DEFAULT_METHOD_COSTS[m] for m in methods}
    manifest = _manifest([_element("el-1", "formula", text="x^2")], [obligation])
    decision = toolbox_gate.evaluate(methods, None, mode="enforce", config=_config())

    _, plan = PlannerAgent().plan(manifest, catalogue=decision.catalogue_facts())

    assert [step.method for step in plan.steps if step.method] == [fallback]


def test_requirements_name_the_exact_capability_version() -> None:
    """#640 PR 2: each fact binds the capability at the contract version the
    SDK client calls, the one the catalogue check requires."""
    from acessilia_sdk.toolbox import TOOLBOX_CAPABILITIES

    decision = toolbox_gate.evaluate(FUSE_METHODS, _staging_snapshot(), mode="enforce", config=_config())

    pairs = {pair for pairs in decision.requirements.values() for pair in pairs}
    assert pairs
    for capability, _ in pairs:
        # Every capability these methods call is in the SDK allowlist; the
        # bare exception is pinned by the test below.
        assert "@" in capability, f"{capability} is not versioned"
        capability_id, version = capability.split("@")
        assert int(version) == TOOLBOX_CAPABILITIES[capability_id].contract_version
    assert set(decision.offered) == pairs


def test_a_capability_outside_the_allowlist_stays_bare_and_is_never_offered(monkeypatch) -> None:
    """The catalogue publishing a capability does not authorize the core to
    call it when the SDK does not know its contract: the requirement stays
    bare, the method is blocked, nothing is offered, and enforce never makes
    the method runnable."""
    from acessilia_core.planning.domain_bundle import DomainBundle
    from acessilia_core.planning.pddl_processor import PddlProblemCompiler
    from acessilia_sdk.toolbox import Requirement

    assert toolbox_gate.capability_ref("not.a.capability") == "not.a.capability"
    monkeypatch.setitem(
        toolbox_gate.METHOD_TOOLBOX_REQUIREMENTS,
        "single-provider",
        lambda config: [Requirement("not.a.capability", "docling")],
    )

    decision = toolbox_gate.evaluate(FUSE_METHODS, _staging_snapshot(), mode="enforce", config=_config())

    assert decision.requirements["single-provider"] == [("not.a.capability", "docling")]
    assert "fora da allowlist do SDK" in " ".join(decision.blocked["single-provider"])
    assert ("not.a.capability", "docling") not in decision.offered
    compiled = PddlProblemCompiler(DomainBundle.load()).compile(
        _fuse_manifest(), catalogue=decision.catalogue_facts()
    )
    assert "single-provider" not in compiled.projection.runnable_methods


def test_versioned_requirements_survive_the_checkpoint() -> None:
    """A plan made with versioned facts replans with the same facts after a
    restart: to_metadata and from_metadata keep the version."""
    decision = toolbox_gate.evaluate(FUSE_METHODS, _staging_snapshot(), mode="enforce", config=_config())
    restored = toolbox_gate.AvailabilityDecision.from_metadata(
        json.loads(json.dumps(decision.to_metadata())), toolbox_config()
    )

    assert restored.requirements == decision.requirements
    assert restored.offered == decision.offered
    assert restored.catalogue_facts() == decision.catalogue_facts()
    assert any("@" in capability for pairs in restored.requirements.values() for capability, _ in pairs)


def test_versioned_requirements_reach_the_problem() -> None:
    from acessilia_core.planning.planner_agent import PlannerAgent

    methods = ["mathml", "latex-verbalizer", "human-review"]
    obligation = _obligation("verbalize-formula-1", ["el-1"], methods)
    obligation.kind = "verbalize-formula"
    obligation.method_costs = {m: DEFAULT_METHOD_COSTS[m] for m in methods}
    manifest = _manifest([_element("el-1", "formula", text="x^2")], [obligation])
    decision = toolbox_gate.evaluate(methods, _staging_snapshot(), mode="enforce", config=_config())

    compiled = PlannerAgent().compile_problem(manifest, catalogue=decision.catalogue_facts())

    assert "(requires mathml math-convert-1 math-speech)" in compiled.text
    assert "(offered math-verbalize-1 math-speech)" in compiled.text


def test_a_checkpoint_with_unversioned_requirements_still_restores() -> None:
    """A 0.3.10 plan checkpoint stores bare ids; its replans keep them, so the
    restored facts stay consistent with the plan they explain."""
    restored = toolbox_gate.AvailabilityDecision.from_metadata(
        {"mode": "enforce", "requirements": {"mathml": [["math.convert", "math-speech"]]},
         "offered": [["math.convert", "math-speech"]]},
        toolbox_config(),
    )

    facts = restored.catalogue_facts()
    assert facts.requirements == {"mathml": frozenset({("math.convert", "math-speech")})}
    assert facts.offers(("math.convert", "math-speech"))
