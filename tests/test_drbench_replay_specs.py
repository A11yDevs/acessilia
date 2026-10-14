"""Tests for the versioned replay specs.

The frozen replay needs a spec per split. Without a versioned spec the recorded
performance runs cannot be resumed: the selection, the environment lock and the
model revisions would have to be reconstructed by hand.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SPECS_DIR = REPO_ROOT / "scripts" / "drbench" / "experiments" / "eval" / "specs"

EXPECTED_SPECS = ("dev120.spec.json", "dev986.spec.json", "test509.spec.json")


def spec_paths() -> list[Path]:
    return sorted(SPECS_DIR.glob("*.spec.json"))


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class TestSpecsExist:
    def test_all_expected_specs_are_versioned(self):
        names = {p.name for p in spec_paths()}
        for name in EXPECTED_SPECS:
            assert name in names, f"spec ausente: {name}"

    def test_dev120_pages_selection_is_versioned(self):
        assert (SPECS_DIR / "dev120-pages.json").is_file()


class TestSpecShape:
    @pytest.mark.parametrize("path", spec_paths(), ids=lambda p: p.name)
    def test_required_keys(self, path):
        data = load(path)
        for key in ("dataset", "seed", "data_root", "pages", "lockfile",
                    "inference", "models", "evaluator", "variants"):
            assert key in data, f"{path.name}: falta {key}"

    @pytest.mark.parametrize("path", spec_paths(), ids=lambda p: p.name)
    def test_variants_are_baseline_and_candidate(self, path):
        data = load(path)
        assert set(data["variants"]) == {"baseline", "candidate"}
        for variant in data["variants"].values():
            for component in ("acessilia", "toolbox"):
                assert "repo" in variant[component]
                assert "ref" in variant[component]

    @pytest.mark.parametrize("path", spec_paths(), ids=lambda p: p.name)
    def test_every_model_is_pinned_by_revision(self, path):
        data = load(path)
        assert data["models"], f"{path.name}: nenhum modelo declarado"
        for entry in data["models"]:
            assert entry.get("model"), f"{path.name}: modelo sem nome"
            assert entry.get("revision"), (
                f"{path.name}: {entry['model']} sem revisão (não é reproduzível)"
            )

    @pytest.mark.parametrize("path", spec_paths(), ids=lambda p: p.name)
    def test_lockfile_is_declared(self, path):
        assert load(path)["lockfile"].endswith("uv.lock")


class TestSpecPathsResolve:
    @pytest.mark.parametrize("path", spec_paths(), ids=lambda p: p.name)
    def test_lockfile_resolves(self, path):
        data = load(path)
        lock = (path.parent / data["lockfile"]).resolve()
        assert lock.is_file(), f"{path.name}: lockfile não resolve ({lock})"

    @pytest.mark.parametrize("path", spec_paths(), ids=lambda p: p.name)
    def test_pages_resolve_or_declare_a_generator(self, path):
        # O dataset do Dr.DocBench não vive no repositório: um spec pode apontar
        # para um pages.json gerado no workspace, desde que declare o comando.
        data = load(path)
        pages = (path.parent / data["pages"]).resolve()
        if pages.is_file():
            return
        assert data.get("pages_generator"), (
            f"{path.name}: pages ausente e sem pages_generator"
        )
        assert "make_replay_pages.py" in data["pages_generator"]

    def test_dev120_pages_pass_validation(self):
        from scripts.drbench.experiments.eval.frozen_inputs import validate_pages

        pages = json.loads((SPECS_DIR / "dev120-pages.json").read_text(encoding="utf-8"))
        validate_pages(pages)
        assert len(pages) == 120

    def test_dev120_pages_match_the_documented_subset(self):
        documented = json.loads(
            (REPO_ROOT / "docs" / "drbench" / "experiments" / "dev120-subset.json").read_text(
                encoding="utf-8"
            )
        )
        pages = json.loads((SPECS_DIR / "dev120-pages.json").read_text(encoding="utf-8"))
        assert [p["id"] for p in pages] == [p["id"] for p in documented]


class TestMakeReplayPages:
    def test_collects_pages_in_the_replay_format(self, tmp_path):
        from scripts.drbench.experiments.eval.make_replay_pages import collect

        images = tmp_path / "SCIENCE" / "doc1" / "images"
        images.mkdir(parents=True)
        (images / "page_1.jpg").write_bytes(b"x")
        (images / "page_2.jpg").write_bytes(b"x")

        pages = collect(tmp_path, "dev")
        assert [p["id"] for p in pages] == ["doc1_p1", "doc1_p2"]
        assert pages[0]["image"] == "dev/SCIENCE/doc1/images/page_1.jpg"
        assert pages[0]["batch"] == 1

    def test_ignores_non_page_files(self, tmp_path):
        from scripts.drbench.experiments.eval.make_replay_pages import collect

        images = tmp_path / "SCIENCE" / "doc1" / "images"
        images.mkdir(parents=True)
        (images / "page_1.jpg").write_bytes(b"x")
        (images / "cover.jpg").write_bytes(b"x")

        assert [p["id"] for p in collect(tmp_path, "dev")] == ["doc1_p1"]

    def test_output_passes_validation(self, tmp_path):
        from scripts.drbench.experiments.eval.frozen_inputs import validate_pages
        from scripts.drbench.experiments.eval.make_replay_pages import collect

        images = tmp_path / "SCIENCE" / "doc1" / "images"
        images.mkdir(parents=True)
        (images / "page_1.jpg").write_bytes(b"x")

        validate_pages(collect(tmp_path, "dev"))
