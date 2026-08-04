import asyncio
from pathlib import Path

import httpx
import pytest
import respx

from frontend.clients.api_client import ApiClient
from backend.config.settings import settings
from frontend.telegram.handlers import document as doc_module

BASE = "http://localhost:8000"


def _fake_pdf_bytes() -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n%%EOF\n"


class _FakeFile:
    def __init__(self, file_size=0):
        self.file_path = "doc.pdf"
        self.file_size = file_size


class _FakeSentMsg:
    def __init__(self, message_id):
        self.message_id = message_id


class _FakeBot:
    def __init__(self, content):
        self.content = content
        self.sent = []
        self.edited = []

    async def get_file(self, file_id):
        return _FakeFile(file_size=len(self.content))

    async def download_file(self, file_path, destination):
        Path(destination).write_bytes(self.content)

    async def send_message(self, chat_id, text, message_thread_id=None, parse_mode=None):
        self.sent.append(text)
        return _FakeSentMsg(len(self.sent))

    async def edit_message_text(self, text, chat_id=None, message_id=None, parse_mode=None):
        self.edited.append(text)


class _FakeChat:
    id = 123


class _FakeMessage:
    def __init__(self, bot, document=None, photo=None):
        self.bot = bot
        self.document = document
        self.photo = photo
        self.chat = _FakeChat()
        self.message_thread_id = None
        self.answers = []

    async def answer(self, text, **kwargs):
        self.answers.append(text)


class _FakeDocument:
    def __init__(self, file_name, file_size, file_id):
        self.file_name = file_name
        self.file_size = file_size
        self.file_id = file_id


class _FakePhoto:
    file_id = "photo1"


@pytest.fixture()
def doc_module_isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "temp_dir", tmp_path)
    monkeypatch.setattr(doc_module, "client", ApiClient(base_url=BASE))
    monkeypatch.setattr(doc_module, "POLL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(doc_module, "user_modes", {})
    monkeypatch.setattr(doc_module, "user_emails", {})
    monkeypatch.setattr(doc_module, "user_task_ids", {})
    return doc_module


def _mock_job_api(status_body: dict, task_id: str = "tg12345"):
    respx.post(f"{BASE}/api/v1/jobs").mock(
        return_value=httpx.Response(
            202, json={"task_id": task_id, "position": 1, "message": "ok"}
        )
    )
    respx.get(f"{BASE}/api/v1/jobs/{task_id}").mock(
        return_value=httpx.Response(200, json=status_body)
    )


def _done_status(task_id: str = "tg12345") -> dict:
    return {
        "task_id": task_id,
        "arquivo": "doc.pdf",
        "status": "done",
        "progresso": 1.0,
        "etapa_atual": "Processamento concluido",
        "erros": [],
        "download_url": "http://localhost:8000/api/v1/download/tok123",
    }


def test_document_flow_sends_download_link(doc_module_isolated):
    content = _fake_pdf_bytes()
    _mock_job_api(_done_status())
    bot = _FakeBot(content)
    msg = _FakeMessage(bot, document=_FakeDocument("doc.pdf", len(content), "file1"))

    with respx.mock:
        asyncio.run(doc_module_isolated.handle_document(msg))

    assert any("http://localhost:8000/api/v1/download/tok123" in s for s in bot.sent)
    assert doc_module_isolated.user_task_ids[(123, None)] == "tg12345"


def test_document_submits_with_mode_and_source(doc_module_isolated):
    content = _fake_pdf_bytes()
    route = respx.post(f"{BASE}/api/v1/jobs").mock(
        return_value=httpx.Response(
            202, json={"task_id": "tg12345", "position": 1, "message": "ok"}
        )
    )
    respx.get(f"{BASE}/api/v1/jobs/tg12345").mock(
        return_value=httpx.Response(200, json=_done_status())
    )

    doc_module_isolated.user_modes[(123, None)] = "detalhado"
    bot = _FakeBot(content)
    msg = _FakeMessage(bot, document=_FakeDocument("doc.pdf", len(content), "file1"))

    with respx.mock:
        asyncio.run(doc_module_isolated.handle_document(msg))
        body = route.calls[0].request.read()

    assert b'name="mode"' in body and b"detalhado" in body
    assert b'name="source"' in body and b"telegram" in body


def test_document_passes_email_and_notifies(doc_module_isolated):
    content = _fake_pdf_bytes()
    route = respx.post(f"{BASE}/api/v1/jobs").mock(
        return_value=httpx.Response(
            202, json={"task_id": "tg12345", "position": 1, "message": "ok"}
        )
    )
    respx.get(f"{BASE}/api/v1/jobs/tg12345").mock(
        return_value=httpx.Response(200, json=_done_status())
    )

    doc_module_isolated.user_emails[(123, None)] = "test@example.com"
    bot = _FakeBot(content)
    msg = _FakeMessage(bot, document=_FakeDocument("doc.pdf", len(content), "file1"))

    with respx.mock:
        asyncio.run(doc_module_isolated.handle_document(msg))
        body = route.calls[0].request.read()

    assert b"test@example.com" in body
    assert any("test@example.com" in a for a in msg.answers)


def test_document_api_error_sends_message(doc_module_isolated):
    content = _fake_pdf_bytes()
    respx.post(f"{BASE}/api/v1/jobs").mock(
        return_value=httpx.Response(400, json={"detail": "Formato não suportado"})
    )
    bot = _FakeBot(content)
    msg = _FakeMessage(bot, document=_FakeDocument("doc.pdf", len(content), "file1"))

    with respx.mock:
        asyncio.run(doc_module_isolated.handle_document(msg))

    assert any("Formato não suportado" in a for a in msg.answers)


def test_photo_flow(doc_module_isolated):
    content = _fake_pdf_bytes()
    _mock_job_api(_done_status())
    bot = _FakeBot(content)
    msg = _FakeMessage(bot, photo=[_FakePhoto()])

    with respx.mock:
        asyncio.run(doc_module_isolated.handle_photo(msg))

    assert any("http://localhost:8000/api/v1/download/tok123" in s for s in bot.sent)
