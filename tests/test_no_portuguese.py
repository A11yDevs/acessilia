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
    REPO_ROOT / "libs" / "core" / "src" / "acessilia_core" / "i18n" / "locales" / "pt_BR",
    # The vision prompts, written in Portuguese for the model. They were not
    # scanned under backend/ (no *.md pattern there); libs/**/*.md reaches
    # them since the core moved to libs/core (ADR-0016, step 6).
    REPO_ROOT / "libs" / "core" / "src" / "acessilia_core" / "agents" / "prompts",
    # The PDDL domain descriptions, package data whose hash is part of the
    # domain's identity (DomainBundle.description_sha256): same reason.
    REPO_ROOT / "libs" / "core" / "src" / "acessilia_core" / "planning" / "domains",
}

# ── Exempt files (relative to the repository root) ─────────────────
# Every ``*.pt-br.md`` mirror is exempt as well.
EXEMPT_FILES: set[str] = {
    # English i18n documentation — may reference Portuguese.
    "docs/i18n.md",
    # Translation catalogs and the pt-BR table they are generated from.
    "libs/core/src/acessilia_core/i18n/locales/en_US/LC_MESSAGES/messages.po",
    "libs/core/src/acessilia_core/i18n/locales/pt_BR/LC_MESSAGES/messages.po",
    "scripts/gen_locale_catalogs.py",
    # This guard — it lists the exempt Portuguese strings.
    "tests/test_no_portuguese.py",
    # The #410 tests assert the pt-BR step messages verbatim; the text is the
    # expected user-facing output, not source prose.
    "tests/test_pddl_messages_i18n.py",
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
    # Vision retry instruction — an AI prompt, in the language of the region prompts
    ("libs/core/src/acessilia_core/agents/vision_agent.py", "Responda com um objeto JSON completo e válido"),
    ("libs/core/src/acessilia_core/agents/vision_agent.py", "Não repita tokens nem preencha campos"),
    # Vision schema instruction — an AI prompt, allowed by constitution
    ("libs/core/src/acessilia_core/agents/output_schemas.py", "molécula é kind='description'"),
    # Vision, page-inspection and data schema instructions — AI prompts, moved
    # with output_schemas.py out of the allowlist (ADR-0016, step 2)
    ("libs/core/src/acessilia_core/agents/output_schemas.py", "description para conteúdo visual/textual"),
    ("libs/core/src/acessilia_core/agents/output_schemas.py", "quando a região for predominantemente"),
    ("libs/core/src/acessilia_core/agents/output_schemas.py", "O extrator estrutural não encontrou"),
    ("libs/core/src/acessilia_core/agents/output_schemas.py", "tem conteúdo. Use kind='blank'"),
    ("libs/core/src/acessilia_core/agents/output_schemas.py", "ruído de digitalização"),
    ("libs/core/src/acessilia_core/agents/output_schemas.py", "contrário, use kind='content'"),
    ("libs/core/src/acessilia_core/agents/output_schemas.py", "descreva os elementos visuais"),
    ("libs/core/src/acessilia_core/agents/output_schemas.py", "para tabelas, incluindo caption"),
    ("libs/core/src/acessilia_core/agents/output_schemas.py", "latex para fórmulas"),
    # Page prompt and its fallback — AI prompts, moved with prompt_tools.py out
    # of the allowlist (ADR-0016, step 2)
    ("libs/core/src/acessilia_core/agents/prompt_tools.py", "Você é um sistema de acessibilidade digital"),
    ("libs/core/src/acessilia_core/agents/prompt_tools.py", "forneça a audiodescrição entre colchetes"),
    ("libs/core/src/acessilia_core/agents/prompt_tools.py", "Preserve a ênfase do texto original"),
    ("libs/core/src/acessilia_core/agents/prompt_tools.py", "Para MATEMÁTICA: linearize fórmulas"),
    ("libs/core/src/acessilia_core/agents/prompt_tools.py", "Se um parágrafo termina com hífen"),
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
    # Spoken-formula label — user-facing, the core prepends it in alt text and plain-text exports
    ("libs/core/src/acessilia_core/formula_tools.py", "Fórmula:"),

    # Stage messages — user-facing pipeline stage names
    ("libs/core/src/acessilia_core/i18n/stage_messages.py", "descrição"),
    ("libs/core/src/acessilia_core/i18n/stage_messages.py", "imagem"),
    ("libs/core/src/acessilia_core/i18n/stage_messages.py", "texto"),
    ("libs/core/src/acessilia_core/i18n/stage_messages.py", "tabela"),
    ("libs/core/src/acessilia_core/i18n/stage_messages.py", "gráfico"),
    ("libs/core/src/acessilia_core/i18n/stage_messages.py", "fórmula"),
    ("libs/core/src/acessilia_core/i18n/stage_messages.py", "legenda"),
    ("libs/core/src/acessilia_core/i18n/stage_messages.py", "página"),
    ("libs/core/src/acessilia_core/i18n/stage_messages.py", "elemento"),
    ("libs/core/src/acessilia_core/i18n/stage_messages.py", "conteúdo"),
    ("libs/core/src/acessilia_core/i18n/stage_messages.py", "processamento"),
    ("libs/core/src/acessilia_core/i18n/stage_messages.py", "documento"),
    ("libs/core/src/acessilia_core/i18n/stage_messages.py", "arquivo"),
    ("libs/core/src/acessilia_core/i18n/stage_messages.py", "extração"),
    ("libs/core/src/acessilia_core/i18n/stage_messages.py", "estrutura"),
    ("libs/core/src/acessilia_core/i18n/stage_messages.py", "validação"),
    ("libs/core/src/acessilia_core/i18n/stage_messages.py", "exportação"),
    ("libs/core/src/acessilia_core/i18n/stage_messages.py", "renderização"),
    ("libs/core/src/acessilia_core/i18n/stage_messages.py", "geração"),
    ("libs/core/src/acessilia_core/i18n/stage_messages.py", "conversão"),
    ("libs/core/src/acessilia_core/i18n/stage_messages.py", "preparação"),
    ("libs/core/src/acessilia_core/i18n/stage_messages.py", "divisão"),
    # Log messages — may reference Portuguese user-facing concepts
    ("libs/core/src/acessilia_core/i18n/log_messages.py", "descrição"),
    ("libs/core/src/acessilia_core/i18n/log_messages.py", "imagem"),
    ("libs/core/src/acessilia_core/i18n/log_messages.py", "texto"),
    ("libs/core/src/acessilia_core/i18n/log_messages.py", "tabela"),
    ("libs/core/src/acessilia_core/i18n/log_messages.py", "gráfico"),
    ("libs/core/src/acessilia_core/i18n/log_messages.py", "fórmula"),
    ("libs/core/src/acessilia_core/i18n/log_messages.py", "legenda"),
    ("libs/core/src/acessilia_core/i18n/log_messages.py", "página"),
    ("libs/core/src/acessilia_core/i18n/log_messages.py", "elemento"),
    ("libs/core/src/acessilia_core/i18n/log_messages.py", "conteúdo"),
    ("libs/core/src/acessilia_core/i18n/log_messages.py", "processamento"),
    ("libs/core/src/acessilia_core/i18n/log_messages.py", "documento"),
    ("libs/core/src/acessilia_core/i18n/log_messages.py", "arquivo"),
    ("libs/core/src/acessilia_core/i18n/log_messages.py", "formato"),
    ("libs/core/src/acessilia_core/i18n/log_messages.py", "extração"),
    ("libs/core/src/acessilia_core/i18n/log_messages.py", "estrutura"),
    ("libs/core/src/acessilia_core/i18n/log_messages.py", "validação"),
    ("libs/core/src/acessilia_core/i18n/log_messages.py", "exportação"),
    ("libs/core/src/acessilia_core/i18n/log_messages.py", "conversão"),
    ("libs/core/src/acessilia_core/i18n/log_messages.py", "preparação"),
    ("libs/core/src/acessilia_core/i18n/log_messages.py", "divisão"),
    ("libs/core/src/acessilia_core/i18n/log_messages.py", "cache"),
    ("libs/core/src/acessilia_core/i18n/log_messages.py", "fila"),
    ("libs/core/src/acessilia_core/i18n/log_messages.py", "histórico"),
    ("libs/core/src/acessilia_core/i18n/log_messages.py", "configuração"),
    # Schema descriptions — canonical names
    ("schemas/accessible_document.schema.json", "Acessilia"),
    ("schemas/execution_report.schema.json", "Acessilia"),
    ("schemas/nominal_plan.schema.json", "Acessilia"),
    ("schemas/planning_comparison.schema.json", "Acessilia"),
    ("schemas/processing_manifest.schema.json", "Acessilia"),
    # Non-ASCII fixtures exercise HTTP header rejection and Unicode URL encoding.
    ("tests/test_n05_n09_n10_regressions.py", '"inválido".encode()'),
    ("libs/sdk/tests/clients/test_dataset.py", '"input/álgebra.pdf"'),
    # The heading of the Brazilian Portuguese README whose table it reads (ADR-0018).
    ("libs/sdk/tests/test_public_api.py", "## API pública"),
    # Legacy Unicode repair — user-facing execution messages and observations
    ("libs/core/src/acessilia_core/pipeline/payload.py", "Texto com sinais de Unicode legado"),
    ("libs/core/src/acessilia_core/manifest/builder.py", "Texto extraído de PDF legado contém Unicode"),
    # Text-layer formula agreement — Portuguese function names (máx, mín) that
    # pt-BR material prints, matched as a detection pattern
    ("libs/docstruct/src/docstruct/text/latex.py", "máx"),
    ("libs/docstruct/tests/test_latex.py", "máx"),
    # Legacy TeX repair — the Portuguese crase (à) is what the grave-crase
    # rule produces, so its code, docs and tests carry it
    ("libs/docstruct/src/docstruct/text/unicode_repair.py", "à"),
    ("libs/docstruct/tests/test_unicode_repair.py", "à"),
    ("tests/test_legacy_unicode_repair.py", "à medida"),
    ("docs/docstruct_algorithms.md", "→ `à`"),
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


def test_exempt_strings_name_existing_files() -> None:
    """A string exemption bound to a missing file exempts nothing; remove it.

    48 entries named prompt modules that never existed until ADR-0016's
    step 2 removed them; this keeps the list honest, like the allowlist.
    """
    missing = sorted({rel for rel, _ in EXEMPT_STRINGS if not (REPO_ROOT / rel).is_file()})
    assert not missing, f"EXEMPT_STRINGS entries for files that do not exist: {missing}"
