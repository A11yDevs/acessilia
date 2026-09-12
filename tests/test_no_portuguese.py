"""Regression test: no Portuguese (pt-BR) text in code or documentation.

Exceptions allowed by the constitution (principle 8):
- User-facing content: Telegram messages, rendered output, AI prompts
- Domain-specific educational materials where audience is Portuguese-speaking
- Translation catalogs (*.po files in backend/locales/pt_BR/)
- Portuguese documentation files (*.pt-br.md)
- Fixture datasets containing real document content
- Functional detection patterns (callout titles, chapter-heading regex)
  that are language-agnostic classifiers

Add new exemptions here when adding intentional Portuguese detection patterns.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent

# ── Exempt paths (entire directories) ──────────────────────────────
EXEMPT_PATHS = {
    # Real document content — not source code.
    PROJECT_ROOT / "fixtures" / "images",
    PROJECT_ROOT / "fixtures" / "presentations",
    PROJECT_ROOT / "fixtures" / "tutorials",
    # Translation catalogs — intentionally in Portuguese.
    PROJECT_ROOT.parent / "backend" / "locales" / "pt_BR",
}

# ── Exempt files (by relative path) ────────────────────────────────
# Files with known fixture or generated content that may contain Portuguese.
EXEMPT_FILES: set[str] = {
    # Portuguese documentation — allowed by constitution.
    "CONTRIBUTING.pt-br.md",
    "README.pt-br.md",
    "docs/README.pt-br.md",
    "docs/architecture.pt-br.md",
    "docs/constitution.pt-br.md",
    "docs/docker-compose.pt-br.md",
    "docs/endpoints.pt-br.md",
    "docs/homologacao-systemd.pt-br.md",
    "docs/i18n.pt-br.md",
    "docs/old/MVP_CHANGES.pt-br.md",
    "docs/old/PMV_2_1_CHANGES.pt-br.md",
    "docs/old/PMV_2_CHANGES.pt-br.md",
    "docs/patterns.pt-br.md",
    "docs/plano_incorporacao_pddl_agno.pt-br.md",
    "docs/pmv_agno_pddl.pt-br.md",
    "docs/pr-14-review.pt-br.md",
    "docs/use_cases.pt-br.md",
    "tests/README.pt-br.md",
    # English i18n documentation — may reference Portuguese.
    "docs/i18n.md",
    # Translation catalogs.
    "backend/locales/en_US/LC_MESSAGES/messages.po",
    "backend/locales/pt_BR/LC_MESSAGES/messages.po",
    # Test documentation — may reference Portuguese concepts.
    "README.md",
}

# ── Known-functional Portuguese strings in source code ─────────────
# Tuple of (relative_file_path, substring). Add new entries here when
# adding intentional detection patterns that match Portuguese words.
EXEMPT_STRINGS: list[tuple[str, str]] = [
    # Callout detection — multi-language set (Portuguese)
    ("backend/pipeline/structure_parser.py", "nota"),
    ("backend/pipeline/structure_parser.py", "aviso"),
    ("backend/pipeline/structure_parser.py", "dica"),
    ("backend/pipeline/structure_parser.py", "importante"),
    # Callout detection — warning types set
    ("backend/pipeline/structure_parser.py", "warning_types"),
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


def _iter_project_files(root: Path) -> list[Path]:
    """Walk source, docs and config files (skip exempt and __pycache__)."""
    files: list[Path] = []
    for pattern in (
        "backend/**/*.py",
        "frontend/**/*.py",
        "docs/**/*.md",
        "schemas/*.json",
        "pyproject.toml",
        "Dockerfile",
        "infra/Dockerfile",
        ".env.example",
        "README.md",
        "CONTRIBUTING.md",
        ".github/workflows/*.yml",
        "docker-compose*.yml",
        "scripts/*.sh",
        "scripts/*.py",
    ):
        found = list(root.glob(pattern))
        for p in found:
            rel = p.relative_to(root)
            if any(rel.is_relative_to(ex) for ex in EXEMPT_PATHS):
                continue
            if "__pycache__" in p.parts:
                continue
            files.append(p)
    return files


# Patterns that match a Portuguese (accented) character.
# Only check .py, .md, .json, .yaml, .toml files for accented strings.
_PORTUGUESE_RE = pytest.importorskip("re").compile(r"[áàâãéèêíìóòôõúùûç]")


@pytest.fixture(scope="session")
def project_files() -> list[Path]:
    return _iter_project_files(PROJECT_ROOT)


def test_no_portuguese_in_code(project_files: list[Path]) -> None:
    """No source file should contain accented Portuguese strings,
    except known exemptions in EXEMPT_STRINGS and EXEMPT_FILES."""
    failures: list[str] = []
    for filepath in project_files:
        if filepath.suffix not in {".py", ".md", ".json", ".yaml", ".yml", ".toml"}:
            continue
        if filepath.name == "pyproject.toml" and filepath.parent == PROJECT_ROOT:
            continue

        rel = str(filepath.relative_to(PROJECT_ROOT))
        if rel in EXEMPT_FILES:
            continue
        exempt_lines = _EXEMPT_BY_FILE.get(rel, set())

        try:
            text = filepath.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        for lineno, line in enumerate(text.splitlines(), start=1):
            line_stripped = line.strip()
            if not line_stripped:
                continue
            match = _PORTUGUESE_RE.search(line_stripped)
            if not match:
                continue
            # Check if this line contains an exempt substring
            if any(exempt in line_stripped for exempt in exempt_lines):
                continue
            failures.append(f"  {rel}:{lineno}: {line_stripped[:100]}")

    if failures:
        fail_msg = (
            f"Found {len(failures)} line(s) with Portuguese text.\n"
            "If intentional, add an entry to EXEMPT_STRINGS in this test file.\n"
            + "\n".join(failures)
        )
        pytest.fail(fail_msg)


def test_exempt_paths_still_exist() -> None:
    """Fail early if an exempt path is renamed or deleted."""
    for path in EXEMPT_PATHS:
        assert path.exists(), f"Exempt path {path} no longer exists"
    for rel in EXEMPT_FILES:
        path = PROJECT_ROOT.parent / rel
        assert path.exists(), f"Exempt file {rel} no longer exists"