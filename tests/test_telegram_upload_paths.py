"""Only application-generated local names may be used for Telegram downloads."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.config.settings import settings
from frontend.clients.api_client import ApiError
from frontend.telegram.handlers import document
from tests.test_telegram_client import _FakeBot, _FakeMessage


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["handler", "direct"])
@pytest.mark.parametrize("name", ["../victim.pdf", "..\\victim.pdf", "absolute", "C:\\outside\\victim.pdf", "documento ç.pdf"])
async def test_telegram_download_uses_generated_contained_filename(monkeypatch, tmp_path, route, name):
    temporary_root = tmp_path / "temp"
    temporary_root.mkdir()
    monkeypatch.setattr(settings, "temp_dir", temporary_root)
    victim = tmp_path / "victim.pdf"
    victim.write_bytes(b"original sentinel")
    local_victim = temporary_root / "victim.pdf"
    local_victim.write_bytes(b"another sentinel")
    filename = str(victim) if name == "absolute" else name
    submitted = []

    async def reject(path, filename, **kwargs):
        submitted.append((path, filename))
        assert path.resolve().is_relative_to(temporary_root.resolve())
        assert path.parent != temporary_root
        assert path.name != filename
        assert path.suffix == ".pdf"
        assert path.read_bytes() == b"uploaded harmless content"
        raise ApiError(400, "Stop after the simulated download")

    monkeypatch.setattr(document, "client", SimpleNamespace(submit_job=reject))
    message = _FakeMessage(_FakeBot(b"uploaded harmless content"), document=SimpleNamespace(
        file_name=filename, file_size=10, file_id="fake",
    ))
    if route == "handler":
        await document.handle_document(message)
    else:
        await document.process_file(message, "fake", filename)
    assert len(submitted) == 1
    assert submitted[0][1] == Path(filename.replace("\\", "/")).name
    assert not submitted[0][0].exists()
    assert victim.read_bytes() == b"original sentinel"
    assert local_victim.read_bytes() == b"another sentinel"
