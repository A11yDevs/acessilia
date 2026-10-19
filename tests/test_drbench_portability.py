"""Tests for the Dr.DocBench experiment workspace portability.

The experiment scripts were written against a fixed DGX workspace
(`/raid/user_marcospaulo/drdocbench`). They must be relocatable: every path that
points at the workspace has to be overridable through an environment variable,
so the recorded jobs stay reproducible while another cluster can run them.
"""
from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SLURM_DIR = REPO_ROOT / "scripts" / "drbench" / "experiments" / "slurm"

HISTORICAL_WS = "/raid/user_marcospaulo/drdocbench"

# Um caminho absoluto do workspace é aceitável apenas como default de uma
# expansão `${VAR:-...}` ou dentro de `os.environ.get(...)`.
PARAMETERISED = re.compile(
    r"\$\{[A-Z_]+:-[^}]*\}|os\.environ\.get\([^)]*\)|^\s*#"
)


def _sbatch_files() -> list[Path]:
    return sorted(SLURM_DIR.glob("*.sbatch"))


def _shell_files() -> list[Path]:
    return sorted(SLURM_DIR.glob("*.sh"))


def _unparameterised_lines(path: Path) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if HISTORICAL_WS not in line:
            continue
        if PARAMETERISED.search(line):
            continue
        out.append((n, line.strip()))
    return out


class TestSbatchPortability:
    def test_no_sbatch_hardcodes_the_workspace(self):
        offenders = {
            p.name: _unparameterised_lines(p)
            for p in _sbatch_files()
            if _unparameterised_lines(p)
        }
        assert not offenders, f"caminhos não parametrizados: {offenders}"

    def test_every_sbatch_sources_env_sh_through_ws(self):
        # Duas formas aceitáveis: `source "$WS/..."` (WS exportado pelo
        # submissor) ou `source "${WS:-<default>}/..."` (default histórico).
        for path in _sbatch_files():
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.lstrip().startswith("source "):
                    continue
                if "env.sh" not in line:
                    continue
                assert '"$WS/' in line or '"${WS:-' in line, (
                    f"{path.name} não parametriza o source: {line.strip()}"
                )

    def test_sbatch_output_is_relative(self):
        # Slurm não expande variáveis de shell em diretivas #SBATCH.
        for path in _sbatch_files():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("#SBATCH --output="):
                    target = line.split("=", 1)[1]
                    assert not target.startswith("/"), (
                        f"{path.name}: #SBATCH --output absoluto ({target})"
                    )

    def test_sbatch_files_are_syntactically_valid(self):
        import subprocess

        for path in _sbatch_files():
            result = subprocess.run(
                ["bash", "-n", str(path)], capture_output=True, text=True
            )
            assert result.returncode == 0, f"{path.name}: {result.stderr}"


class TestShellHelperPortability:
    def test_env_sh_parameterises_every_path(self):
        text = (SLURM_DIR / "env.sh").read_text(encoding="utf-8")
        for line in text.splitlines():
            if HISTORICAL_WS in line and not line.lstrip().startswith("#"):
                assert "${" in line, f"env.sh não parametriza: {line.strip()}"

    def test_cdm_env_parameterises_every_path(self):
        text = (SLURM_DIR / "cdm_env.sh").read_text(encoding="utf-8")
        for line in text.splitlines():
            if "/raid/user_marcospaulo" in line and not line.lstrip().startswith("#"):
                assert "${" in line, f"cdm_env.sh não parametriza: {line.strip()}"

    def test_shell_helpers_are_syntactically_valid(self):
        import subprocess

        for path in _shell_files():
            result = subprocess.run(
                ["bash", "-n", str(path)], capture_output=True, text=True
            )
            assert result.returncode == 0, f"{path.name}: {result.stderr}"


class TestPythonHelperPortability:
    def test_python_helpers_read_roots_from_the_environment(self):
        helpers = {
            "eval/loop_score.py": "DRBENCH_FULL",
            "loop/agent2/fastscore.py": "DRBENCH_WS",
            "loop/agent2/support_filter.py": "DRBENCH_FULL",
        }
        for rel, var in helpers.items():
            text = (REPO_ROOT / "scripts" / "drbench" / "experiments" / rel).read_text(
                encoding="utf-8"
            )
            assert var in text, f"{rel} não lê {var} do ambiente"
