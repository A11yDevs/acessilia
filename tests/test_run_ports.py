"""A run reaches the service's state through its ``RunPorts`` (ADR-0016, step 4)."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.core.agents.model_calls import current_model_calls
from backend.core.ports import NoRegionCache, RunPorts, region_cache_for
from tests.core_config_support import core_config, vision_config
from tests.pddl_support import build_orchestrator

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "backend" / "core"

#: Service modules the core still imports, each waiting for its step-4 pull
#: request. The list only shrinks: a new import from ``backend.services`` fails,
#: and so does an entry nobody imports any more. Empty, the boundary test of
#: step 5 can pass.
PENDING_SERVICE_IMPORTS = {
    "backend/core/pipeline/orchestrator.py": {
        "backend.services.job_checkpoint",
        "backend.services.operation_context",
    },
    "backend/core/manifest/toolbox_extractor.py": {
        "backend.services.operation_context",
        "backend.services.operation_registry",
    },
}


def _service_imports(path: Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if node.module == "backend.services":
                found |= {f"backend.services.{alias.name}" for alias in node.names}
            elif node.module.startswith("backend.services."):
                found.add(node.module)
        elif isinstance(node, ast.Import):
            found |= {a.name for a in node.names if a.name.startswith("backend.services")}
    return found


def test_the_core_imports_only_the_pending_service_modules() -> None:
    """Inside functions included: the caches and ``run_blocking`` are gone."""
    found = {
        path.relative_to(ROOT).as_posix(): imports
        for path in sorted(CORE.rglob("*.py"))
        if (imports := _service_imports(path))
    }

    assert found == PENDING_SERVICE_IMPORTS


def test_ports_outside_the_service_keep_no_state() -> None:
    ports = RunPorts.none()

    assert isinstance(ports.region_cache, NoRegionCache)


@pytest.mark.asyncio
async def test_the_no_op_region_cache_never_answers() -> None:
    cache = NoRegionCache()

    await cache.put(b"image", "variant", {"description": "stored"})

    assert await cache.get(b"image", "variant", ttl_seconds=60) is None


@pytest.mark.parametrize("enabled", [True, False])
def test_the_run_config_turns_the_region_cache_on_or_off(enabled) -> None:
    cache = NoRegionCache()
    ports = RunPorts(region_cache=cache)

    chosen = region_cache_for(ports, vision_config(region_cache_enabled=enabled))

    assert chosen is (cache if enabled else None)


@pytest.mark.asyncio
async def test_the_service_region_cache_stores_by_content_and_variant(monkeypatch, tmp_path) -> None:
    from backend.services import cache as cache_module
    from backend.services.run_ports import service_run_ports

    monkeypatch.setattr(cache_module, "CACHE_DIR", tmp_path / "cache")
    cache = service_run_ports().region_cache

    await cache.put(b"image", "variant-a", {"description": "a"})

    assert isinstance(cache, cache_module.ContentCache)
    assert await cache.get(b"image", "variant-a", ttl_seconds=60) == {"description": "a"}
    assert await cache.get(b"image", "variant-b", ttl_seconds=60) is None
    assert await cache.get(b"other", "variant-a", ttl_seconds=60) is None


@pytest.mark.asyncio
async def test_the_service_region_cache_honours_the_ttl(monkeypatch, tmp_path) -> None:
    from backend.services import cache as cache_module

    monkeypatch.setattr(cache_module, "CACHE_DIR", tmp_path / "cache")
    cache = cache_module.ContentCache()
    await cache.put(b"image", "variant", {"description": "old"})
    stored = cache_module.time.time()
    monkeypatch.setattr(cache_module.time, "time", lambda: stored + 120)

    assert await cache.get(b"image", "variant", ttl_seconds=60) is None
    assert await cache.get(b"image", "variant", ttl_seconds=600) == {"description": "old"}


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_a_run_gives_its_region_cache_to_the_stages_and_the_handlers(
    monkeypatch, tmp_path, enabled
) -> None:
    """Through ``execute``: each vision stage gets the run's cache (or ``None``
    when its config turns it off), and the inspection handlers get the ports."""
    from backend.core.pipeline import orchestrator as pddl
    from tests.pddl_support import build_element, build_manifest

    class Stop(Exception):
        pass

    async def no_media(*_args, **_kwargs):
        return None, {}

    caches: dict[str, object] = {}

    def recording(name):
        async def stage(*_args, region_cache=..., **_kwargs):
            caches[name] = region_cache

        return stage

    monkeypatch.setattr(pddl, "_inspect_media", no_media)
    for name in ("_classify_formula_regions", "_enrich_picture_descriptions", "_enrich_formula_latex"):
        monkeypatch.setattr(pddl, name, recording(name))
    for name in ("_mark_inline_math", "_enrich_table_structures", "_mark_table_inline_math"):
        monkeypatch.setattr(pddl, name, recording(name))
    manifest = build_manifest([build_element("p-1", "paragraph", text="Text.")], [])
    received = []

    async def run_plan(*_args, executor, **_kwargs):
        received.append(executor)
        raise Stop

    orchestrator = build_orchestrator()
    orchestrator.information_structural = SimpleNamespace(process=lambda *a, **k: manifest)
    monkeypatch.setattr(orchestrator, "_run_plan", run_plan)
    cache = NoRegionCache()
    ports = RunPorts(region_cache=cache)

    with pytest.raises(Stop):
        await orchestrator.execute(
            tmp_path / "doc.pdf", tmp_path,
            config=core_config(vision={"region_cache_enabled": enabled}),
            model_calls=current_model_calls(), ports=ports,
        )

    expected = cache if enabled else None
    assert caches == {
        "_classify_formula_regions": expected,
        "_enrich_picture_descriptions": expected,
        "_enrich_formula_latex": expected,
        # The steps without a vision agent take no cache.
        "_mark_inline_math": ...,
        "_enrich_table_structures": ...,
        "_mark_table_inline_math": ...,
    }
    [executor] = received
    for method in ("pymupdf-region", "vision-page-inspection"):
        assert executor.registry.get(method).keywords["ports"] is ports


def test_bind_run_gives_the_ports_only_to_the_handlers_that_take_them() -> None:
    from backend.core.execution.executor import MethodRegistry
    from backend.core.pipeline.handlers.registry import bind_run

    def with_ports(manifest, obligation_id, *, ports):
        return ports

    def with_both(manifest, obligation_id, *, config, ports):
        return config, ports

    def plain(manifest, obligation_id):
        return None

    registry = MethodRegistry()
    for name, handler in (("ports", with_ports), ("both", with_both), ("plain", plain)):
        registry.register(name, handler)
    config, ports = core_config(), RunPorts.none()

    bound = bind_run(registry, config, ports)

    assert bound.get("ports")(None, "o") is ports
    assert bound.get("both")(None, "o") == (config, ports)
    assert bound.get("plain") is plain
