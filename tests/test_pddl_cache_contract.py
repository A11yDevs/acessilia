"""Execution policy must be part of the cached-document contract."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_pending_fixes import isolated_runtime as runtime_fixture

isolated_runtime = runtime_fixture


@pytest.mark.parametrize("field,value", [
    ("pddl_execute_dry_run", False), ("pddl_max_replans", 99),
    ("pddl_planner_backend", "fast-downward"), ("pddl_preferred_plan", "fast-downward"),
    ("pddl_fast_downward", "/another/planner"),
    ("pddl_fast_downward_alias", "another-alias"),
    ("pddl_fast_downward_search", "astar(lmcut())"),
])
def test_execution_configuration_invalidates_document_cache(monkeypatch, field, value):
    from backend import service

    if field == "pddl_execute_dry_run":
        monkeypatch.setattr(service.settings, field, True)
    before = service._cache_version()
    monkeypatch.setattr(service.settings, field, value)
    assert service._cache_version() != before


def test_domain_identity_invalidates_document_cache(monkeypatch):
    from backend import service
    from backend.core.planning.domain_bundle import DomainBundle

    before = service._cache_version()
    monkeypatch.setattr(DomainBundle, "load", lambda: SimpleNamespace(
        domain_sha256="new-domain", description_sha256="new-description"
    ))
    assert service._cache_version() != before


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["dry-run-completed", "failed", "replan-required"])
async def test_live_processing_rejects_incompatible_cached_execution(
    isolated_runtime, monkeypatch, tmp_path, status
):
    from backend import service

    source = tmp_path / "doc.pdf"
    source.write_bytes(b"%PDF")
    calls = []

    async def stale_cache(*args):
        return {"text": "Cached content", "canonical_metadata": {"pddl_execution_status": status}}

    async def execute(*args, **kwargs):
        calls.append(True)
        raise RuntimeError("Live validation rejected the document")

    async def forbidden(*args, **kwargs):
        pytest.fail("An unsuccessful live execution must not be cached")

    monkeypatch.setattr(service.settings, "pddl_execute_dry_run", False)
    monkeypatch.setattr(service, "get_cached", stale_cache)
    monkeypatch.setattr(service, "set_cache", forbidden)
    monkeypatch.setattr(service, "agente", SimpleNamespace(executar=execute))
    with pytest.raises(RuntimeError, match="Live validation"):
        await service.process(source, task_id="live-from-cache")
    assert calls == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("cacheable", [True, False])
async def test_degraded_processing_is_not_cached(
    isolated_runtime, monkeypatch, tmp_path, cacheable
):
    """A run degraded by a Toolbox failure must not be replayed from the cache."""
    from backend import service

    source = tmp_path / "doc.pdf"
    source.write_bytes(b"%PDF")
    cached = []

    async def no_cache(*args):
        return None

    async def execute(*args, **kwargs):
        return {"text": "Live content", "cacheable": cacheable}

    async def record(*args, **kwargs):
        cached.append(True)

    monkeypatch.setattr(service, "get_cached", no_cache)
    monkeypatch.setattr(service, "set_cache", record)
    monkeypatch.setattr(service, "agente", SimpleNamespace(executar=execute))
    await service.process(source, task_id=f"degraded-{cacheable}")
    assert cached == ([True] if cacheable else [])


@pytest.mark.asyncio
async def test_cached_entry_with_failed_media_inspection_is_ignored(
    isolated_runtime, monkeypatch, tmp_path
):
    """A degraded entry written before the `cacheable` flag is not replayed."""
    from backend import service

    source = tmp_path / "doc.pdf"
    source.write_bytes(b"%PDF")
    calls = []

    async def degraded_cache(*args):
        return {
            "text": "Cached content",
            "canonical_metadata": {
                "pddl_media_inspection": {"status": "failed", "error": "ToolboxError: down"}
            },
        }

    async def execute(*args, **kwargs):
        calls.append(True)
        return {"text": "Live content"}

    async def record(*args, **kwargs):
        pass

    monkeypatch.setattr(service, "get_cached", degraded_cache)
    monkeypatch.setattr(service, "set_cache", record)
    monkeypatch.setattr(service, "agente", SimpleNamespace(executar=execute))
    await service.process(source, task_id="degraded-from-cache")
    assert calls == [True]



def _payload(manifest):
    from backend.agents import pddl_orchestrator as pddl

    plan = SimpleNamespace(plan_id="p-1", planner="internal", expected_total_cost=0)
    return pddl.build_pddl_structured_payload(
        file_path=Path("deck.pdf"), manifest=manifest, plan=plan,
        planner_backend="internal",
        execution_report=SimpleNamespace(status="completed", execution_id="test"),
        comparison=None,
    )


def _warnings(failures):
    from backend.agents.pddl_orchestrator import MSG_PICTURES_NOT_DESCRIBED, MSG_TABLES_NOT_READ
    from backend.i18n import n

    expected = []
    for kind, msgids in (("pictures", MSG_PICTURES_NOT_DESCRIBED), ("tables", MSG_TABLES_NOT_READ)):
        if count := sum((failures or {}).get(kind, {}).values()):
            expected.append(n(*msgids, count).format(count=count))
    return expected


@pytest.mark.parametrize(
    "elements, failures",
    [
        # 006.pdf v5: the vision provider failed partway through the deck.
        ([("picture", {"vision_failure_reason": "model_failed"}),
          ("picture", {"vision_failure_reason": "crop_unavailable"}),
          ("table", {"table_read_failure": "model_failed"})],
         {"pictures": {"model_failed": 1, "crop_unavailable": 1}, "tables": {"model_failed": 1}}),
        # A mostly visual deck: its placeholders keep their type when the model fails.
        ([("group", {"vision_failure_reason": "model_failed"}),
          ("paragraph", {"vision_failure_reason": "model_failed"})],
         {"pictures": {"model_failed": 2}}),
        # An empty description is the model's answer and would come back the same.
        ([("picture", {"vision_failure_reason": "empty_description"})], None),
        ([("picture", {"vision_description_complete": True})], None),
    ],
    ids=["provider-failed", "placeholders-failed", "empty-description", "all-described"],
)
def test_a_run_the_vision_model_failed_is_not_cacheable(elements, failures):
    from tests.pddl_support import build_element, build_manifest

    manifest = build_manifest(
        [build_element(f"e-{i}", kind, text="", metadata=metadata)
         for i, (kind, metadata) in enumerate(elements)],
        [],
    )
    payload = _payload(manifest)

    assert payload["canonical_metadata"]["pddl_visual_failures"] == failures
    assert payload["cacheable"] is (failures is None)
    for warning in _warnings(failures):
        assert warning in payload["technical_warnings"]


def _enrich_tables(monkeypatch, table, *, image, reading):
    from backend.agents import pddl_orchestrator as pddl
    from backend.config.settings import settings
    from tests.pddl_support import build_manifest

    class FakeDataAgent:
        async def process_region(self, **kwargs):
            return reading

    async def run_inline(function, *args):
        return function(*args)

    monkeypatch.setattr(settings, "table_visual_review", True)
    monkeypatch.setattr(pddl, "DataAgent", FakeDataAgent)
    monkeypatch.setattr(pddl, "_extract_picture_bytes", lambda *_args: (image, 1))
    monkeypatch.setattr(pddl.asyncio, "to_thread", run_inline)
    manifest = build_manifest([table], [])
    asyncio.run(pddl._enrich_table_structures(manifest, Path("/tmp/deck.pdf")))
    return _payload(manifest)


@pytest.mark.parametrize(
    "image, failures",
    [(b"image", {"tables": {"model_failed": 1}}), (None, {"tables": {"crop_unavailable": 1}})],
    ids=["provider-failed", "crop-unavailable"],
)
def test_a_table_read_from_scratch_that_failed_is_not_cacheable(monkeypatch, image, failures):
    """A table with nothing to backfill gets one reading; none coming back is a failure."""
    from tests.pddl_support import build_element

    payload = _enrich_tables(
        monkeypatch, build_element("t-1", "table", text=""), image=image, reading=None
    )

    assert payload["canonical_metadata"]["pddl_visual_failures"] == failures
    assert payload["cacheable"] is False


def test_a_refused_reading_of_a_misread_table_is_cacheable(monkeypatch):
    """A reading refused as worse than the table is the model's answer, not its failure."""
    from backend.agents.output_schemas import DataOutput
    from tests.pddl_support import build_element

    collapsed = {
        "header": [{"cells": [{"text": t, "scope": "col"} for t in ("Prefix", "symbol", "power")]}],
        "body": [{"cells": [{"text": t} for t in (
            "yota zeta exa peta tera giga mega kilo hecto deca",
            "Y Z E P T G M k h da",
            "10^24 10^21 10^18 10^15 10^12 10^9 10^6 10^3 10^2 10^1",
        )]}],
    }
    one_column = DataOutput(
        kind="table",
        rows=[{"cells": [{"text": "Prefix", "scope": "col"}]}, {"cells": [{"text": "yota"}]}],
        language="pt-BR",
        confidence=0.9,
    )
    table = build_element("t-1", "table", metadata={"table_ast": collapsed})

    payload = _enrich_tables(monkeypatch, table, image=b"image", reading=one_column)

    assert table.metadata["table_review"]["outcome"] == "kept"
    assert payload["canonical_metadata"]["pddl_visual_failures"] is None
    assert payload["cacheable"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("rerun_cacheable", [True, False], ids=["clean-rerun", "degraded-rerun"])
@pytest.mark.parametrize(
    "degraded_metadata",
    [
        {"pddl_visual_failures": {"pictures": {"model_failed": 10}}},
        {"pddl_extraction_degraded": True},
    ],
    ids=["visual-failures", "single-provider-extraction"],
)
async def test_cached_degraded_entry_is_ignored(
    isolated_runtime, monkeypatch, tmp_path, rerun_cacheable, degraded_metadata
):
    """A degraded entry is not replayed; a clean rerun replaces it, a degraded one drops it."""
    from backend import service

    source = tmp_path / "doc.pdf"
    source.write_bytes(b"%PDF")
    calls, cached, dropped = [], [], []

    async def degraded_cache(*args):
        return {
            "text": "Cached content",
            "canonical_metadata": degraded_metadata,
        }

    async def execute(*args, **kwargs):
        calls.append(True)
        return {"text": "Live content", "cacheable": rerun_cacheable}

    async def record(*args, **kwargs):
        cached.append(True)

    async def drop(*args, **kwargs):
        dropped.append(True)

    monkeypatch.setattr(service, "get_cached", degraded_cache)
    monkeypatch.setattr(service, "set_cache", record)
    monkeypatch.setattr(service, "drop_cache", drop)
    monkeypatch.setattr(service, "agente", SimpleNamespace(executar=execute))
    await service.process(source, task_id=f"visual-failures-from-cache-{rerun_cacheable}")
    assert calls == [True]
    assert cached == ([True] if rerun_cacheable else [])
    assert dropped == ([] if rerun_cacheable else [True])


@pytest.mark.parametrize(
    "failures, recorded",
    [
        (None, False),
        ({}, False),
        ({"pictures": {}, "tables": {"model_failed": 0}}, False),
        ({"pictures": 3}, False),
        ({"tables": {"crop_unavailable": 1}}, True),
    ],
)
def test_records_visual_failures(failures, recorded):
    from backend.agents.pddl_orchestrator import records_visual_failures

    assert records_visual_failures(failures) is recorded


@pytest.mark.parametrize("fusion_degraded", [False, True])
@pytest.mark.parametrize("visual_failed", [False, True])
@pytest.mark.parametrize("execution_status", [None, "completed", "failed", "replan-required"])
def test_merged_cache_policy_requires_success_across_all_stages(
    fusion_degraded, visual_failed, execution_status
):
    """Visual recovery and fusion/execution recovery must both survive integration."""
    from backend.agents.pddl_orchestrator import build_pddl_structured_payload
    from tests.pddl_support import build_element, build_manifest
    from tests.test_pddl_orchestrator import _sample_plan

    manifest = build_manifest(
        [build_element("picture-1", "picture", metadata=(
            {"vision_failure_reason": "model_failed"} if visual_failed else {}
        ))], [],
    )
    manifest.extractor.configuration["fusion"] = {
        "status": "degraded" if fusion_degraded else "completed",
    }
    payload = build_pddl_structured_payload(
        file_path=Path("deck.pdf"), manifest=manifest, plan=_sample_plan(),
        planner_backend="internal",
        execution_report=(
            SimpleNamespace(status=execution_status, execution_id="merged-policy")
            if execution_status is not None else None
        ),
        comparison=None,
    )
    metadata = payload["canonical_metadata"]
    assert metadata["pddl_fusion"]["status"] == (
        "degraded" if fusion_degraded else "completed"
    )
    assert bool(metadata["pddl_visual_failures"]) is visual_failed
    assert payload["cacheable"] is (
        execution_status == "completed" and not fusion_degraded and not visual_failed
    )
