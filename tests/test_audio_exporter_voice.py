"""Voice selection for the edge-tts MP3 export."""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import ClassVar

import pytest

from backend.config import settings as settings_module
from backend.config.settings import settings
from backend.export.exporters import audio_exporter


class _FakeCommunicate:
    voices: ClassVar[list[str]] = []

    def __init__(self, text: str, voice: str) -> None:
        self.voices.append(voice)

    async def save(self, path: str) -> None:
        Path(path).write_bytes(b"ID3")


@pytest.fixture
def fake_tts(monkeypatch):
    _FakeCommunicate.voices = []
    monkeypatch.setattr(audio_exporter.edge_tts, "Communicate", _FakeCommunicate)
    return _FakeCommunicate


def test_default_voice_is_pinned(monkeypatch):
    # pt-BR-ThalitaNeural left the edge-tts catalogue; keep the default on a listed voice.
    monkeypatch.delenv("TTS_VOICE", raising=False)
    field = settings_module.Settings.__dataclass_fields__["tts_voice"]
    assert field.default is dataclasses.MISSING
    assert field.default_factory() == "pt-BR-FranciscaNeural"


@pytest.mark.asyncio
async def test_export_uses_the_configured_voice(monkeypatch, fake_tts, tmp_path):
    monkeypatch.setattr(settings, "tts_voice", "pt-BR-AntonioNeural")

    await audio_exporter.export_mp3("Olá.", tmp_path / "out.mp3")

    assert fake_tts.voices == ["pt-BR-AntonioNeural"]


@pytest.mark.asyncio
async def test_explicit_voice_overrides_the_setting(monkeypatch, fake_tts, tmp_path):
    monkeypatch.setattr(settings, "tts_voice", "pt-BR-AntonioNeural")

    await audio_exporter.export_mp3("Olá.", tmp_path / "out.mp3", voice="pt-BR-FranciscaNeural")

    assert fake_tts.voices == ["pt-BR-FranciscaNeural"]
