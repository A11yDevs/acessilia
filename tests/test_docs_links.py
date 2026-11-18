"""Local links in the repository's Markdown resolve (review of #584).

Renaming a guide (``pmv_agno_pddl.md`` to ``pddl_pipeline.md``) left links to
the old name in documents no test read. This checks every relative link of
every tracked Markdown file, and that current documents no longer name the
renamed PMV files.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: ``"file.md": {"target": "reason"}`` for a link that is broken on purpose.
ALLOWED: dict[str, dict[str, str]] = {
    "docs/adr/template.md": {"NNNN-title.md": "placeholder in the ADR template"},
    "docs/adr/template.pt-br.md": {"NNNN-title.pt-br.md": "placeholder in the ADR template"},
    "docs/drbench/experiments/PLAN.md": {
        "Orientacoes_cluster_dgx_SLURM.pdf": "the cluster's guide is not versioned here",
    },
    "docs/drbench/experiments/summary-dev120.md": {"imgs/…": "placeholder for the run's images"},
}

#: The names the PMV rename replaced. History keeps them.
OLD_NAMES = ("pmv_agno_pddl", "generate_pmv_schemas", "scripts/pmv.py", "scripts.pmv")
HISTORY = ("docs/old/", "docs/plano_incorporacao_pddl_agno")

_LINK = re.compile(r"\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_FENCE = re.compile(r"^(```|~~~).*?^\1", re.S | re.M)
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


def _tracked(pattern: str) -> list[str]:
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--", pattern],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    return sorted(name for name in listed.split("\0") if name and (ROOT / name).exists())


def broken_links(path: str, text: str) -> list[str]:
    """The relative link targets of ``text`` (a file at ``path``) that do not exist."""
    missing = []
    for match in _LINK.finditer(_FENCE.sub("", text)):
        target = match.group(1)
        if target.startswith("#") or _SCHEME.match(target):
            continue
        local = target.split("#", 1)[0]
        if local and not (ROOT / path).parent.joinpath(local).exists():
            missing.append(target)
    return missing


def test_every_local_link_resolves() -> None:
    found = {
        path: broken
        for path in _tracked("*.md")
        if (broken := broken_links(path, (ROOT / path).read_text(encoding="utf-8")))
    }
    unexpected = {
        path: [target for target in targets if target not in ALLOWED.get(path, {})]
        for path, targets in found.items()
    }
    assert not {path: targets for path, targets in unexpected.items() if targets}
    stale = {
        f"{path}: {target}"
        for path, targets in ALLOWED.items()
        for target in targets
        if target not in found.get(path, [])
    }
    assert not stale, f"exceptions nothing needs any more: {sorted(stale)}"


def test_the_checker_finds_a_broken_link() -> None:
    text = (
        "[ok](README.md) [gone](missing.md) [anchor](#top) [web](https://example.org)\n"
        "```\n[fenced](also-missing.md)\n```\n"
    )

    assert broken_links("docs/x.md", text) == ["missing.md"]


def test_current_documents_do_not_name_the_renamed_pmv_files() -> None:
    offenders = [
        f"{path}: {name}"
        for pattern in ("*.md", "*.py", "*.json", "*.yml", "*.toml", "Makefile")
        for path in _tracked(pattern)
        if not path.startswith(HISTORY) and path != "tests/test_docs_links.py"
        for name in OLD_NAMES
        if name in (ROOT / path).read_text(encoding="utf-8", errors="replace")
    ]
    assert not offenders
