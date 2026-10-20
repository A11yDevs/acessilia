"""Regression test: no Portuguese (pt-BR) text in code or documentation.

Exceptions allowed by the constitution (principle 2.8):
- User-facing content: Telegram messages, rendered output, AI prompts
- Domain-specific educational materials where audience is Portuguese-speaking
- Translation catalogs (*.po files, and the pt-BR table in scripts/gen_locale_catalogs.py)
- Portuguese documentation mirrors (*.pt-br.md) and the link to them
- Fixture datasets containing real document content
- Functional detection patterns (callout titles, chapter-heading regex)
  that are language-agnostic classifiers

The scan starts at the repository root and covers libs/ and tests/ (#187). Lines that
predate it are counted per file in ``tests/fixtures/portuguese_allowlist.json``:
no file may go above its count, and a count must be lowered when its file is
cleaned, so the allowlist only shrinks. Add an exemption below only for an
intentional Portuguese string.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST_PATH = REPO_ROOT / "tests" / "fixtures" / "portuguese_allowlist.json"

# ── Exempt paths (entire directories) ──────────────────────────────
EXEMPT_PATHS = {
    # Real document content — not source code.
    REPO_ROOT / "tests" / "fixtures" / "images",
    REPO_ROOT / "tests" / "fixtures" / "presentations",
    REPO_ROOT / "tests" / "fixtures" / "tutorials",
    # Translation catalogs — intentionally in Portuguese.
    REPO_ROOT / "backend" / "locales" / "pt_BR",
}

# ── Exempt files (relative to the repository root) ─────────────────
# Every ``*.pt-br.md`` mirror is exempt as well.
EXEMPT_FILES: set[str] = {
    # English i18n documentation — may reference Portuguese.
    "docs/i18n.md",
    # Translation catalogs and the pt-BR table they are generated from.
    "backend/locales/en_US/LC_MESSAGES/messages.po",
    "backend/locales/pt_BR/LC_MESSAGES/messages.po",
    "scripts/gen_locale_catalogs.py",
    # This guard — it lists the exempt Portuguese strings.
    "tests/test_no_portuguese.py",
}

# Local clone of the separate acessilia-dataset repository (git-ignored):
# real document content, absent in CI.
UNTRACKED_PATHS = {REPO_ROOT / "tests" / "dataset"}

# Substrings exempt in every file: the link from an English page to its
# pt-BR mirror ("[português brasileiro](page.pt-br.md)").
GLOBAL_EXEMPT_STRINGS = ("português brasileiro",)

# ── Known-functional Portuguese strings in source code ─────────────
# Tuple of (relative_file_path, substring). Add new entries here when
# adding intentional detection patterns that match Portuguese words.
EXEMPT_STRINGS: list[tuple[str, str]] = [
    # AI prompts — user-facing content, allowed by constitution
    ("backend/ai/prompts/vision_agent.py", "área"),
    ("backend/ai/prompts/vision_agent.py", "descrição"),
    ("backend/ai/prompts/vision_agent.py", "imagem"),
    ("backend/ai/prompts/vision_agent.py", "texto"),
    ("backend/ai/prompts/vision_agent.py", "tabela"),
    ("backend/ai/prompts/vision_agent.py", "gráfico"),
    ("backend/ai/prompts/vision_agent.py", "fórmula"),
    ("backend/ai/prompts/vision_agent.py", "legenda"),
    ("backend/ai/prompts/vision_agent.py", "rótulo"),
    ("backend/ai/prompts/vision_agent.py", "página"),
    ("backend/ai/prompts/vision_agent.py", "elemento"),
    ("backend/ai/prompts/vision_agent.py", "capítulo"),
    ("backend/ai/prompts/vision_agent.py", "seção"),
    ("backend/ai/prompts/vision_agent.py", "título"),
    ("backend/ai/prompts/vision_agent.py", "conteúdo"),
    ("backend/ai/prompts/vision_agent.py", "estrutura"),
    ("backend/ai/prompts/vision_agent.py", "descrições"),
    ("backend/ai/prompts/vision_agent.py", "imagens"),
    ("backend/ai/prompts/vision_agent.py", "tabelas"),
    ("backend/ai/prompts/vision_agent.py", "gráficos"),
    ("backend/ai/prompts/vision_agent.py", "fórmulas"),
    ("backend/ai/prompts/vision_agent.py", "legendas"),
    ("backend/ai/prompts/vision_agent.py", "rótulos"),
    ("backend/ai/prompts/vision_agent.py", "páginas"),
    ("backend/ai/prompts/vision_agent.py", "elementos"),
    ("backend/ai/prompts/vision_agent.py", "capítulos"),
    ("backend/ai/prompts/vision_agent.py", "seções"),
    ("backend/ai/prompts/vision_agent.py", "títulos"),
    # Data agent prompts — user-facing content
    ("backend/ai/prompts/data_agent.py", "tabela"),
    ("backend/ai/prompts/data_agent.py", "fórmula"),
    ("backend/ai/prompts/data_agent.py", "matemática"),
    ("backend/ai/prompts/data_agent.py", "célula"),
    ("backend/ai/prompts/data_agent.py", "linha"),
    ("backend/ai/prompts/data_agent.py", "coluna"),
    ("backend/ai/prompts/data_agent.py", "conteúdo"),
    ("backend/ai/prompts/data_agent.py", "estrutura"),
    # Editor agent prompts — user-facing content
    ("backend/ai/prompts/editor_agent.py", "conteúdo"),
    ("backend/ai/prompts/editor_agent.py", "descrição"),
    ("backend/ai/prompts/editor_agent.py", "elemento"),
    ("backend/ai/prompts/editor_agent.py", "texto"),
    ("backend/ai/prompts/editor_agent.py", "seção"),
    ("backend/ai/prompts/editor_agent.py", "parágrafo"),
    ("backend/ai/prompts/editor_agent.py", "tabela"),
    ("backend/ai/prompts/editor_agent.py", "legenda"),
    ("backend/ai/prompts/editor_agent.py", "imagem"),
    ("backend/ai/prompts/editor_agent.py", "gráfico"),
    ("backend/ai/prompts/editor_agent.py", "fórmula"),
    ("backend/ai/prompts/editor_agent.py", "referência"),
    # Telegram messages — user-facing content
    ("frontend/telegram/messages.py", "área"),
    ("frontend/telegram/messages.py", "descrição"),
    ("frontend/telegram/messages.py", "imagem"),
    ("frontend/telegram/messages.py", "texto"),
    ("frontend/telegram/messages.py", "tabela"),
    ("frontend/telegram/messages.py", "gráfico"),
    ("frontend/telegram/messages.py", "fórmula"),
    ("frontend/telegram/messages.py", "legenda"),
    ("frontend/telegram/messages.py", "página"),
    ("frontend/telegram/messages.py", "elemento"),
    ("frontend/telegram/messages.py", "capítulo"),
    ("frontend/telegram/messages.py", "seção"),
    ("frontend/telegram/messages.py", "título"),
    ("frontend/telegram/messages.py", "conteúdo"),
    ("frontend/telegram/messages.py", "estrutura"),
    ("frontend/telegram/messages.py", "processamento"),
    ("frontend/telegram/messages.py", "documento"),
    ("frontend/telegram/messages.py", "arquivo"),
    ("frontend/telegram/messages.py", "formato"),
    ("frontend/telegram/messages.py", "idioma"),
    ("frontend/telegram/messages.py", "tradução"),
    ("frontend/telegram/messages.py", "configuração"),
    ("frontend/telegram/messages.py", "comando"),
    ("frontend/telegram/messages.py", "ajuda"),
    ("frontend/telegram/messages.py", "idioma"),
    ("frontend/telegram/messages.py", "locale"),
    # Web messages — user-facing content
    ("frontend/web/messages.py", "descrição"),
    ("frontend/web/messages.py", "imagem"),
    ("frontend/web/messages.py", "texto"),
    ("frontend/web/messages.py", "tabela"),
    ("frontend/web/messages.py", "gráfico"),
    ("frontend/web/messages.py", "fórmula"),
    ("frontend/web/messages.py", "legenda"),
    ("frontend/web/messages.py", "página"),
    ("frontend/web/messages.py", "elemento"),
    ("frontend/web/messages.py", "conteúdo"),
    ("frontend/web/messages.py", "processamento"),
    ("frontend/web/messages.py", "documento"),
    ("frontend/web/messages.py", "arquivo"),
    ("frontend/web/messages.py", "formato"),
    ("frontend/web/messages.py", "idioma"),
    ("frontend/web/messages.py", "tradução"),
    ("frontend/web/messages.py", "configuração"),
    # Stage messages — user-facing pipeline stage names
    ("backend/stage_messages.py", "descrição"),
    ("backend/stage_messages.py", "imagem"),
    ("backend/stage_messages.py", "texto"),
    ("backend/stage_messages.py", "tabela"),
    ("backend/stage_messages.py", "gráfico"),
    ("backend/stage_messages.py", "fórmula"),
    ("backend/stage_messages.py", "legenda"),
    ("backend/stage_messages.py", "página"),
    ("backend/stage_messages.py", "elemento"),
    ("backend/stage_messages.py", "conteúdo"),
    ("backend/stage_messages.py", "processamento"),
    ("backend/stage_messages.py", "documento"),
    ("backend/stage_messages.py", "arquivo"),
    ("backend/stage_messages.py", "extração"),
    ("backend/stage_messages.py", "estrutura"),
    ("backend/stage_messages.py", "validação"),
    ("backend/stage_messages.py", "exportação"),
    ("backend/stage_messages.py", "renderização"),
    ("backend/stage_messages.py", "geração"),
    ("backend/stage_messages.py", "conversão"),
    ("backend/stage_messages.py", "preparação"),
    ("backend/stage_messages.py", "divisão"),
    # Log messages — may reference Portuguese user-facing concepts
    ("backend/log_messages.py", "descrição"),
    ("backend/log_messages.py", "imagem"),
    ("backend/log_messages.py", "texto"),
    ("backend/log_messages.py", "tabela"),
    ("backend/log_messages.py", "gráfico"),
    ("backend/log_messages.py", "fórmula"),
    ("backend/log_messages.py", "legenda"),
    ("backend/log_messages.py", "página"),
    ("backend/log_messages.py", "elemento"),
    ("backend/log_messages.py", "conteúdo"),
    ("backend/log_messages.py", "processamento"),
    ("backend/log_messages.py", "documento"),
    ("backend/log_messages.py", "arquivo"),
    ("backend/log_messages.py", "formato"),
    ("backend/log_messages.py", "extração"),
    ("backend/log_messages.py", "estrutura"),
    ("backend/log_messages.py", "validação"),
    ("backend/log_messages.py", "exportação"),
    ("backend/log_messages.py", "conversão"),
    ("backend/log_messages.py", "preparação"),
    ("backend/log_messages.py", "divisão"),
    ("backend/log_messages.py", "cache"),
    ("backend/log_messages.py", "fila"),
    ("backend/log_messages.py", "histórico"),
    ("backend/log_messages.py", "configuração"),
    # Schema descriptions — canonical names
    ("schemas/accessible_document.schema.json", "Acessilia"),
    ("schemas/execution_report.schema.json", "Acessilia"),
    ("schemas/nominal_plan.schema.json", "Acessilia"),
    ("schemas/planning_comparison.schema.json", "Acessilia"),
    ("schemas/processing_manifest.schema.json", "Acessilia"),
]

# Build the exempt set from strings so we can check quickly.
_EXEMPT_BY_FILE: dict[str, set[str]] = {}
for file_rel, substring in EXEMPT_STRINGS:
    _EXEMPT_BY_FILE.setdefault(file_rel, set()).add(substring)


#: Source, docs and config files the guard reads, relative to the repository root.
SCAN_PATTERNS = (
    "backend/**/*.py",
    "frontend/**/*.py",
    "libs/**/*.py",
    "libs/**/*.md",
    "libs/*/pyproject.toml",
    "docs/**/*.md",
    "schemas/*.json",
    "pyproject.toml",
    "infra/Dockerfile",
    ".env.example",
    "README.md",
    "CONTRIBUTING.md",
    ".github/**/*.yml",
    ".github/**/*.md",
    "docker-compose*.yml",
    "scripts/**/*.sh",
    "scripts/**/*.py",
    "tests/**/*.py",
    "tests/**/*.md",
)
_SKIPPED_PARTS = {"__pycache__", ".venv", "node_modules", "build"}

# Patterns that match a Portuguese (accented) character.
_PORTUGUESE_RE = re.compile(r"[áàâãéèêíìóòôõúùûç]")


def _iter_project_files(root: Path) -> list[Path]:
    """Walk source, docs and config files (skip exempt paths and caches)."""
    files: set[Path] = set()
    for pattern in SCAN_PATTERNS:
        for path in root.glob(pattern):
            if _SKIPPED_PARTS.intersection(path.parts):
                continue
            if any(path.is_relative_to(exempt) for exempt in EXEMPT_PATHS | UNTRACKED_PATHS):
                continue
            files.add(path)
    return sorted(files)


def _portuguese_lines(root: Path = REPO_ROOT) -> dict[str, list[str]]:
    """Offending lines per file, relative to ``root``, after every exemption."""
    found: dict[str, list[str]] = {}
    for filepath in _iter_project_files(root):
        rel = filepath.relative_to(root).as_posix()
        if rel in EXEMPT_FILES or rel.endswith(".pt-br.md"):
            continue
        exempt = _EXEMPT_BY_FILE.get(rel, set()) | set(GLOBAL_EXEMPT_STRINGS)
        try:
            text = filepath.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped or not _PORTUGUESE_RE.search(stripped):
                continue
            if any(substring in stripped for substring in exempt):
                continue
            found.setdefault(rel, []).append(f"{rel}:{lineno}: {stripped[:100]}")
    return found


def _allowlist() -> dict[str, int]:
    return json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))["files"]


@pytest.fixture(scope="session")
def portuguese_lines() -> dict[str, list[str]]:
    return _portuguese_lines()


def test_the_scan_covers_the_whole_repository() -> None:
    """The guard once read only tests/ (#187); it must reach every component."""
    files = _iter_project_files(REPO_ROOT)
    scanned = {path.relative_to(REPO_ROOT).parts[0] for path in files}
    assert {"backend", "frontend", "libs", "docs", "scripts", "tests"} <= scanned
    # Files without a source suffix are read too, and none is exempt whole.
    for name in (".env.example", "infra/Dockerfile", "README.md"):
        assert REPO_ROOT / name in files
        assert name not in EXEMPT_FILES


def test_no_new_portuguese(portuguese_lines: dict[str, list[str]]) -> None:
    """No file may hold more Portuguese lines than the allowlist records.

    A file absent from the allowlist may hold none. If the text is
    intentional (user-facing content, a detection pattern), add an exemption
    to ``EXEMPT_STRINGS`` instead of raising the count.
    """
    allowed = _allowlist()
    failures = [
        f"{rel}: {len(lines)} line(s), {allowed.get(rel, 0)} allowed\n  "
        + "\n  ".join(lines)
        for rel, lines in sorted(portuguese_lines.items())
        if len(lines) > allowed.get(rel, 0)
    ]
    assert not failures, "Portuguese text above the allowlist:\n" + "\n".join(failures)


def test_the_allowlist_only_shrinks(portuguese_lines: dict[str, list[str]]) -> None:
    """A count above what the file holds must be lowered, so it never comes back."""
    stale = {
        rel: (allowed, len(portuguese_lines.get(rel, [])))
        for rel, allowed in _allowlist().items()
        if len(portuguese_lines.get(rel, [])) < allowed
    }
    assert not stale, (
        "Lower these counts in tests/fixtures/portuguese_allowlist.json "
        "(remove the entry at 0): "
        + ", ".join(f"{rel} {old} -> {new}" for rel, (old, new) in sorted(stale.items()))
    )


def test_exempt_paths_still_exist() -> None:
    """Fail early if an exempt path is renamed or deleted."""
    for path in EXEMPT_PATHS:
        assert path.exists(), f"Exempt path {path} no longer exists"
    for rel in EXEMPT_FILES:
        assert (REPO_ROOT / rel).exists(), f"Exempt file {rel} no longer exists"
