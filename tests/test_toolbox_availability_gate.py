"""The Toolbox availability gate for planning methods.

Methods whose handlers call the Toolbox are checked against one catalogue
snapshot per document. ``observe`` only reports; ``enforce`` keeps the methods
out of the plan and fails closed without a catalogue.
"""

from __future__ import annotations

from acessilia_core.ports import RunPorts

from acessilia_core.agents.model_calls import current_model_calls

from collections import OrderedDict

import json
from dataclasses import replace
from pathlib import Path

import pytest

from acessilia_sdk.toolbox import snapshot_from_payloads
from acessilia_core.manifest.builder import DEFAULT_METHOD_COSTS
from acessilia_core.planning import toolbox_gate
from tests.core_config_support import core_config, toolbox_config
from tests.pddl_support import (
    build_element as _element,
    build_manifest as _manifest,
    build_obligation as _obligation,
    build_orchestrator as _orchestrator,
)

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

    assert decision.unavailable_methods == ["dual-provider-fusion", "single-provider"]
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
                 "_enrich_formula_latex", "_enrich_table_structures", "_mark_table_inline_math"):
        monkeypatch.setattr(pddl, name, no_step)
    monkeypatch.setattr(toolbox_gate, "decide", decide)
    orchestrator = _orchestrator()
    run_config = _config(gate="enforce")
    orchestrator.information_structural = SimpleNamespace(process=lambda *a, **k: _fuse_manifest())

    with pytest.raises(Stop):
        await orchestrator.execute(tmp_path / "doc.pdf", tmp_path, config=run_config, model_calls=current_model_calls(), ports=RunPorts.none())

    assert received == [run_config]


def test_a_checkpoint_without_the_mode_gets_the_mode_of_the_run() -> None:
    from acessilia_core.pipeline.orchestrator import _availability_from

    decision = _availability_from({}, toolbox_config(availability_gate="enforce"))

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
