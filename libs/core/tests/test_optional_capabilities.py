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
OPTIONAL = (
    "picture-description", "formula-recognizer", "table-enrichment", "formula-region-classifier",
    "inline-math-marker",
)
#: The ones whose optional calls include ``pdf.render``: the inline math only
#: reads the text layer (``document.text.spans``).
RENDERING = tuple(method for method in OPTIONAL if method != "inline-math-marker")


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
    """Without ``pdf.render`` the methods that render run degraded; none is
    blocked, none gets a requirement, so the planner keeps them."""
    decision = toolbox_gate.evaluate(
        OPTIONAL, _snapshot(without=("pdf.render",)), mode=mode, config=_config(mode)
    )

    assert set(decision.degraded) == set(RENDERING)
    assert all("pdf.render" in " ".join(reasons) for reasons in decision.degraded.values())
    assert decision.blocked == {}
    assert not set(decision.catalogue_facts().requirements) & set(OPTIONAL)
    metadata = decision.to_metadata()
    assert set(metadata["degraded_methods"]) == set(RENDERING)
    assert metadata["applied"] is False


def test_without_the_text_layer_the_inline_math_and_the_tables_degrade() -> None:
    """``document.text.spans`` is optional for the inline math (M4b) and for
    the tables' cell marks."""
    decision = toolbox_gate.evaluate(
        OPTIONAL, _snapshot(without=("document.text.spans",)), mode="enforce", config=_config("enforce")
    )

    assert set(decision.degraded) == {"inline-math-marker", "table-enrichment"}
    assert decision.blocked == {}


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


# The review of #856.


def test_a_generator_of_methods_is_checked_like_a_list() -> None:
    """Item 1: ``evaluate`` read its argument twice; a generator lost the
    required checks on the second pass."""
    snapshot = _snapshot(without=("pdf.render",))

    from_list = toolbox_gate.evaluate(["pymupdf-region"], snapshot, mode="enforce", config=_config("enforce"))
    from_generator = toolbox_gate.evaluate(
        (method for method in ["pymupdf-region"]), snapshot, mode="enforce", config=_config("enforce")
    )

    assert from_generator.blocked == from_list.blocked != {}


def test_an_empty_provider_is_the_one_the_client_calls() -> None:
    """Item 2: an empty provider setting is the registry default, as the
    client resolves it, for required and optional calls alike; it no longer
    blocks a method the client runs."""
    config = replace(
        core_config(),
        toolbox=toolbox_config(providers={"toolbox_pdf_provider": ""}, availability_gate="enforce"),
    )

    decision = toolbox_gate.evaluate(
        ["pymupdf-region", "picture-description"], _snapshot(), mode="enforce", config=config
    )

    assert decision.blocked == {}
    assert decision.requirements["pymupdf-region"] == [("pdf.render@2", "pymupdf-pdf")]
    assert decision.optional["picture-description"] == [("pdf.render@2", "pymupdf-pdf")]


@pytest.mark.asyncio
async def test_off_reads_no_catalogue_for_optional_calls(monkeypatch) -> None:
    reads: list[int] = []

    class Cache:
        last_error = None

        async def get(self):
            reads.append(1)

    monkeypatch.setattr(toolbox_gate, "catalog_cache", lambda _toolbox: Cache())
    describe = build_obligation("describe-images", ["p-1"], ["picture-description", "human-review"])

    decision = await toolbox_gate.decide(build_manifest([build_element("p-1", "picture")], [describe]), _config("off"))

    assert reads == [] and decision.degraded == {}


@pytest.mark.asyncio
async def test_the_report_is_per_method_not_per_document(monkeypatch) -> None:
    """Item 3, pinned until #859: a DOCX picture carries its bytes and never
    needs ``pdf.render``, yet its method is reported as one that *may* run
    degraded. Change this test only with #859."""

    class Cache:
        last_error = None

        async def get(self):
            return _snapshot(without=("pdf.render",))

    monkeypatch.setattr(toolbox_gate, "catalog_cache", lambda _toolbox: Cache())
    describe = build_obligation("describe-images", ["p-1"], ["picture-description", "human-review"])
    manifest = build_manifest([build_element("p-1", "picture")], [describe])
    manifest.source.media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    decision = await toolbox_gate.decide(manifest, _config("enforce"))

    assert list(decision.degraded) == ["picture-description"]


def test_a_degraded_method_reaches_the_output_and_the_log(monkeypatch, tmp_path) -> None:
    """Item 5: the warning and ``degraded_methods`` in the delivered
    ``pddl_toolbox_availability``, through a real run."""
    import asyncio
    from types import SimpleNamespace

    from pddl_support import build_orchestrator

    from acessilia_core.agents.model_calls import current_model_calls
    from acessilia_core.pipeline import orchestrator as pddl, preflight
    from acessilia_core.pipeline.handlers import (
        formula_regions as regions_method,
        pictures as picture_method,
    )
    from acessilia_core.ports import RunPorts

    async def nothing(*_args, **_kwargs):
        return None

    async def decide(manifest, config):
        return toolbox_gate.evaluate(
            toolbox_gate.requested_methods(manifest), _snapshot(without=("pdf.render",)),
            mode="observe", config=config,
        )

    warnings: list[str] = []
    monkeypatch.setattr(pddl.logger, "warning", lambda message, *args: warnings.append(message.format(*args)))
    monkeypatch.setattr(toolbox_gate, "decide", decide)
    monkeypatch.setattr(preflight, "inspect_source_media", nothing)
    monkeypatch.setattr(regions_method, "_classify_formula_regions", nothing)
    monkeypatch.setattr(picture_method, "_enrich_picture_descriptions", nothing)
    prose = build_element(
        "prose", "paragraph",
        text="A paragraph with enough words to make the document read as text, not as a picture.",
    )
    manifest = build_manifest([prose, build_element("p-1", "picture", text="A chart")], [])
    orchestrator = build_orchestrator(max_replans=1)
    orchestrator.information_structural = SimpleNamespace(process=lambda *a, **k: manifest)

    payload = asyncio.run(orchestrator.execute(
        tmp_path / "doc.pdf", tmp_path, structured_output=True, config=_config("observe"),
        model_calls=current_model_calls(), ports=RunPorts.none(),
    ))

    availability = payload["canonical_metadata"]["pddl_toolbox_availability"]
    assert list(availability["degraded_methods"]) == ["picture-description"]
    assert any("may run degraded" in message and "picture-description" in message for message in warnings)
