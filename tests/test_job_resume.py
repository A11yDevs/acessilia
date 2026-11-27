"""Resuming an interrupted job from its durable checkpoints (#407)."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from acessilia_core.agents.model_calls import current_model_calls
from acessilia_core.execution.executor import (
    ExecutionResume,
    ExecutorAgent,
    MethodRegistry,
)
from acessilia_core.execution.models import ExecutionStepResult, MethodResult
from acessilia_core.manifest.models import ProcessingManifest
from acessilia_core.pipeline import orchestrator as pddl
from acessilia_core.pipeline.handlers import (
    formula_recognition as formula_method,
    formula_regions as regions_method,
    pictures as picture_method,
)
from acessilia_core.planning.domain_bundle import DomainBundle
from acessilia_core.planning.planner_agent import PlannerAgent
from acessilia_core.ports import (
    PHASE_ENRICHED,
    PHASE_EXECUTION,
    PHASE_MANIFEST,
    PHASE_MEDIA,
    PHASE_PLAN,
    RunPorts,
)
from backend.config.settings import settings
from backend.services import job_checkpoint
from backend.services.operation_registry import OperationRegistry
from backend.services.run_ports import service_run_ports
from tests.core_config_support import (
    core_config,
    model_config,
    toolbox_config,
    vision_config,
)
from tests.pddl_support import build_element, build_manifest, build_orchestrator


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    directory = tmp_path / "data"
    monkeypatch.setattr(settings, "data_dir", directory)
    return directory


def _sample_manifest(obligations: int = 1) -> ProcessingManifest:
    from tests.pddl_support import build_obligation

    # Enough prose that the document is not mostly visual, so its heading is
    # not one the picture descriptions would describe (#640, M1).
    elements = [
        build_element("h", "heading", text="Titulo"),
        build_element(
            "p", "paragraph",
            text="A paragraph with enough words to make the document read as text, not as a picture.",
        ),
    ]
    built = []
    for index in range(obligations):
        obligation = build_obligation("describe-image", ["h"], ["human-review"])
        obligation.id = f"o-{index + 1}"
        built.append(obligation)
    return build_manifest(elements, built)


# --- checkpoints -----------------------------------------------------------


def test_a_checkpoint_round_trips_and_reports_itself_as_resumable(data_dir):
    job_checkpoint.save("task-1", PHASE_MANIFEST, {"manifest": {"a": 1}})

    assert job_checkpoint.load("task-1", PHASE_MANIFEST) == {
        "manifest": {"a": 1}
    }
    assert job_checkpoint.load("task-1", PHASE_ENRICHED) is None
    assert job_checkpoint.resumable("task-1") is True

    job_checkpoint.clear("task-1")
    assert job_checkpoint.resumable("task-1") is False


def test_a_checkpoint_from_another_version_is_never_used(data_dir):
    job_checkpoint.save("task-1", PHASE_MANIFEST, {"manifest": {}})
    path = data_dir / "jobs" / "task-1" / "checkpoints" / "manifest.json"
    document = path.read_text(encoding="utf-8").replace(
        '"version":1', '"version":999', 1
    )
    path.write_text(document, encoding="utf-8")

    with pytest.raises(job_checkpoint.CheckpointError):
        job_checkpoint.load("task-1", PHASE_MANIFEST)
    assert job_checkpoint.resumable("task-1") is False


def test_a_corrupt_checkpoint_is_never_used(data_dir):
    job_checkpoint.save("task-1", PHASE_MANIFEST, {"manifest": {}})
    path = data_dir / "jobs" / "task-1" / "checkpoints" / "manifest.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(job_checkpoint.CheckpointError):
        job_checkpoint.load("task-1", PHASE_MANIFEST)
    assert job_checkpoint.resumable("task-1") is False


def test_expired_checkpoints_are_swept(data_dir):
    job_checkpoint.save("task-1", PHASE_MANIFEST, {"manifest": {}})

    assert job_checkpoint.expire(7 * 24 * 60 * 60) == 0
    assert job_checkpoint.expire(0) == 1
    assert job_checkpoint.resumable("task-1") is False


# --- operation journal -----------------------------------------------------


def test_a_restarted_registry_reuses_the_operation_id(data_dir):
    first = OperationRegistry().begin("task-1", "primary")
    # A new process: the in-memory registry is empty, the journal is not.
    restarted = OperationRegistry()
    second = restarted.begin("task-1", "primary")

    assert second.operation_id == first.operation_id
    assert OperationRegistry().begin("task-2", "primary").operation_id != first.operation_id

    restarted.clear("task-1")
    assert OperationRegistry().begin("task-1", "primary").operation_id != first.operation_id


def test_finishing_an_operation_keeps_its_id_but_updates_the_state(data_dir):
    registry = OperationRegistry()
    operation = registry.begin("task-1", "upload")
    registry.finish("task-1", operation.operation_id)

    assert registry.active("task-1") == []
    assert OperationRegistry().begin("task-1", "upload").operation_id == operation.operation_id


# --- executor --------------------------------------------------------------


def test_a_resumed_execution_does_not_repeat_completed_steps():
    manifest = _sample_manifest(obligations=2)
    _, plan = PlannerAgent().plan(manifest, selected_roots=["o-1", "o-2"])
    calls: list[str] = []

    def handler(_manifest, obligation_id: str) -> MethodResult:
        calls.append(obligation_id)
        return MethodResult(success=True, validated=True)

    registry = MethodRegistry()
    registry.register("human-review", handler)
    executor = ExecutorAgent(registry, domain=DomainBundle.load())

    class Crash(BaseException):
        """A process death: Agno must not turn it into a failed step."""

    snapshots: list[dict] = []

    def save(snapshot: dict) -> None:
        snapshots.append(snapshot)
        # start-job + the first obligation were recorded.
        if len(snapshot["results"]) == 2:
            raise Crash()

    with pytest.raises(Crash):
        executor.execute(plan, manifest, on_step=save)

    assert len(calls) == 1
    last = snapshots[-1]
    resume = ExecutionResume(
        manifest=ProcessingManifest.model_validate(last["manifest"]),
        results=[ExecutionStepResult.model_validate(item) for item in last["results"]],
        replan_required=last["replan_required"],
    )

    updated, report = executor.execute(plan, manifest, resume=resume)

    assert len(calls) == 2
    assert len(set(calls)) == 2
    assert report.status == "completed"
    assert updated.status == "completed"
    assert [step.index for step in report.steps] == list(range(len(plan.steps)))


# --- orchestrator ----------------------------------------------------------


@pytest.mark.asyncio
async def test_the_pipeline_skips_phases_recorded_before_the_restart(
    monkeypatch, tmp_path, data_dir
):
    manifest = _sample_manifest()
    counts = {"inspect": 0, "extract": 0, "enrich": 0}
    crash = {"armed": True}

    async def inspect(path, _toolbox):
        counts["inspect"] += 1
        return None, {}

    def extract(*_args, **_kwargs):
        counts["extract"] += 1
        return manifest

    async def enrich(*_args, **_kwargs):
        return None

    def prepare(*_args, **_kwargs):
        # The one step left before planning (#640, M1–M4b).
        counts["enrich"] += 1
        if crash["armed"]:
            raise RuntimeError("the process died during enrichment")

    monkeypatch.setattr(pddl, "_inspect_media", inspect)
    monkeypatch.setattr(pddl, "_prepare_pictures", prepare)
    monkeypatch.setattr(regions_method, "_classify_formula_regions", enrich)
    monkeypatch.setattr(formula_method, "_enrich_formula_latex", enrich)
    monkeypatch.setattr(picture_method, "_enrich_picture_descriptions", enrich)

    orchestrator = build_orchestrator()
    orchestrator.executor.registry.register(
        "human-review", lambda _manifest, _obligation: MethodResult(success=True, validated=True)
    )
    orchestrator.information_structural = SimpleNamespace(process=extract)

    with pytest.raises(RuntimeError, match="died during enrichment"):
        await orchestrator.execute(tmp_path / "doc.pdf", tmp_path, structured_output=True, config=core_config(), model_calls=current_model_calls(), ports=service_run_ports("resume-task"))

    assert job_checkpoint.load("resume-task", PHASE_MEDIA) is not None
    assert job_checkpoint.load("resume-task", PHASE_MANIFEST) is not None
    assert job_checkpoint.load("resume-task", PHASE_ENRICHED) is None

    crash["armed"] = False
    result = await orchestrator.execute(
        tmp_path / "doc.pdf", tmp_path, structured_output=True,
        config=core_config(), model_calls=current_model_calls(), ports=service_run_ports("resume-task")
    )

    # Every enrichment step but the pictures' preparation runs inside the
    # plan (#640, M1–M4b), and the pass after execution of #599 is gone: the
    # crashed run stopped at the preparation, and the resume ran it again.
    assert counts == {"inspect": 1, "extract": 1, "enrich": 2}
    assert result["text"]
    assert job_checkpoint.load("resume-task", PHASE_PLAN) is not None


@pytest.mark.asyncio
async def test_outside_a_job_the_pipeline_writes_no_checkpoint(monkeypatch, tmp_path, data_dir):
    manifest = _sample_manifest()
    counts = {"inspect": 0}

    async def inspect(_path, _toolbox):
        counts["inspect"] += 1
        return None, {}

    async def enrich(*_args, **_kwargs):
        return None

    monkeypatch.setattr(pddl, "_inspect_media", inspect)
    monkeypatch.setattr(regions_method, "_classify_formula_regions", enrich)
    monkeypatch.setattr(formula_method, "_enrich_formula_latex", enrich)
    monkeypatch.setattr(picture_method, "_enrich_picture_descriptions", enrich)

    orchestrator = build_orchestrator()
    orchestrator.executor.registry.register(
        "human-review", lambda _manifest, _obligation: MethodResult(success=True, validated=True)
    )
    orchestrator.information_structural = SimpleNamespace(process=lambda *_a, **_k: manifest)

    await orchestrator.execute(tmp_path / "doc.pdf", tmp_path, structured_output=True, config=core_config(), model_calls=current_model_calls(), ports=RunPorts.none())

    assert counts == {"inspect": 1}
    assert not (data_dir / "jobs").exists()


# --- worker recovery -------------------------------------------------------


@pytest.fixture
def isolated_worker(tmp_path, monkeypatch):
    from backend.agents.state_manager import state_manager
    from backend.api import worker
    from backend.api.routes import jobs
    from backend.services import queue_service
    from backend.services.queue_service import UnifiedQueue

    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "temp_dir", tmp_path / "temp")
    queue = UnifiedQueue()
    monkeypatch.setattr(queue_service, "unified_queue", queue)
    monkeypatch.setattr(jobs, "unified_queue", queue)
    monkeypatch.setattr(worker, "queued_jobs", {})
    state_manager._tasks.clear()
    state_manager._cancel_events.clear()
    return queue


def _save_processing_job(task_id: str, path: Path) -> None:
    from dataclasses import asdict

    from backend.api.worker import ApiJob
    from backend.services.job_store import save_request

    payload = asdict(ApiJob(task_id, path, "doc.pdf"))
    payload["file_path"] = str(path)
    save_request(
        task_id,
        "token",
        payload,
        {
            "task_id": task_id,
            "status": "processing",
            "etapa_atual": "Executing the plan: step 3 of 9...",
            "progresso": 0.5,
        },
    )


@pytest.mark.asyncio
async def test_recovery_requeues_a_processing_job_that_has_a_checkpoint(isolated_worker, tmp_path):
    from backend.api.worker import recover_pending_jobs
    from backend.services.job_store import load_record

    path = tmp_path / "doc.pdf"
    path.write_bytes(b"%PDF")
    _save_processing_job("resume-task", path)
    job_checkpoint.save(
        "resume-task",
        PHASE_EXECUTION,
        {"plan_id": "plan-1", "manifest": {}, "results": []},
    )

    await recover_pending_jobs()

    assert load_record("resume-task")["status"]["status"] == "processing"
    assert isolated_worker.get_position("resume-task") == 1

    # A second recovery in the same process must not enqueue it twice, and it
    # must leave the already queued job's status and checkpoints alone.
    await recover_pending_jobs()
    assert isolated_worker.qsize() == 1
    assert load_record("resume-task")["status"]["status"] == "processing"
    assert job_checkpoint.resumable("resume-task") is True


@pytest.mark.asyncio
async def test_a_recovered_job_can_be_cancelled_while_it_waits(
    isolated_worker, tmp_path, data_dir
):
    from backend.api import worker
    from backend.api.worker import cancel_job_status, recover_pending_jobs
    from backend.services.job_store import load_record, save_status

    path = tmp_path / "doc.pdf"
    path.write_bytes(b"%PDF")
    _save_processing_job("resume-cancel", path)
    job_checkpoint.save(
        "resume-cancel", PHASE_MEDIA, {"inspection": None, "configuration": {}}
    )

    await recover_pending_jobs()
    assert isolated_worker.get_position("resume-cancel") == 1

    assert cancel_job_status("resume-cancel") is True
    assert isolated_worker.qsize() == 0
    status = worker.get_job_status("resume-cancel")
    assert status["status"] == "cancelled"
    assert status["progresso"] == 0.5  # the restored progress is kept
    # The endpoint persists the in-memory status after the cancellation.
    save_status("resume-cancel", status)
    assert load_record("resume-cancel")["status"]["status"] == "cancelled"
    assert job_checkpoint.resumable("resume-cancel") is False
    assert not path.exists()


@pytest.mark.asyncio
async def test_recovery_still_fails_a_job_whose_checkpoint_is_unusable(
    isolated_worker, tmp_path, data_dir
):
    from backend.api.worker import recover_pending_jobs
    from backend.services.job_store import load_record

    path = tmp_path / "doc.pdf"
    path.write_bytes(b"%PDF")
    _save_processing_job("broken-checkpoint", path)
    job_checkpoint.save(
        "broken-checkpoint", PHASE_MANIFEST, {"manifest": {}}
    )
    checkpoint = (
        data_dir / "jobs" / "broken-checkpoint" / "checkpoints" / "manifest.json"
    )
    checkpoint.write_text("{truncated", encoding="utf-8")

    await recover_pending_jobs()

    assert load_record("broken-checkpoint")["status"]["status"] == "error"
    assert isolated_worker.qsize() == 0


@pytest.mark.asyncio
async def test_a_resumed_run_restores_progress_and_skips_the_confirmation(
    isolated_worker, monkeypatch, tmp_path
):
    from dataclasses import asdict
    from unittest.mock import AsyncMock

    from backend.agents.state_manager import state_manager
    from backend.api import worker
    from backend.api.worker import ApiJob, JobExecutor

    path = tmp_path / "doc.pdf"
    path.write_bytes(b"%PDF")
    stage = "Executing the plan: step 3 of 9..."
    payload = asdict(ApiJob("resume-run", path, "doc.pdf", email="reader@example.test"))
    payload["file_path"] = str(path)
    from backend.services.job_store import save_request

    save_request(
        "resume-run",
        "token",
        payload,
        {
            "task_id": "resume-run",
            "status": "processing",
            "etapa_atual": stage,
            "progresso": 0.42,
            "inicio": 1000.0,
        },
    )
    job_checkpoint.save("resume-run", PHASE_MANIFEST, {"manifest": {}})

    seen: list[str] = []

    async def fake_process(*_args, **kwargs):
        assert kwargs["resumed"] is True
        task = state_manager.obter("resume-run")
        seen.append(task["etapa_atual"])
        assert task["progresso"] == 0.42
        raise RuntimeError("the resumed pipeline failed")

    confirmation = AsyncMock()
    monkeypatch.setattr(worker, "send_confirmation_email", confirmation)
    monkeypatch.setattr(worker, "send_failure_email", AsyncMock(return_value=False))
    monkeypatch.setattr(worker, "registrar_conversao", AsyncMock())
    monkeypatch.setattr(worker, "finalizar_conversao", AsyncMock())
    monkeypatch.setattr("backend.service.process", fake_process)

    job = ApiJob(
        task_id="resume-run",
        file_path=path,
        filename="doc.pdf",
        email="reader@example.test",
    )
    await JobExecutor().run(job)

    assert seen == [stage]
    confirmation.assert_not_awaited()
    # The resumed attempt replaced the record and says so (#380).
    from backend.services.job_store import load_record

    configuration = load_record("resume-run")["configuration"]
    assert configuration["attempt"]["resumed"] is True
    # The job is terminal now: its checkpoints must not be reused.
    assert job_checkpoint.resumable("resume-run") is False


@pytest.mark.asyncio
async def test_resumption_can_be_disabled_without_a_code_revert(
    isolated_worker, monkeypatch, tmp_path
):
    from backend.api.worker import recover_pending_jobs
    from backend.services.job_store import load_record

    path = tmp_path / "doc.pdf"
    path.write_bytes(b"%PDF")
    _save_processing_job("no-resume", path)
    job_checkpoint.save("no-resume", PHASE_MANIFEST, {"manifest": {}})
    monkeypatch.setattr(settings, "job_resume_on_restart", False)

    await recover_pending_jobs()

    assert load_record("no-resume")["status"]["status"] == "error"
    assert isolated_worker.qsize() == 0


def test_a_cancel_cannot_slip_between_the_check_and_the_registration(
    data_dir, monkeypatch
):
    """``begin`` checks and inserts in one critical section."""
    from types import SimpleNamespace

    from backend.services import operation_registry as registry_module
    from backend.services.operation_registry import RemoteOperationCancelled

    registry = OperationRegistry()
    started, release = threading.Event(), threading.Event()
    real_uuid4 = registry_module.uuid.uuid4

    def slow_uuid4():
        started.set()
        assert release.wait(3)
        return real_uuid4()

    monkeypatch.setattr(registry_module, "uuid", SimpleNamespace(uuid4=slow_uuid4))
    outcome: list[object] = []

    def worker() -> None:
        try:
            outcome.append(registry.begin("task-race", "primary"))
        except RemoteOperationCancelled as exc:
            outcome.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    try:
        assert started.wait(3)
        # The id is being generated, so ``begin`` has not entered the critical
        # section yet: the cancel must still be visible when it does.
        registry.cancel_task("task-race")
    finally:
        release.set()
        thread.join(5)

    assert len(outcome) == 1 and isinstance(outcome[0], RemoteOperationCancelled)
    assert registry.active("task-race") == []


@pytest.mark.asyncio
async def test_an_interrupted_plan_continues_from_the_next_step(
    monkeypatch, tmp_path, data_dir
):
    """A crash between plan steps resumes the plan without repeating a handler."""
    manifest = _sample_manifest(obligations=2)
    handler_calls: list[str] = []

    def handler(_manifest, obligation_id: str) -> MethodResult:
        handler_calls.append(obligation_id)
        return MethodResult(success=True, validated=True)

    async def inspect(_path, _toolbox):
        return None, {}

    async def enrich(*_args, **_kwargs):
        return None

    monkeypatch.setattr(pddl, "_inspect_media", inspect)
    monkeypatch.setattr(regions_method, "_classify_formula_regions", enrich)
    monkeypatch.setattr(formula_method, "_enrich_formula_latex", enrich)
    monkeypatch.setattr(picture_method, "_enrich_picture_descriptions", enrich)

    orchestrator = build_orchestrator()
    orchestrator.executor.registry.register("human-review", handler)
    orchestrator.information_structural = SimpleNamespace(
        process=lambda *_a, **_k: manifest
    )

    class Crash(BaseException):
        pass

    real_save = job_checkpoint.save

    def crash_after_the_first_obligation(task_id, phase, payload):
        real_save(task_id, phase, payload)
        if (
            phase == PHASE_EXECUTION
            and len(payload["results"]) == 2
        ):
            raise Crash()

    monkeypatch.setattr(job_checkpoint, "save", crash_after_the_first_obligation)
    with pytest.raises(Crash):
        await orchestrator.execute(
            tmp_path / "doc.pdf", tmp_path, structured_output=True,
            config=core_config(), model_calls=current_model_calls(), ports=service_run_ports("plan-resume")
        )
    assert len(handler_calls) == 1

    monkeypatch.setattr(job_checkpoint, "save", real_save)
    result = await orchestrator.execute(
        tmp_path / "doc.pdf", tmp_path, structured_output=True,
        config=core_config(), model_calls=current_model_calls(), ports=service_run_ports("plan-resume")
    )

    assert len(handler_calls) == 2
    assert len(set(handler_calls)) == 2
    assert result["canonical_metadata"]["pddl_execution_status"] == "completed"


@pytest.mark.asyncio
async def test_a_graceful_shutdown_keeps_the_job_resumable(
    isolated_worker, monkeypatch, tmp_path
):
    """The queue worker stopping on SIGTERM is not a user cancellation."""
    from dataclasses import asdict
    from unittest.mock import AsyncMock

    from backend.api import worker
    from backend.api.worker import ApiJob, JobExecutor
    from backend.services import shutdown
    from backend.services.job_store import load_record, save_request

    path = tmp_path / "doc.pdf"
    path.write_bytes(b"%PDF")
    payload = asdict(ApiJob("shutdown-job", path, "doc.pdf"))
    payload["file_path"] = str(path)
    save_request(
        "shutdown-job",
        "token",
        payload,
        {
            "task_id": "shutdown-job",
            "status": "processing",
            "etapa_atual": "Executing the plan: step 3 of 9...",
        },
    )
    job_checkpoint.save("shutdown-job", PHASE_MANIFEST, {"manifest": {}})

    started = asyncio.Event()

    async def blocked(*_args, **_kwargs):
        started.set()
        await asyncio.Future()

    monkeypatch.setattr(worker, "registrar_conversao", AsyncMock())
    monkeypatch.setattr("backend.service.process", blocked)

    run = asyncio.create_task(
        JobExecutor().run(
            ApiJob(task_id="shutdown-job", file_path=path, filename="doc.pdf")
        )
    )
    try:
        await asyncio.wait_for(started.wait(), 5)
        shutdown.begin_shutdown()
        run.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run
    finally:
        shutdown.reset()

    status = load_record("shutdown-job")["status"]
    assert status["status"] == "processing"
    assert path.exists()
    assert job_checkpoint.resumable("shutdown-job") is True


@pytest.mark.asyncio
async def test_a_graceful_shutdown_keeps_the_operation_journal(
    monkeypatch, tmp_path, data_dir
):
    from backend import service
    from backend.agents.state_manager import state_manager
    from backend.services import shutdown

    path = tmp_path / "doc.pdf"
    path.write_bytes(b"%PDF")
    state_manager._tasks.clear()
    state_manager._cancel_events.clear()
    operation = OperationRegistry().begin("journal-task", "primary")
    started = asyncio.Event()

    async def blocked(*_args, **_kwargs):
        started.set()
        await asyncio.Future()

    monkeypatch.setattr(service.agente, "execute", blocked)
    run = asyncio.create_task(service.process(path, task_id="journal-task", config=core_config()))
    try:
        await asyncio.wait_for(started.wait(), 5)
        shutdown.begin_shutdown()
        run.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run
    finally:
        shutdown.reset()

    assert (
        OperationRegistry().begin("journal-task", "primary").operation_id
        == operation.operation_id
    )
    OperationRegistry().clear("journal-task")
    state_manager._tasks.clear()
    state_manager._cancel_events.clear()


@pytest.mark.asyncio
async def test_a_completed_picture_is_checkpointed_during_the_stage(
    monkeypatch, data_dir
):
    """A picture folded before the stage ends must be durable for a resume."""
    from acessilia_core.agents.output_schemas import VisionOutput
    from acessilia_core.pipeline.enrichment import pictures as picture_stage

    manifest = build_manifest(
        [
            build_element("pic-1", "picture"),
            build_element("pic-2", "picture", reading_order=2),
        ],
        [],
    )
    monkeypatch.setattr(
        picture_stage,
        "_extract_picture_bytes",
        lambda _source, element, *_a, **_k: (element.id.encode(), 1),
    )
    started, release = asyncio.Event(), asyncio.Event()

    class Vision:
        def __init__(self, **_kwargs) -> None:
            pass

        async def describe_region(self, *, image_bytes, **_kwargs):
            if image_bytes == b"pic-2":
                started.set()
                await release.wait()
            return VisionOutput(
                kind="description",
                description="A photo of a building.",
                language="en",
                confidence=0.9,
            )

    monkeypatch.setattr(picture_stage, "VisionAgent", Vision)

    async def save() -> None:
        job_checkpoint.save(
            "pictures",
            PHASE_MANIFEST,
            {"manifest": manifest.model_dump(mode="json", by_alias=True)},
        )

    task = asyncio.create_task(
        picture_stage._enrich_picture_descriptions(
            manifest, Path("doc.pdf"), mode="medio", on_progress=save,
            vision=vision_config(concurrency=1),
            toolbox=toolbox_config(),
            models=model_config(), region_cache=None
        )
    )
    try:
        await asyncio.wait_for(started.wait(), 5)
        saved = job_checkpoint.load("pictures", PHASE_MANIFEST)
        by_id = {element["id"]: element for element in saved["manifest"]["elements"]}
        assert by_id["pic-1"]["metadata"].get("vision_description_complete") is True
        assert not by_id["pic-2"]["metadata"].get("vision_description_complete")
    finally:
        release.set()
        await task
