"""A run reaches the service's state through its ``RunPorts`` (ADR-0016, step 4)."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from acessilia_core.agents.model_calls import current_model_calls
from acessilia_core.config import CoreConfig
from acessilia_core.ports import NoRegionCache, RunPorts, region_cache_for
from tests.core_config_support import core_config, vision_config
from tests.pddl_support import build_orchestrator

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "libs" / "core" / "src" / "acessilia_core"

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


def test_the_core_imports_nothing_from_the_service() -> None:
    """Inside functions included: the caches, ``run_blocking``, the job
    checkpoints and the registry of remote operations reach a run as
    ports, so ``libs/core/src/acessilia_core`` imports nothing from ``backend.services``."""
    found = {
        path.relative_to(ROOT).as_posix(): imports
        for path in sorted(CORE.rglob("*.py"))
        if (imports := _service_imports(path))
    }

    assert found == {}


def test_ports_outside_the_service_keep_no_state() -> None:
    ports = RunPorts.none()

    assert isinstance(ports.region_cache, NoRegionCache)
    assert ports.checkpoints is None


class MemoryCheckpoints:
    """A ``JobCheckpoints`` that is not the service's: the core needs no more."""

    def __init__(self, job_id: str = "memory-job") -> None:
        self.job_id = job_id
        self.phases: dict[str, dict] = {}
        self.saved: list[str] = []

    def load(self, phase):
        return self.phases.get(phase)

    def save(self, phase, payload):
        self.saved.append(phase)
        self.phases[phase] = payload

    def remove(self, phase):
        self.phases.pop(phase, None)


def _stopped_before_execution(monkeypatch, counts):
    """An orchestrator whose stages are stubs and whose plan run stops the job."""
    from acessilia_core.pipeline import orchestrator as pddl
    from acessilia_core.pipeline.handlers import (
        formula_recognition as formula_method,
        pictures as picture_method,
    )
    from tests.pddl_support import build_element, build_manifest

    class Stop(Exception):
        pass

    async def inspect(*_args, **_kwargs):
        counts["inspect"] += 1
        return None, {}

    async def enrich(*_args, **_kwargs):
        return None

    async def run_plan(*_args, **_kwargs):
        raise Stop

    def extract(*_args, **_kwargs):
        counts["extract"] += 1
        return build_manifest([build_element("p-1", "paragraph", text="Text.")], [])

    monkeypatch.setattr(pddl, "_inspect_media", inspect)
    for name in ("_classify_formula_regions", "_mark_inline_math"):
        monkeypatch.setattr(pddl, name, enrich)
    monkeypatch.setattr(formula_method, "_enrich_formula_latex", enrich)
    monkeypatch.setattr(picture_method, "_enrich_picture_descriptions", enrich)
    orchestrator = build_orchestrator()
    orchestrator.information_structural = SimpleNamespace(process=extract)
    monkeypatch.setattr(orchestrator, "_run_plan", run_plan)
    return orchestrator, Stop


@pytest.mark.asyncio
async def test_a_run_checkpoints_and_resumes_through_its_port(monkeypatch, tmp_path) -> None:
    """Any ``JobCheckpoints`` works: the phases go to the run's port, in
    order, and a second run of the same job resumes from them."""
    from acessilia_core.ports import CHECKPOINT_PHASES

    counts = {"inspect": 0, "extract": 0}
    orchestrator, Stop = _stopped_before_execution(monkeypatch, counts)
    checkpoints = MemoryCheckpoints()
    ports = RunPorts(region_cache=NoRegionCache(), checkpoints=checkpoints, operations=None)

    for _ in range(2):
        with pytest.raises(Stop):
            await orchestrator.execute(
                tmp_path / "doc.pdf", tmp_path, config=core_config(),
                model_calls=current_model_calls(), ports=ports,
            )

    assert counts == {"inspect": 1, "extract": 1}
    assert set(checkpoints.phases) == {"media", "manifest", "enriched", "plan"}
    first_writes = [phase for phase in dict.fromkeys(checkpoints.saved)]
    assert first_writes == [p for p in CHECKPOINT_PHASES if p in checkpoints.phases]


