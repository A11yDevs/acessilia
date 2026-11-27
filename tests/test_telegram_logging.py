"""The Telegram bots log with loguru's brace placeholders, not printf (#759)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TELEGRAM = REPO_ROOT / "frontend" / "telegram"

#: A printf conversion such as ``%s`` or ``%d``: loguru would log it literally.
PRINTF = re.compile(r"%(?:\d+\$)?[-+#0 ]*\d*(?:\.\d+)?[sdifr]")


def _printf_log_calls() -> list[str]:
    """Every ``logger.*`` call whose message keeps a printf placeholder."""
    offenders: list[str] = []
    for path in sorted(TELEGRAM.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            target = node.func.value
            if not isinstance(target, ast.Name) or target.id != "logger" or not node.args:
                continue
            message = node.args[0]
            if isinstance(message, ast.Constant) and isinstance(message.value, str):
                if PRINTF.search(message.value):
                    relative = path.relative_to(REPO_ROOT)
                    offenders.append(f"{relative}:{node.lineno}: {message.value!r}")
    return offenders


def test_telegram_logger_calls_use_loguru_placeholders() -> None:
    offenders = _printf_log_calls()
    assert not offenders, (
        "use loguru braces (logger.warning('...: {}', error)) instead of printf "
        f"placeholders, which log literally: {offenders}"
    )
