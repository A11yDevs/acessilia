"""A job reports the page it is on and says where it stopped when it fails.

Users only see ``etapa_atual`` and ``erros``. Before this, a document that broke
the pipeline left them with "Processing failed" and no way to tell which page
caused it, and a process killed mid-job (out of memory, a native crash) lost
even the stage, because the status was only persisted at the start and the end.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.agents.pddl_orchestrator import _pages_label, _plan_progress
from backend.agents.state_manager import describe_failure, state_manager
from backend.config.settings import settings
from backend.core.planning.models import PlanStep
from backend.i18n import t
from backend.stage_messages import (
    STAGE_DESCRIBING_IMAGE,
    STAGE_EXECUTING_PLAN_STEP,
    STAGE_PAGE,
    STAGE_PAGE_OF,
    STAGE_PAGE_UNKNOWN,
    STAGE_PAGES,
    STAGE_RESTART_INTERRUPTED_DURING,
)
from tests.pddl_support import (
    build_element as _element,
)
from tests.pddl_support import (
    build_manifest as _manifest,
)
from tests.pddl_support import (
    build_obligation as _obligation,
)
from tests.pddl_support import (
    build_orchestrator as _orchestrator,
)


@pytest.fixture
def job_db(tmp_path, monkeypatch):
    import backend.services.history_service as hs

    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    hs._connection = None
    state_manager._tasks.clear()
    state_manager._cancel_events.clear()
    yield tmp_path
    hs._connection = None


@pytest.fixture
def sent_failures(monkeypatch):
    sent: list[tuple[str, str, str]] = []

    async def record(to_email, filename, error):
        sent.append((to_email, filename, error))
        return True

    async def no_confirmation(*args, **kwargs):
        return True

    monkeypatch.setattr("backend.api.worker.send_failure_email", record)
    monkeypatch.setattr("backend.api.worker.send_confirmation_email", no_confirmation)
    return sent


@pytest.fixture
def warning_messages():
    """Collect loguru warnings so a swallowed notification error stays visible."""
    from loguru import logger as loguru_logger

    messages: list[str] = []
    handler_id = loguru_logger.add(
        lambda message: messages.append(str(message)), level="WARNING"
    )
    yield messages
    loguru_logger.remove(handler_id)


class TestPagesLabel:
    def test_single_page(self):
        assert _pages_label([3, 3, None]) == t(STAGE_PAGE).format(page=3)
    def test_single_page_of_a_multi_page_document_names_the_total(self):
        assert _pages_label([3, 3, None], 42) == t(STAGE_PAGE_OF).format(
            page=3, total_pages=42
        )

    def test_single_page_of_a_one_page_document_keeps_the_plain_label(self):
        assert _pages_label([1, 1, None], 1) == t(STAGE_PAGE).format(page=1)

    def test_several_pages_are_sorted_and_deduplicated(self):
        assert _pages_label([5, 2, 5]) == t(STAGE_PAGES).format(pages="2, 5")

    def test_unknown_page(self):
        assert _pages_label([None]) == t(STAGE_PAGE_UNKNOWN)


def test_the_image_progress_message_names_the_location_with_the_page_total():
    from backend.i18n import reset_request_locale, set_request_locale

    token = set_request_locale("en_US")
    try:
        assert (
            t(STAGE_DESCRIBING_IMAGE).format(
                current=11,
                total=37,
                pages=t(STAGE_PAGE_OF).format(page=18, total_pages=42),
            )
            == "Describing image 11 of 37 (this image is on page 18 of 42)..."
        )
    finally:
        reset_request_locale(token)


def test_executor_reports_each_step_before_running_it():
    manifest = _manifest(
        [_element("text", "paragraph", text="First line 5\nSecond line 10")],
        [_obligation("chunk-verse", ["text"], ["verse-chunker", "human-review"])],
    )
    orchestrator = _orchestrator()
    plan, _ = orchestrator._build_plan(manifest)
    calls: list[tuple[str, int, int]] = []

    _, report = orchestrator.executor.execute(
        plan,
        manifest,
        dry_run=False,
        progress=lambda step, position, total: calls.append(
            (step.action, position, total)
        ),
    )

    total = len(plan.steps)
    assert calls == [(step.action, i, total) for i, step in enumerate(plan.steps, 1)]
    assert len(report.steps) == total


@pytest.mark.asyncio
async def test_plan_progress_names_the_obligation_pages_from_the_executor_thread():
    first = _element("a", "paragraph", text="x")
    second = _element("b", "paragraph", text="y")
    first.page_number, second.page_number = 5, 2
    manifest = _manifest(
        [first, second], [_obligation("adjudicate-page", ["a", "b"], ["human-review"])]
    )
    messages: list[str] = []

    async def status_callback(message: str) -> None:
        messages.append(message)

    report = _plan_progress(manifest, status_callback, asyncio.get_running_loop())
    step = PlanStep(
        index=3,
        action="execute-obligation",
        obligation_id="o-1",
        obligation_kind="adjudicate-page",
        method="human-review",
    )
    await asyncio.to_thread(report, PlanStep(index=0, action="start-job"), 1, 9)
    await asyncio.to_thread(report, step, 4, 9)

    assert messages == [
        t(STAGE_EXECUTING_PLAN_STEP).format(
            current=4,
            total=9,
            pages=t(STAGE_PAGES).format(pages="2, 5"),
        )
    ]
    # The obligation kind is internal jargon; the user only sees step and pages.
    assert "adjudicate-page" not in messages[0]


@pytest.mark.asyncio
async def test_a_failing_progress_report_does_not_fail_the_step():
    manifest = _manifest(
        [_element("a", "paragraph", text="x")],
        [_obligation("chunk-verse", ["a"], ["verse-chunker"])],
    )

    async def broken(message: str) -> None:
        raise OSError("database is locked")

    report = _plan_progress(manifest, broken, asyncio.get_running_loop())
    step = PlanStep(
        index=1,
        action="execute-obligation",
        obligation_id="o-1",
        obligation_kind="chunk-verse",
        method="verse-chunker",
    )
    await asyncio.to_thread(report, step, 1, 1)


@pytest.mark.asyncio
async def test_a_broken_label_translation_does_not_fail_the_step(monkeypatch):
    manifest = _manifest(
        [_element("a", "paragraph", text="x")],
        [_obligation("chunk-verse", ["a"], ["verse-chunker"])],
    )
    messages: list[str] = []

    async def status_callback(message: str) -> None:
        messages.append(message)

    # A catalog entry with a placeholder the code does not pass.
    monkeypatch.setattr(
        "backend.agents.pddl_orchestrator.t", lambda msgid: "{missing} {current}"
    )
    report = _plan_progress(manifest, status_callback, asyncio.get_running_loop())
    step = PlanStep(
        index=1,
        action="execute-obligation",
        obligation_id="o-1",
        obligation_kind="chunk-verse",
        method="verse-chunker",
    )
    await asyncio.to_thread(report, step, 1, 1)
    assert messages == []


@pytest.mark.asyncio
async def test_pipeline_failure_names_the_stage_once_and_emails_the_user(
    job_db, monkeypatch, sent_failures
):
    from backend import service
    from backend.api.worker import ApiJob, JobExecutor
    from backend.services.job_store import load_record, save_request

    task_id = "page-failure"
    input_path = job_db / "006.pdf"
    input_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    stage = "Describing image 2 of 3 (page 4)..."
    persisted_mid_run: list[str] = []
    save_request(task_id, "token", {}, {"status": "queued"})

    async def fail_on_page_four(file_path, tmpdir, status_callback, **kwargs):
        await status_callback(stage)
        persisted_mid_run.append(load_record(task_id)["status"]["etapa_atual"])
        raise RuntimeError("vision model crashed")

    monkeypatch.setattr(service.agente, "executar", fail_on_page_four)

    await JobExecutor().run(
        ApiJob(
            task_id=task_id,
            file_path=input_path,
            filename="006.pdf",
            email="user@example.com",
            output_dir=job_db / "output",
        )
    )

    expected = describe_failure("vision model crashed", stage)
    assert persisted_mid_run == [stage]
    assert state_manager.obter(task_id)["erros"] == [expected]
    assert state_manager.obter(task_id)["email_delivery"] == "sent"
    assert load_record(task_id)["status"]["erros"] == [expected]
    assert load_record(task_id)["status"]["email_delivery"] == "sent"
    assert sent_failures == [("user@example.com", "006.pdf", expected)]


@pytest.mark.asyncio
async def test_restart_reports_the_last_persisted_stage_and_emails_the_user(
    job_db, sent_failures
):
    from backend.api.worker import recover_pending_jobs
    from backend.services.job_store import load_record, save_request

    stage = "Executing the plan: step 3 of 9, page 7 (adjudicate-page)..."
    save_request(
        "killed",
        "token",
        {"file_path": str(job_db / "006.pdf"), "filename": "006.pdf", "email": "user@example.com"},
        {"task_id": "killed", "status": "processing", "etapa_atual": stage, "erros": []},
    )

    await recover_pending_jobs()

    status = load_record("killed")["status"]
    expected = t(STAGE_RESTART_INTERRUPTED_DURING).format(
        stage="Executing the plan: step 3 of 9, page 7 (adjudicate-page)"
    )
    assert status["status"] == "error"
    assert status["erros"] == [expected]
    assert status["email_delivery"] == "sent"
    assert sent_failures == [("user@example.com", "006.pdf", expected)]

    # The error is saved before the e-mail goes out, so a server in a crash
    # loop does not e-mail the same interrupted job again on every restart.
    await recover_pending_jobs()
    assert len(sent_failures) == 1


@pytest.mark.asyncio
async def test_a_broken_failure_email_keeps_the_job_error_and_records_the_failure(
    job_db, monkeypatch, warning_messages
):
    """A mailer that raises must not mask the pipeline error or fail the job twice."""
    from backend import service
    from backend.api.worker import ApiJob, JobExecutor
    from backend.services.job_store import load_record, save_request

    task_id = "broken-mailer"
    input_path = job_db / "006.pdf"
    input_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    output_dir = job_db / "output" / task_id
    save_request(task_id, "token", {}, {"status": "queued"})

    async def fail_pipeline(*args, **kwargs):
        raise RuntimeError("vision model crashed")

    async def broken_mailer(to_email, filename, error):
        raise OSError("smtp offline")

    monkeypatch.setattr(service.agente, "executar", fail_pipeline)
    monkeypatch.setattr("backend.api.worker.send_failure_email", broken_mailer)

    await JobExecutor().run(
        ApiJob(
            task_id=task_id,
            file_path=input_path,
            filename="006.pdf",
            email="user@example.com",
            output_dir=output_dir,
        )
    )

    task = state_manager.obter(task_id)
    assert task["status"] == "error"
    [expected] = task["erros"]
    assert "vision model crashed" in expected
    assert task["email_delivery"] == "failed"
    durable = load_record(task_id)["status"]
    assert durable["status"] == "error"
    assert durable["erros"] == [expected]
    assert durable["email_delivery"] == "failed"
    assert any(task_id in message for message in warning_messages)


@pytest.mark.asyncio
async def test_restart_records_a_failure_email_that_could_not_be_sent(
    job_db, monkeypatch, warning_messages
):
    from backend.api.worker import recover_pending_jobs
    from backend.services.job_store import load_record, save_request

    async def broken_mailer(to_email, filename, error):
        return False

    monkeypatch.setattr("backend.api.worker.send_failure_email", broken_mailer)
    save_request(
        "killed-broken-mailer",
        "token",
        {
            "file_path": str(job_db / "006.pdf"),
            "filename": "006.pdf",
            "email": "user@example.com",
        },
        {
            "task_id": "killed-broken-mailer",
            "status": "processing",
            "etapa_atual": "",
            "erros": [],
        },
    )

    await recover_pending_jobs()

    status = load_record("killed-broken-mailer")["status"]
    assert status["status"] == "error"
    assert status["email_delivery"] == "failed"
    assert any("killed-broken-mailer" in message for message in warning_messages)