@pytest.mark.asyncio
async def test_a_run_without_a_job_neither_reads_nor_writes_checkpoints(
    monkeypatch, tmp_path
) -> None:
    """Not even the manifest is serialized for a checkpoint (review of #565)."""
    from acessilia_core.pipeline import orchestrator as pddl

    counts = {"inspect": 0, "extract": 0}
    orchestrator, Stop = _stopped_before_execution(monkeypatch, counts)
    serialized = []
    from acessilia_core.pipeline import checkpointing

    monkeypatch.setattr(checkpointing, "manifest_payload", lambda manifest: serialized.append(manifest))
    monkeypatch.setattr(pddl, "manifest_payload", lambda manifest: serialized.append(manifest))

    for _ in range(2):
        with pytest.raises(Stop):
            await orchestrator.execute(
                tmp_path / "doc.pdf", tmp_path, config=core_config(),
                model_calls=current_model_calls(), ports=RunPorts.none(),
            )

    assert counts == {"inspect": 2, "extract": 2}
    assert serialized == []


@pytest.mark.asyncio
async def test_a_checkpoint_that_cannot_be_written_does_not_fail_the_run(
    monkeypatch, tmp_path
) -> None:
    from loguru import logger

    class Full(MemoryCheckpoints):
        def save(self, phase, payload):
            raise OSError("disk full")

    counts = {"inspect": 0, "extract": 0}
    orchestrator, Stop = _stopped_before_execution(monkeypatch, counts)
    messages: list[str] = []
    sink = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    try:
        with pytest.raises(Stop):
            await orchestrator.execute(
                tmp_path / "doc.pdf", tmp_path, config=core_config(),
                model_calls=current_model_calls(),
                ports=RunPorts(region_cache=NoRegionCache(), checkpoints=Full("full-job"), operations=None),
            )
    finally:
        logger.remove(sink)

    assert any("full-job" in m and "disk full" in m for m in messages)


def test_the_service_checkpoints_are_bound_to_the_job(monkeypatch, tmp_path) -> None:
    from backend.config.settings import settings
    from backend.services import job_checkpoint
    from backend.services.run_ports import service_run_ports

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    checkpoints = service_run_ports("job-7").checkpoints

    checkpoints.save("plan", {"plan": 1})

    assert isinstance(checkpoints, job_checkpoint.FileJobCheckpoints)
    assert checkpoints.job_id == "job-7"
    assert checkpoints.load("plan") == {"plan": 1}
    assert job_checkpoint.load("job-7", "plan") == {"plan": 1}
    assert job_checkpoint.load("job-8", "plan") is None
    checkpoints.remove("plan")
    assert checkpoints.load("plan") is None
    assert service_run_ports().checkpoints is None


def test_an_untrusted_service_checkpoint_is_not_resumed(monkeypatch, tmp_path) -> None:
    from backend.config.settings import settings
    from backend.services import job_checkpoint

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    checkpoints = job_checkpoint.FileJobCheckpoints("job-9")
    checkpoints.save("manifest", {"manifest": {}})
    path = tmp_path / "jobs" / "job-9" / "checkpoints" / "manifest.json"
    path.write_text(path.read_text().replace('"manifest":{}', '"manifest":{"x":1}'))

    with pytest.raises(job_checkpoint.CheckpointError):
        checkpoints.load("manifest")


@pytest.mark.asyncio
async def test_the_no_op_region_cache_never_answers() -> None:
    cache = NoRegionCache()

    await cache.put(b"image", "variant", {"description": "stored"})

    assert await cache.get(b"image", "variant", ttl_seconds=60) is None


@pytest.mark.parametrize("enabled", [True, False])
def test_the_run_config_turns_the_region_cache_on_or_off(enabled) -> None:
    cache = NoRegionCache()
    ports = RunPorts(region_cache=cache, checkpoints=None, operations=None)

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
    from acessilia_core.pipeline import orchestrator as pddl
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
    for name in ("_classify_formula_regions",):
        monkeypatch.setattr(pddl, name, recording(name))
    monkeypatch.setattr(pddl, "_mark_inline_math", recording("_mark_inline_math"))
    manifest = build_manifest([build_element("p-1", "paragraph", text="Text.")], [])
    received = []

    async def run_plan(*_args, executor, **_kwargs):
        received.append(executor)
        raise Stop

    orchestrator = build_orchestrator()
    orchestrator.information_structural = SimpleNamespace(process=lambda *a, **k: manifest)
    monkeypatch.setattr(orchestrator, "_run_plan", run_plan)
    cache = NoRegionCache()
    ports = RunPorts(region_cache=cache, checkpoints=None, operations=None)

    with pytest.raises(Stop):
        await orchestrator.execute(
            tmp_path / "doc.pdf", tmp_path,
            config=core_config(vision={"region_cache_enabled": enabled}),
            model_calls=current_model_calls(), ports=ports,
        )

    expected = cache if enabled else None
    assert caches == {
        "_classify_formula_regions": expected,
        # The steps without a vision agent take no cache.
        "_mark_inline_math": ...,
    }
    [executor] = received
    # The picture descriptions run inside the plan (#640, M1): their method
    # takes the region cache from the ports, like the inspection handlers.
    for method in ("pymupdf-region", "vision-page-inspection", "picture-description", "formula-recognizer"):
        assert executor.registry.get(method).keywords["ports"] is ports


