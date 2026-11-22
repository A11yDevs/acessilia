"""Startup logs the bot identity and publishes localized command lists (#397)."""

from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace

from frontend.telegram import bot as bot_module
from frontend.telegram.commands import bot_commands, telegram_language


def test_commands_come_from_the_help_text_in_both_locales() -> None:
    english = {command.command: command.description for command in bot_commands("en_US")}
    portuguese = {command.command: command.description for command in bot_commands("pt_BR")}

    assert {"start", "help", "formats", "email", "status", "cancel"} <= set(english)
    assert {"start", "ajuda", "help", "formatos", "email", "cancelar"} <= set(portuguese)
    assert english["start"] == "Start the bot"
    assert portuguese["start"] == "Iniciar o bot"
    for command in (*english, *portuguese):
        assert re.fullmatch(r"[a-z0-9_]{1,32}", command)
    for description in (*english.values(), *portuguese.values()):
        assert description and len(description) <= 256


def test_language_code_uses_the_base_locale() -> None:
    assert telegram_language("en_US") == "en"
    assert telegram_language("pt_BR") == "pt"


def test_startup_registers_commands_and_warns_about_privacy(monkeypatch) -> None:
    calls: list[list[str]] = []
    languages: list[str | None] = []
    warnings: list[str] = []

    class FakeBot:
        async def get_me(self):
            return SimpleNamespace(
                username="acessilia_test_bot",
                can_read_all_group_messages=False,
            )

        async def set_my_commands(self, commands, language_code=None):
            calls.append([command.command for command in commands])
            languages.append(language_code)

    async def no_resume(_bot) -> None:
        return None

    monkeypatch.setattr(bot_module, "active_locales", lambda: ("en_US", "pt_BR"))
    monkeypatch.setattr(bot_module, "resume_tracked_tasks", no_resume)
    monkeypatch.setattr(
        bot_module.logger,
        "warning",
        lambda message, *args: warnings.append(str(message)),
    )

    asyncio.run(bot_module.on_startup(FakeBot()))

    assert languages == [None, "pt"]
    assert "start" in calls[0]
    assert "help" in calls[0]
    assert "ajuda" in calls[1]
    assert any("privacy mode" in warning for warning in warnings)


def test_startup_survives_telegram_metadata_failures(monkeypatch) -> None:
    async def no_resume(_bot) -> None:
        return None

    class FailingBot:
        async def get_me(self):
            raise RuntimeError("getMe failed")

        async def set_my_commands(self, commands, language_code=None):
            raise RuntimeError("setMyCommands failed")

    monkeypatch.setattr(bot_module, "resume_tracked_tasks", no_resume)

    asyncio.run(bot_module.on_startup(FailingBot()))
