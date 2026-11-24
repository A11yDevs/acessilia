"""A method's optional, degradable Toolbox capabilities (#848).

``picture-description``, ``formula-recognizer`` and ``table-enrichment`` call
the Toolbox, but each call that fails degrades one element, not the method.
They declare those calls in ``METHOD_OPTIONAL_CAPABILITIES``: the gate
reports a missing one as ``degraded_methods`` and never rules the method out.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from core_config_support import core_config, toolbox_config
from pddl_support import build_element, build_manifest, build_obligation

from acessilia_core.pipeline.handlers.registry import METHOD_HANDLERS
from acessilia_core.planning import toolbox_gate
from acessilia_sdk.toolbox import TOOLBOX_CAPABILITIES, snapshot_from_payloads

CONTRACT_SNAPSHOT = Path(__file__).parent / "fixtures" / "toolbox-contract.json"
OPTIONAL = ("picture-description", "formula-recognizer", "table-enrichment")


def _snapshot(*, without: tuple[str, ...] = ()):
    """The captured staging catalogue, less the capabilities in ``without``."""
    payload = json.loads(CONTRACT_SNAPSHOT.read_text(encoding="utf-8"))
    capabilities = [item for item in payload["capabilities"] if item["id"] not in without]
    providers = [
        {**item, "capabilities": [c for c in item["capabilities"] if c not in without]}
        for item in payload["providers"]
    ]
    return snapshot_from_payloads(capabilities, providers, fetched_at=0.0)


def _config(gate: str):
    return replace(core_config(), toolbox=toolbox_config(availability_gate=gate))


def test_a_method_is_required_or_optional_never_both() -> None:
    assert not set(toolbox_gate.METHOD_OPTIONAL_CAPABILITIES) & set(toolbox_gate.METHOD_TOOLBOX_REQUIREMENTS)
    assert set(OPTIONAL) <= set(toolbox_gate.METHOD_OPTIONAL_CAPABILITIES)
    for method, calls in toolbox_gate.METHOD_OPTIONAL_CAPABILITIES.items():
        assert method in METHOD_HANDLERS, method
        assert all(item.capability_id in TOOLBOX_CAPABILITIES for item in calls(core_config())), method


def test_the_staging_catalogue_degrades_nothing() -> None:
    decision = toolbox_gate.evaluate(OPTIONAL, _snapshot(), mode="enforce", config=_config("enforce"))

    assert decision.degraded == {}
    assert set(decision.optional) == set(OPTIONAL)
    assert decision.optional["formula-recognizer"][0][0] == toolbox_gate.capability_ref("math.recognize")


@pytest.mark.parametrize("mode", ["observe", "enforce"])
def test_a_missing_optional_capability_degrades_without_ruling_out(mode) -> None:
    """Without ``pdf.render`` the three methods run degraded; none is
    blocked, none gets a requirement, so the planner keeps them."""
    decision = toolbox_gate.evaluate(
        OPTIONAL, _snapshot(without=("pdf.render",)), mode=mode, config=_config(mode)
    )

    assert set(decision.degraded) == set(OPTIONAL)
    assert all("pdf.render" in " ".join(reasons) for reasons in decision.degraded.values())
    assert decision.blocked == {}
    assert not set(decision.catalogue_facts().requirements) & set(OPTIONAL)
    metadata = decision.to_metadata()
    assert set(metadata["degraded_methods"]) == set(OPTIONAL)
    assert metadata["applied"] is False


def test_only_the_method_that_calls_it_is_degraded() -> None:
    decision = toolbox_gate.evaluate(
        OPTIONAL, _snapshot(without=("math.recognize",)), mode="enforce", config=_config("enforce")
    )

    assert list(decision.degraded) == ["formula-recognizer"]


def test_without_a_catalogue_nothing_is_reported_degraded() -> None:
    """Without a snapshot nothing is known; ``catalog_error`` says why."""
    decision = toolbox_gate.evaluate(
        OPTIONAL, None, mode="enforce", config=_config("enforce"), catalog_error="down"
    )

    assert decision.degraded == {}
    assert decision.catalog_error == "down"


def test_the_degraded_methods_survive_the_checkpoint() -> None:
    decision = toolbox_gate.evaluate(
        OPTIONAL, _snapshot(without=("pdf.render",)), mode="enforce", config=_config("enforce")
    )

    restored = toolbox_gate.AvailabilityDecision.from_metadata(
        json.loads(json.dumps(decision.to_metadata())), _config("enforce").toolbox
    )

    assert restored.degraded == decision.degraded
    assert restored.optional == decision.optional


def test_a_checkpoint_from_before_the_optional_calls_restores_none() -> None:
    restored = toolbox_gate.AvailabilityDecision.from_metadata(
        {"mode": "enforce", "requirements": {}}, _config("enforce").toolbox
    )

    assert (restored.optional, restored.degraded) == ({}, {})


@pytest.mark.asyncio
async def test_a_document_with_only_optional_calls_reads_the_catalogue(monkeypatch) -> None:
    """A document whose only Toolbox calls are optional still has its
    catalogue read, so its degradation is reported."""
    reads: list[int] = []

    class Cache:
        last_error = None

        async def get(self):
            reads.append(1)
            return _snapshot(without=("pdf.render",))

    monkeypatch.setattr(toolbox_gate, "catalog_cache", lambda _toolbox: Cache())
    describe = build_obligation("describe-images", ["p-1"], ["picture-description", "human-review"])
    manifest = build_manifest([build_element("p-1", "picture")], [describe])

    decision = await toolbox_gate.decide(manifest, _config("observe"))

    assert reads == [1]
    assert list(decision.degraded) == ["picture-description"]
