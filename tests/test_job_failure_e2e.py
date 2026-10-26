"""The real pipeline aborting on a corrupt file still notifies the user.

The documents in ``tests/fixtures/failures`` are inert corrupt files, never
read by production code, so reproducing the failure does not need a debug
switch in the application. This test walks the whole path a submission takes
after validation: the worker registers the job, the real PDDL pipeline tries to
process the document, fails, and the failure e-mail is sent. Only the SMTP
transport is replaced, because the test must not send real mail.

Marked ``e2e`` because the real pipeline needs the Toolbox; CI excludes it.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from backend.agents.state_manager import trim_stage
from backend.config.settings import settings
from backend.i18n import t
from backend.stage_messages import STAGE_ANALYZING_STRUCTURAL
from backend.tools.toolbox_client import toolbox_endpoints

FAILURES_DIR = Path(__file__).resolve().parent / "fixtures" / "failures"

#: Corrupt documents that must never be produced as a valid result.
FAILURE_FIXTURES = ("empty.pdf", "not-a-pdf.pdf", "truncated.pdf")


@pytest.fixture(scope="module", autouse=True)
def require_toolbox():
    """Skip unless a Toolbox answers, so a down service cannot pass this suite."""
    try:
        endpoints = toolbox_endpoints()
    except ValueError:
        pytest.skip("no Toolbox configured; set TOOLBOX_BASE_URL to run the e2e suite")
    for endpoint in endpoints:
        try:
            healthy = (
                httpx.get(f"{endpoint.base_url.rstrip('/')}/v1/health", timeout=10)
                .status_code
                == 200
            )
        except httpx.HTTPError:
            healthy = False
        if healthy:
            return
    pytest.skip(
        "no Toolbox reachable; set TOOLBOX_BASE_URL (or TOOLBOX_BASE_URLS) to run the e2e suite"
    )


@pytest.fixture
def failure_runtime(tmp_path, monkeypatch):
    import backend.services.history_service as history_service
    from backend.agents.state_manager import state_manager

    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "temp_dir", tmp_path / "temp")
    history_service._connection = None
    state_manager._tasks.clear()
    state_manager._cancel_events.clear()
    yield tmp_path
    if history_service._connection is not None:
        history_service._connection.close()
        history_service._connection = None


@pytest.mark.e2e
@pytest.mark.asyncio
@pytest.mark.parametrize("fixture_name", FAILURE_FIXTURES)
async def test_corrupt_document_ends_in_error_and_emails_the_user(
    failure_runtime, monkeypatch, fixture_name
):
    from backend.api.worker import ApiJob, JobExecutor
    from backend.services.job_store import load_record, save_request

    sent_failures: list[tuple[str, str, str]] = []

    async def record_failure(to_email, filename, error):
        sent_failures.append((to_email, filename, error))
        return True

    async def ignore_confirmation(*args, **kwargs):
        return True

    monkeypatch.setattr("backend.api.worker.send_failure_email", record_failure)
    monkeypatch.setattr("backend.api.worker.send_confirmation_email", ignore_confirmation)

    source = FAILURES_DIR / fixture_name
    task_id = f"corrupt-{source.stem}"
    # The worker deletes the submitted file as part of its cleanup, so the test
    # hands it a copy and keeps the checked-in fixture intact.
    uploaded = failure_runtime / "work" / "upload" / source.name
    uploaded.parent.mkdir(parents=True, exist_ok=True)
    uploaded.write_bytes(source.read_bytes())
    output_dir = failure_runtime / "output" / task_id
    save_request(task_id, "token", {}, {"status": "queued"})

    await JobExecutor().run(
        ApiJob(
            task_id=task_id,
            file_path=uploaded,
            filename=source.name,
            email="user@example.com",
            output_dir=output_dir,
        )
    )

    status = load_record(task_id)["status"]
    assert status["status"] == "error"
    assert not output_dir.exists()
    assert not uploaded.exists()
    assert source.is_file()
    [error] = status["erros"]
    # A down Toolbox is skipped above, so this is the corrupt document really
    # failing at structural extraction — not a generic connectivity failure.
    assert "document.structure.extract" in error
    assert trim_stage(t(STAGE_ANALYZING_STRUCTURAL)) in error
    [sent] = sent_failures
    assert sent[0] == "user@example.com"
    assert sent[1] == source.name
    assert sent[2]
    assert status["email_delivery"] == "sent"
