"""Telegram command suggestions derived from the same text `/help` renders (#397)."""

from __future__ import annotations

import html
import re

from aiogram.types import BotCommand

from acessilia_core.i18n import get_translations
from frontend.telegram.messages import MSG_HELP_TEXT

#: A help line looks like ``/command - Description``; aliases may be joined by
#: ``ou`` (pt-BR) or ``or`` (English), e.g. ``/ajuda ou /help``.
_ALIAS_SPLIT = re.compile(r"\s+(?:ou|or)\s+", re.IGNORECASE)
_COMMAND = re.compile(r"[a-z0-9_]{1,32}")


def bot_commands(locale: str) -> list[BotCommand]:
    """Build the command list for ``locale`` from its translated ``/help`` text.

    Reusing the help message keeps the BotFather suggestions in sync with the
    commands the bot documents and handles, including localized aliases such as
    ``/ajuda`` and ``/cancelar``. Only command-shaped tokens are accepted.
    """
    text = get_translations(locale).gettext(MSG_HELP_TEXT)
    commands: dict[str, BotCommand] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("/") or " - " not in line:
            continue
        names, description = line.split(" - ", 1)
        description = html.unescape(description.strip())
        for part in _ALIAS_SPLIT.split(names):
            part = html.unescape(part).strip()
            if not part.startswith("/"):
                continue
            command = part.split(maxsplit=1)[0].lstrip("/").lower()
            if _COMMAND.fullmatch(command) and command not in commands:
                commands[command] = BotCommand(
                    command=command, description=description
                )
    return list(commands.values())


def telegram_language(locale: str) -> str:
    """The Bot API ``language_code`` for an Acessilia locale (``pt_BR`` → ``pt``)."""
    return locale.split("_", 1)[0].lower()