def test_bind_run_gives_the_ports_only_to_the_handlers_that_take_them() -> None:
    from acessilia_core.execution.executor import MethodRegistry
    from acessilia_core.pipeline.handlers.registry import bind_run

    def with_ports(manifest, obligation_id, *, ports: RunPorts):
        return ports

    def with_both(manifest, obligation_id, *, config: CoreConfig, ports: RunPorts):
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


@pytest.mark.asyncio
async def test_the_enrichment_steps_are_checkpointed_one_by_one(monkeypatch, tmp_path) -> None:
    """After each of the three enrichment steps before planning the manifest
    checkpoint is written again (#407), so a restart repeats at most the step
    that ran. The picture descriptions (#640, M1), the formula LaTeX (M3) and
    the table steps (M2) run inside the plan, where the execution checkpoint
    covers them."""
    counts = {"inspect": 0, "extract": 0}
    orchestrator, Stop = _stopped_before_execution(monkeypatch, counts)
    checkpoints = MemoryCheckpoints()

    with pytest.raises(Stop):
        await orchestrator.execute(
            tmp_path / "doc.pdf", tmp_path, config=core_config(),
            model_calls=current_model_calls(),
            ports=RunPorts(region_cache=NoRegionCache(), checkpoints=checkpoints, operations=None),
        )

    # One after the extraction, then one after each enrichment step.
    assert checkpoints.saved.count("manifest") == 1 + 3


@pytest.mark.asyncio
async def test_a_replan_drops_the_execution_checkpoint_of_the_old_plan(monkeypatch) -> None:
    import asyncio

    from tests.pddl_support import build_element, build_manifest, build_obligation

    orchestrator = build_orchestrator(max_replans=1)
    obligation = build_obligation("describe-image", ["p-1"], ["human-review"])
    obligation.selected = True
    manifest = build_manifest([build_element("p-1", "paragraph", text="Text.")], [obligation])
    checkpoints = MemoryCheckpoints()
    checkpoints.phases["execution"] = {"plan_id": "first-plan", "results": []}
    seen = []

    async def run_plan(*_args, **_kwargs):
        seen.append(dict(checkpoints.phases))
        return manifest, SimpleNamespace(replan_required=False, status="completed", steps=[])

    async def no_save(*_args, **_kwargs):
        return None

    monkeypatch.setattr(orchestrator, "_run_plan", run_plan)
    monkeypatch.setattr(orchestrator, "_build_plan", lambda *a, **k: ("plan", None))
    from acessilia_core.pipeline.checkpointing import RunCheckpoints

    monkeypatch.setattr(RunCheckpoints, "save_plan", no_save)

    await orchestrator._replan_until_done(
        manifest,
        SimpleNamespace(replan_required=True, status="replan-required", steps=[SimpleNamespace(status="failed")]),
        "first-plan",
        None,
        [],
        None,
        asyncio.get_running_loop(),
        checkpoints=RunCheckpoints(checkpoints, core_config()),
        planning_manifest=manifest,
        availability=None,
        replans=0,
        executor=orchestrator._run_executor(core_config(), RunPorts.none()),
    )

    assert seen == [{}], "the new plan starts without the old plan's progress"


class MemoryOperations:
    """A ``RemoteOperations`` that is not the service's registry."""

    def __init__(self, job_id: str = "memory-job", refuse: set[str] | None = None) -> None:
        self.job_id = job_id
        self.refuse = refuse or set()
        self.events: list[tuple[str, str]] = []

    def begin(self, kind):
        if kind in self.refuse:
            raise RuntimeError(f"job cancelled before {kind}")
        operation_id = f"{kind}-id"
        self.events.append(("begin", operation_id))
        return operation_id

    def finish(self, operation_id):
        self.events.append(("finish", operation_id))


