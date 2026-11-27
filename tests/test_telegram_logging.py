"""The Telegram bots log with loguru's brace placeholders, not printf (#759)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TELEGRAM = REPO_ROOT / "frontend" / "telegram"

#: A printf conversion such as ``%s``, ``%d`` or ``%(task_id)s``. The space
#: flag is deliberately absent so prose such as ``"95% done"`` is not treated
#: as a placeholder, and the lookahead leaves ``"100%success"`` alone.
PRINTF = re.compile(
    r"%(?:\d+\$|\([^)]*\))?[-+#0]*\d*(?:\.\d+)?[diouxXeEfFgGcrsa](?![A-Za-z0-9_])"
)


def _logger_aliases(tree: ast.AST) -> set[str]:
    """The names this module uses for the project's loguru logger."""
    aliases = {"logger"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "acessilia_core.logger":
            for alias in node.names:
                if alias.name == "logger":
                    aliases.add(alias.asname or alias.name)
    return aliases


def _is_logger(node: ast.AST, aliases: set[str]) -> bool:
    """Whether ``node`` is the logger or a loguru chain rooted at it."""
    if isinstance(node, ast.Name):
        return node.id in aliases
    if isinstance(node, ast.Attribute):
        return _is_logger(node.value, aliases)
    if isinstance(node, ast.Call):
        return _is_logger(node.func, aliases)
    return False


def _printf_calls_in(tree: ast.AST, aliases: set[str]) -> list[tuple[int, str]]:
    """``(line, message)`` for each logger call with a printf placeholder."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if not node.args or not _is_logger(node.func.value, aliases):
            continue
        message = node.args[0]
        if isinstance(message, ast.Constant) and isinstance(message.value, str):
            if PRINTF.search(message.value):
                found.append((node.lineno, message.value))
    return found


def _printf_log_calls() -> list[str]:
    """Every ``logger.*`` call whose message keeps a printf placeholder."""
    paths = sorted(TELEGRAM.rglob("*.py"))
    assert paths, f"no Python files under {TELEGRAM}; the guard would pass vacuously"
    offenders: list[str] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        relative = path.relative_to(REPO_ROOT)
        for line, message in _printf_calls_in(tree, _logger_aliases(tree)):
            offenders.append(f"{relative}:{line}: {message!r}")
    return offenders


def test_telegram_logger_calls_use_loguru_placeholders() -> None:
    offenders = _printf_log_calls()
    assert not offenders, (
        "use loguru braces (logger.warning('...: {}', error)) instead of printf "
        f"placeholders, which log literally: {offenders}"
    )


@pytest.mark.parametrize(
    "message",
    [
        "Telegram state store unavailable: %s",
        "value %d",
        "crc mismatch: 0x%x",
        "octal %o",
        "rate %e",
        "char %c",
        "upper %X",
        "mapping %(task_id)s",
        "padded %02d",
    ],
)
def test_the_printf_pattern_matches_real_placeholders(message: str) -> None:
    assert PRINTF.search(message), message


@pytest.mark.parametrize(
    "message",
    [
        "95% done",
        "50% idle",
        "100% success",
        "100%success",
        "no placeholder",
    ],
)
def test_the_printf_pattern_ignores_prose_percentages(message: str) -> None:
    assert not PRINTF.search(message), message


@pytest.mark.parametrize(
    "source",
    [
        "logger.warning('state: %s', error)\n",
        "logger.opt(exception=True).warning('state: %s', error)\n",
        "logger.bind(task=1).warning('state: %s', error)\n",
        "from acessilia_core.logger import logger as log\nlog.warning('state: %s', error)\n",
    ],
)
def test_the_guard_finds_printf_calls_through_logger_chains_and_aliases(
    source: str,
) -> None:
    tree = ast.parse(source)
    assert _printf_calls_in(tree, _logger_aliases(tree))


def test_the_guard_ignores_translated_and_preformatted_messages() -> None:
    tree = ast.parse(
        "logger.info(t('state %s').format(error=error))\n"
        "logger.info(f'state {error}')\n"
        "logger.info('state %s' % error)\n"
    )
    assert _printf_calls_in(tree, _logger_aliases(tree)) == []
