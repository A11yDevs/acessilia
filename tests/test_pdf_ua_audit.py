"""The veraPDF audit of the PDF/UA: its e-mail summary, and the worker step.

Every user-visible line is resolved through backend.i18n.t, so the assertions
hold under any supported server locale.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from backend.config.settings import settings
from backend.i18n import t
from backend.log_messages import (
    EMAIL_AUDIT_COMPLIANT,
    EMAIL_AUDIT_MORE_RULES,
    EMAIL_AUDIT_NON_COMPLIANT,
    EMAIL_AUDIT_RULE,
    EMAIL_AUDIT_UNAVAILABLE,
    EMAIL_RESULT_AUDIT_HEADER,
)
from backend.tools.pdf_ua_audit import audit_pdf_ua, summarize_audit
from tests.conftest import COMPLIANT_PDF_UA_REPORT


def _rule(clause: str, test_number: int, failed_checks: int, description: str = "A rule") -> dict:
    return {
        "specification": "ISO 14289-1:2014",
        "clause": clause,
        "test_number": test_number,
        "description": description,
        "object": "PDDocument",
        "test": "x == true",
        "tags": ["structure"],
        "failed_checks": failed_checks,
        "checks": [],
    }


def _non_compliant(*failures: dict) -> dict:
    return {
        **COMPLIANT_PDF_UA_REPORT,
        "compliant": False,
        "statement": "PDF file is not compliant with Validation Profile requirements.",
        "failures": list(failures),
    }


def _rule_line(rule: dict) -> str:
    return t(EMAIL_AUDIT_RULE).format(
        specification=rule["specification"],
        clause=rule["clause"],
        test=rule["test_number"],
        description=rule["description"],
        checks=rule["failed_checks"],
    )


def test_a_compliant_pdf_is_one_line():
    assert summarize_audit(COMPLIANT_PDF_UA_REPORT, max_rules=10) == [
        t(EMAIL_AUDIT_COMPLIANT).format(profile="PDF/UA-1")
    ]


def test_failed_rules_are_listed_most_frequent_first():
    rare = _rule("7.1", 11, 1, "StructTreeRoot\n  required")
    common = _rule("7.18.1", 4, 12)

    lines = summarize_audit(_non_compliant(rare, common), max_rules=10)

    assert lines == [
        t(EMAIL_AUDIT_NON_COMPLIANT).format(profile="PDF/UA-1", rules=2, checks=13),
        _rule_line(common),
        # A description spanning lines is put on one, as the e-mail lists it.
        _rule_line({**rare, "description": "StructTreeRoot required"}),
    ]


def test_rules_beyond_the_cap_are_counted_not_listed():
    rules = [_rule("7.1", number, 10 - number) for number in range(1, 6)]

    lines = summarize_audit(_non_compliant(*rules), max_rules=2)

    assert lines[1:] == [
        _rule_line(rules[0]),
        _rule_line(rules[1]),
        t(EMAIL_AUDIT_MORE_RULES).format(count=3),
    ]


@pytest.mark.parametrize("max_rules", [0, -1])
def test_a_zero_or_negative_cap_lists_no_rule_and_counts_them_all(max_rules):
    rules = [_rule("7.1", number, 1) for number in range(1, 4)]

    lines = summarize_audit(_non_compliant(*rules), max_rules=max_rules)

    assert lines[1:] == [t(EMAIL_AUDIT_MORE_RULES).format(count=3)]


def test_a_report_without_a_profile_still_names_the_standard():
    report = {key: value for key, value in COMPLIANT_PDF_UA_REPORT.items() if key != "profile"}

    assert summarize_audit(report, max_rules=10) == [
        t(EMAIL_AUDIT_COMPLIANT).format(profile="PDF/UA")
    ]


def test_a_negative_cap_is_refused_at_startup(monkeypatch):
    from backend.config.settings import Settings

    monkeypatch.setenv("PDF_UA_AUDIT_MAX_RULES", "-1")
    with pytest.raises(ValueError, match="PDF_UA_AUDIT_MAX_RULES"):
        Settings()


@pytest.mark.asyncio
async def test_no_audit_when_validation_is_disabled(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "toolbox_pdf_validate_enabled", False)

    class Unused:
        async def validate(self, **_kwargs):
            pytest.fail("validated with TOOLBOX_PDF_VALIDATE_ENABLED=false")

    assert await audit_pdf_ua(tmp_path / "doc.pdf_ua.pdf", client=Unused()) is None


@pytest.mark.asyncio
async def test_the_audit_validates_against_pdf_ua_1(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "toolbox_pdf_validate_enabled", True)
    calls = []

    class Client:
        async def validate(self, **kwargs):
            calls.append(kwargs)
            return COMPLIANT_PDF_UA_REPORT

    pdf = tmp_path / "doc.pdf_ua.pdf"

    assert await audit_pdf_ua(pdf, client=Client()) == COMPLIANT_PDF_UA_REPORT
    [call] = calls
    assert call["file_path"] == pdf and call["profile"] == "ua1"


@pytest.mark.asyncio
async def test_the_worker_packages_the_report(monkeypatch, tmp_path):
    from backend.api import worker

    report = _non_compliant(_rule("7.1", 11, 1))

    async def audit(_pdf_path, **_kwargs):
        return report

    monkeypatch.setattr(worker, "audit_pdf_ua", audit)
    executor = worker.JobExecutor()
    try:
        lines, path = await executor._audit_pdf_ua(
            "task", tmp_path / "doc.pdf_ua.pdf", tmp_path / "doc.pdf_ua.verapdf.json"
        )
    finally:
        executor._executor.shutdown(wait=True)

    assert json.loads(path.read_text(encoding="utf-8")) == report
    assert lines == summarize_audit(report, max_rules=settings.pdf_ua_audit_max_rules)


@pytest.mark.asyncio
async def test_a_failed_audit_does_not_fail_the_job(monkeypatch, tmp_path):
    from backend.api import worker

    async def audit(_pdf_path, **_kwargs):
        raise TimeoutError("http://toolbox.internal:8000 timed out")

    monkeypatch.setattr(worker, "audit_pdf_ua", audit)
    executor = worker.JobExecutor()
    try:
        lines, path = await executor._audit_pdf_ua(
            "task", tmp_path / "doc.pdf_ua.pdf", tmp_path / "doc.pdf_ua.verapdf.json"
        )
    finally:
        executor._executor.shutdown(wait=True)

    # Only the kind of failure: the cause names internal Toolbox endpoints.
    assert lines == [t(EMAIL_AUDIT_UNAVAILABLE).format(error="TimeoutError")]
    assert path is None


@pytest.mark.asyncio
async def test_the_result_email_carries_the_audit_before_the_warnings(monkeypatch):
    from backend.services import email_service

    bodies = []

    async def fake_send(_to_email, _subject, body, attachment_path=None):
        bodies.append(body)
        return True

    monkeypatch.setattr(email_service, "send_email_notification", fake_send)
    rule = _rule("7.1", 11, 1)
    audit = summarize_audit(_non_compliant(rule), max_rules=10)

    await email_service.send_result_email(
        "test@example.invalid",
        "doc.pdf",
        download_url="https://acessilia.example/download/tok",
        completed_formats=["txt", "pdf_ua"],
        warnings=["DOCX failed"],
        audit=audit,
    )

    [body] = bodies
    section = f"{t(EMAIL_RESULT_AUDIT_HEADER)}\n{audit[0]}\n- {_rule_line(rule)}"
    assert section in body
    assert body.index(section) < body.index("- DOCX failed")


async def _run_audit_step(tmp_path, task_id: str = "task") -> tuple[list[str], Path | None]:
    from backend.api import worker

    executor = worker.JobExecutor()
    try:
        return await executor._audit_pdf_ua(
            task_id, tmp_path / "doc.pdf_ua.pdf", tmp_path / "doc.pdf_ua.verapdf.json"
        )
    finally:
        executor._executor.shutdown(wait=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failures", "error"),
    [(["oops"], "AttributeError"), ([{"failed_checks": "N/A"}], "ValueError")],
)
async def test_a_report_that_cannot_be_summarized_does_not_fail_the_job(
    monkeypatch, tmp_path, failures, error
):
    from backend.api import worker

    async def audit(_pdf_path, **_kwargs):
        return {**COMPLIANT_PDF_UA_REPORT, "compliant": False, "failures": failures}

    monkeypatch.setattr(worker, "audit_pdf_ua", audit)

    lines, path = await _run_audit_step(tmp_path)

    assert lines == [t(EMAIL_AUDIT_UNAVAILABLE).format(error=error)]
    assert path is None
    assert not (tmp_path / "doc.pdf_ua.verapdf.json").exists()


@pytest.mark.asyncio
async def test_a_report_that_cannot_be_written_does_not_fail_the_job(monkeypatch, tmp_path):
    from backend.api import worker

    async def audit(_pdf_path, **_kwargs):
        return COMPLIANT_PDF_UA_REPORT

    def write_text(self, *_args, **_kwargs):
        raise OSError("No space left on device")

    monkeypatch.setattr(worker, "audit_pdf_ua", audit)
    monkeypatch.setattr(Path, "write_text", write_text)

    lines, path = await _run_audit_step(tmp_path)

    assert lines == [t(EMAIL_AUDIT_UNAVAILABLE).format(error="OSError")]
    assert path is None


@pytest.mark.asyncio
async def test_a_cancel_ends_the_audit_wait(monkeypatch, tmp_path):
    from backend.agents.state_manager import TaskCancelledError, state_manager
    from backend.api import worker

    started = asyncio.Event()
    abandoned = asyncio.Event()

    async def audit(_pdf_path, **_kwargs):
        started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            abandoned.set()
            raise

    monkeypatch.setattr(worker, "audit_pdf_ua", audit)
    task_id = state_manager.criar_tarefa(tmp_path / "doc.pdf", task_id="audit-cancel")

    async def cancel_once_started():
        await started.wait()
        state_manager.cancelar(task_id)

    canceller = asyncio.create_task(cancel_once_started())
    with pytest.raises(TaskCancelledError):
        await asyncio.wait_for(_run_audit_step(tmp_path, task_id), timeout=5)
    await canceller
    await asyncio.wait_for(abandoned.wait(), timeout=1)