def _extractor(seen, *, fail_primary=False):
    from unittest.mock import AsyncMock

    from acessilia_core.manifest.toolbox_extractor import ToolboxManifestExtractor
    from acessilia_sdk.toolbox.clients import (
        ToolboxArtifactClient,
        ToolboxStructureClient,
    )
    from acessilia_sdk.toolbox.operation import current_operation
    from tests.test_toolbox_manifest_extractor import SAMPLE_TOOLBOX_RESPONSE

    def labelled(kind, answer):
        async def call(*_args, **_kwargs):
            context = current_operation()
            seen.append((kind, context and (context.task_id, context.operation_id)))
            if kind == "primary" and fail_primary:
                raise RuntimeError("primary failed")
            return answer

        return call

    structure = AsyncMock(spec=ToolboxStructureClient)
    structure.base_url, structure.provider = "http://toolbox.test", "docling"
    structure.extract_structure = AsyncMock(side_effect=labelled("primary", SAMPLE_TOOLBOX_RESPONSE))
    artifacts = AsyncMock(spec=ToolboxArtifactClient)
    artifacts.upload = AsyncMock(side_effect=labelled("upload", "sha256:abc"))
    return ToolboxManifestExtractor(client=structure, artifact_client=artifacts)


def _extract(extractor, operations):
    from tests.core_config_support import fusion_config, paths_config, toolbox_config
    from tests.test_toolbox_manifest_extractor import FIXTURE_PDF

    return extractor.extract(
        FIXTURE_PDF, fusion=fusion_config(), toolbox=toolbox_config(use_artifact_store=True),
        paths=paths_config(), operations=operations,
    )


def test_the_extractor_registers_and_labels_each_call_through_its_port() -> None:
    """Any ``RemoteOperations`` works: each call is registered, labelled with
    the job and its operation id, and finished."""
    seen: list = []
    operations = MemoryOperations("job-ops")

    _extract(_extractor(seen), operations)

    assert seen == [("upload", ("job-ops", "upload-id")), ("primary", ("job-ops", "primary-id"))]
    assert operations.events == [
        ("begin", "upload-id"), ("finish", "upload-id"),
        ("begin", "primary-id"), ("finish", "primary-id"),
    ]


def test_an_extraction_outside_a_job_is_neither_registered_nor_labelled() -> None:
    seen: list = []

    _extract(_extractor(seen), None)

    assert seen == [("upload", None), ("primary", None)]


def test_a_failed_call_is_still_finished() -> None:
    seen: list = []
    operations = MemoryOperations()

    with pytest.raises(RuntimeError, match="primary failed"):
        _extract(_extractor(seen, fail_primary=True), operations)

    assert operations.events[-1] == ("finish", "primary-id")


def test_a_refused_operation_never_reaches_the_toolbox() -> None:
    """A job being cancelled refuses the next call before it starts."""
    seen: list = []
    operations = MemoryOperations(refuse={"primary"})

    with pytest.raises(RuntimeError, match="cancelled before primary"):
        _extract(_extractor(seen), operations)

    assert [kind for kind, _ in seen] == ["upload"]


@pytest.mark.asyncio
async def test_a_run_gives_its_operations_to_the_extraction(monkeypatch, tmp_path) -> None:
    counts = {"inspect": 0, "extract": 0}
    orchestrator, Stop = _stopped_before_execution(monkeypatch, counts)
    received = []
    process = orchestrator.information_structural.process

    def recording(*args, operations, **kwargs):
        received.append(operations)
        return process(*args, **kwargs)

    orchestrator.information_structural = SimpleNamespace(process=recording)
    operations = MemoryOperations()

    with pytest.raises(Stop):
        await orchestrator.execute(
            tmp_path / "doc.pdf", tmp_path, config=core_config(),
            model_calls=current_model_calls(),
            ports=RunPorts(region_cache=NoRegionCache(), checkpoints=None, operations=operations),
        )

    assert received == [operations] and received[0] is operations


def test_the_service_operations_are_bound_to_the_job() -> None:
    from backend.services.operation_registry import JobOperations, OperationRegistry
    from backend.services.run_ports import service_run_ports

    registry = OperationRegistry()
    operations = JobOperations("job-ops", registry)

    operation_id = operations.begin("primary")

    assert [op.operation_id for op in registry.active("job-ops")] == [operation_id]
    assert registry.active("other-job") == []
    operations.finish(operation_id)
    assert registry.active("job-ops") == []
    registry.clear("job-ops")
    assert service_run_ports("job-ops").operations.job_id == "job-ops"
    assert service_run_ports().operations is None


def test_the_service_operations_refuse_a_cancelled_job() -> None:
    from backend.services.operation_registry import (
        JobOperations,
        OperationRegistry,
        RemoteOperationCancelled,
    )

    registry = OperationRegistry()
    registry.cancel_task("job-cancelled")

    with pytest.raises(RemoteOperationCancelled):
        JobOperations("job-cancelled", registry).begin("upload")
    registry.clear("job-cancelled")
