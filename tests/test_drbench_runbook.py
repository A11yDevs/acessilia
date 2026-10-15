"""Tests for the reproduction runbook.

The runbook is the single entry point for resuming the performance work. It must
stay consistent with the code it documents: the commands it shows have to exist,
the specs it lists have to be versioned, and the English source and the
Portuguese mirror have to stay in sync (constitution rule 8).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS = REPO_ROOT / "docs" / "drbench" / "experiments"
RUNBOOK = DOCS / "RUNBOOK.md"
RUNBOOK_PT = DOCS / "RUNBOOK.pt-br.md"
SPECS = REPO_ROOT / "scripts" / "drbench" / "experiments" / "eval" / "specs"


@pytest.fixture(scope="module")
def runbook() -> str:
    return RUNBOOK.read_text(encoding="utf-8")


class TestRunbookExists:
    def test_english_source_exists(self):
        assert RUNBOOK.is_file()

    def test_portuguese_mirror_exists(self):
        assert RUNBOOK_PT.is_file()

    def test_language_links_are_bidirectional(self, runbook):
        assert "RUNBOOK.pt-br.md" in runbook
        assert "RUNBOOK.md" in RUNBOOK_PT.read_text(encoding="utf-8")


class TestRunbookCommandsExist:
    def test_referenced_scripts_exist(self, runbook):
        for script in (
            "scripts/drbench/experiments/eval/frozen_replay.py",
            "scripts/drbench/experiments/eval/make_replay_pages.py",
        ):
            assert script in runbook, f"runbook não menciona {script}"
            assert (REPO_ROOT / script).is_file(), f"{script} não existe"

    def test_referenced_docs_exist(self, runbook):
        for doc in (
            "scripts/drbench/experiments/eval/FROZEN_REPLAY.md",
            "scripts/drbench/experiments/README.md",
            "docs/drbench/experiments/SERVICES-LOOP.md",
            "docs/drbench/experiments/LOOP.md",
            "docs/drbench/experiments/SUBMISSIONS-LEADERBOARD.md",
        ):
            assert doc in runbook, f"runbook não menciona {doc}"
            assert (REPO_ROOT / doc).is_file(), f"{doc} não existe"

    def test_referenced_sbatch_jobs_exist(self, runbook):
        jobs = set(re.findall(r"`([a-z_0-9]+\.sbatch)`", runbook))
        assert jobs, "runbook não menciona nenhum sbatch"
        slurm = REPO_ROOT / "scripts" / "drbench" / "experiments" / "slurm"
        for job in jobs:
            assert (slurm / job).is_file(), f"{job} não existe"

    def test_referenced_specs_exist(self, runbook):
        for spec in re.findall(r"`(dev\d+\.spec\.json|test\d+\.spec\.json)`", runbook):
            assert (SPECS / spec).is_file(), f"spec {spec} não existe"

    def test_lockfile_is_referenced_and_exists(self, runbook):
        assert "uv.lock" in runbook
        assert (REPO_ROOT / "uv.lock").is_file()

    def test_results_artifact_is_referenced_and_exists(self, runbook):
        assert "RESULTS.json" in runbook
        assert (DOCS / "RESULTS.json").is_file()


class TestRunbookContent:
    def test_states_what_is_deterministic(self, runbook):
        assert "Deterministic?" in runbook
        assert "Needs GPU?" in runbook

    def test_states_the_replay_does_not_rerun_ocr(self, runbook):
        assert "never runs OCR again" in runbook

    def test_states_the_dev_to_test_gap(self, runbook):
        assert "~8 points" in runbook

    def test_states_the_teds_non_transfer(self, runbook):
        assert "TEDS did not transfer" in runbook

    def test_states_the_holdout_criteria(self, runbook):
        assert "Δtune" in runbook and "Δhold" in runbook

    def test_lists_gpu_costs(self, runbook):
        assert "GPU cost" in runbook
        assert "h100n2" in runbook

    def test_mentions_the_expected_pre_existing_failures(self, runbook):
        assert "pre-existing failures" in runbook


class TestRunbookMirrorIsInSync:
    def test_mirror_covers_the_same_sections(self):
        en = re.findall(r"^## (.+)$", RUNBOOK.read_text(encoding="utf-8"), re.M)
        pt = re.findall(r"^## (.+)$", RUNBOOK_PT.read_text(encoding="utf-8"), re.M)
        assert len(en) == len(pt), f"seções divergentes: {len(en)} EN vs {len(pt)} pt-BR"

    def test_mirror_references_the_same_scripts(self):
        en = RUNBOOK.read_text(encoding="utf-8")
        pt = RUNBOOK_PT.read_text(encoding="utf-8")
        for script in re.findall(r"scripts/drbench/[\w/]+\.py", en):
            assert script in pt, f"espelho pt-BR não menciona {script}"

    def test_mirror_references_the_same_sbatch_jobs(self):
        en = set(re.findall(r"`([a-z_0-9]+\.sbatch)`", RUNBOOK.read_text(encoding="utf-8")))
        pt = set(re.findall(r"`([a-z_0-9]+\.sbatch)`", RUNBOOK_PT.read_text(encoding="utf-8")))
        assert en == pt, f"jobs divergentes: {en ^ pt}"
