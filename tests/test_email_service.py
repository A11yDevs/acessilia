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
