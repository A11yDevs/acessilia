"""
What this module verifies: the result e-mail sent when a job finishes lists only the actually-completed
output formats and appends any optional-format failures, with every user-visible line resolved through the
active locale's Babel catalog (backend.i18n.t) so the assertions stay correct under any supported server locale.
"""

import pytest

from backend.i18n import t
from backend.log_messages import EMAIL_FAILURE_SUBJECT, EMAIL_FORMAT_MP3, EMAIL_FORMAT_TXT
from backend.config.settings import settings
from backend.services.email_service import send_failure_email, send_result_email


@pytest.mark.asyncio
async def test_failure_email_reports_missing_smtp(monkeypatch):
    monkeypatch.setattr(settings, "smtp_user", "")
    monkeypatch.setattr(settings, "smtp_password", "")

    sent = await send_failure_email(
        "test@example.invalid", "doc.pdf", "the pipeline raised"
    )

    assert sent is False


@pytest.mark.asyncio
async def test_failure_email_names_the_file_and_the_reason(monkeypatch):
    from backend.services import email_service

    sent_messages = []

    async def fake_send(to_email, subject, body, attachment_path=None):
        sent_messages.append((to_email, subject, body))
        return True

    monkeypatch.setattr(email_service, "send_email_notification", fake_send)

    sent = await send_failure_email(
        "test@example.invalid", "006.pdf", "vision model crashed (page 4)"
    )

    assert sent is True
    [(to_email, subject, body)] = sent_messages
    assert to_email == "test@example.invalid"
    assert subject == t(EMAIL_FAILURE_SUBJECT)
    assert "006.pdf" in body
    assert "vision model crashed (page 4)" in body


@pytest.mark.asyncio
@pytest.mark.parametrize("recipient", ["invalid\nrecipient@example.test", "invalid\rrecipient@example.test"])
async def test_invalid_legacy_recipient_returns_false_without_smtp(monkeypatch, recipient):
    from unittest.mock import AsyncMock
    from backend.services import email_service

    monkeypatch.setattr(settings, "smtp_user", "audit@example.test")
    monkeypatch.setattr(settings, "smtp_password", "fake-password")
    send = AsyncMock()
    monkeypatch.setattr(email_service.aiosmtplib, "send", send)

    assert await email_service.send_failure_email(recipient, "doc.pdf", "interrupted") is False
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_result_email_reports_missing_smtp(monkeypatch):
    monkeypatch.setattr(settings, "smtp_user", "")
    monkeypatch.setattr(settings, "smtp_password", "")

    sent = await send_result_email(
        "test@example.invalid",
        "doc.pdf",
        download_url="https://acessilia.example/download/tok",
    )

    assert sent is False


@pytest.mark.asyncio
async def test_result_email_lists_only_completed_formats(monkeypatch):
    from backend.services import email_service

    sent_messages = []

    async def fake_send(to_email, subject, body, attachment_path=None):
        sent_messages.append(body)
        return True

    monkeypatch.setattr(email_service, "send_email_notification", fake_send)

    sent = await send_result_email(
        "test@example.invalid",
        "doc.pdf",
        download_url="https://acessilia.example/download/tok",
        completed_formats=["txt", "docx", "html", "zip"],
        warnings=["Falha ao gerar MP3: tts offline"],
    )

    assert sent is True
    [body] = sent_messages
    # The TXT label is localized at send time; t() resolves it in the active locale.
    assert t(EMAIL_FORMAT_TXT) in body
    # Formats that were not produced must not appear in the e-mail body.
    assert "PDF/UA" not in body
    assert t(EMAIL_FORMAT_MP3) not in body
    # Raw per-format failure warnings pass through verbatim into the body.
    assert "Falha ao gerar MP3: tts offline" in body
