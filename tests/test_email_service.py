import pytest

from backend.config.settings import settings
from backend.services.email_service import send_result_email


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
        completed_formats=["txt", "docx", "pdf", "html", "zip"],
        warnings=["Falha ao gerar MP3: tts offline"],
    )

    assert sent is True
    [body] = sent_messages
    assert "Texto (TXT)" in body
    assert "PDF/UA" not in body
    assert "Audiodescrição em Áudio (MP3)" not in body
    assert "Falha ao gerar MP3: tts offline" in body
