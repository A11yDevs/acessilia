"""Execution policy must be part of the cached-document contract."""

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


def _payload(elements):
    from backend.agents import pddl_orchestrator as pddl
    from tests.pddl_support import build_manifest

    manifest = build_manifest(elements, [])
    plan = SimpleNamespace(plan_id="p-1", planner="internal", expected_total_cost=0)
    return pddl.build_pddl_structured_payload(
        file_path=__import__("pathlib").Path("deck.pdf"), manifest=manifest, plan=plan,
        planner_backend="internal", execution_report=None, comparison=None,
    )


@pytest.mark.parametrize(
    "elements, failures",
    [
        # 006.pdf v5: the vision provider failed partway through the deck.
        ([("picture", {"vision_failure_reason": "model_failed"}),
          ("picture", {"vision_failure_reason": "empty_description"}),
          ("table", {"table_review": {"reason": "collapsed_rows", "outcome": "kept", "why": "no table was read", "attempts": 3}})],
         {"pictures": 2, "tables": 1}),
        # A reading refused as worse than the table is an answer, not a failure.
        ([("table", {"table_review": {"reason": "collapsed_rows", "outcome": "kept", "why": "the new reading has 1 column(s), the table 3", "attempts": 3}})],
         None),
        ([("picture", {"vision_description_complete": True})], None),
    ],
    ids=["provider-failed", "reading-refused", "all-described"],
)
def test_a_run_the_vision_model_failed_is_not_cacheable(elements, failures):
    from tests.pddl_support import build_element

    payload = _payload(
        [build_element(f"e-{i}", kind, metadata=metadata) for i, (kind, metadata) in enumerate(elements)]
    )

    assert payload["canonical_metadata"]["pddl_model_failures"] == failures
    assert payload["cacheable"] is (failures is None)
    warned = any("Modelo de visao falhou" in w for w in payload["technical_warnings"])
    assert warned is (failures is not None)


@pytest.mark.asyncio
async def test_cached_entry_with_model_failures_is_ignored(
    isolated_runtime, monkeypatch, tmp_path
):
    """A degraded entry written before the flag covered model failures is not replayed."""
    from backend import service

    source = tmp_path / "doc.pdf"
    source.write_bytes(b"%PDF")
    calls = []

    async def degraded_cache(*args):
        return {
            "text": "Cached content",
            "canonical_metadata": {"pddl_model_failures": {"pictures": 10, "tables": 0}},
        }

    async def execute(*args, **kwargs):
        calls.append(True)
        return {"text": "Live content"}

    async def record(*args, **kwargs):
        pass

    monkeypatch.setattr(service, "get_cached", degraded_cache)
    monkeypatch.setattr(service, "set_cache", record)
    monkeypatch.setattr(service, "agente", SimpleNamespace(executar=execute))
    await service.process(source, task_id="model-failures-from-cache")
    assert calls == [True]
