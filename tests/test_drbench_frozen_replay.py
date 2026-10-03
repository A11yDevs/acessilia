"""Protect experiment identity, coverage and isolation using temporary Git repos."""
import json
import subprocess
from pathlib import Path

import pytest

from scripts.drbench.experiments.eval.frozen_inputs import (
    export_revision, freeze, sha256, validate_pages,
)


def page(number=1):
    return {"id": f"doc_p{number}", "subject": "SCIENCE", "document_id": "doc",
            "page": number, "batch": 1, "image": f"dev/SCIENCE/doc/images/page_{number}.jpg"}


def repository(path):
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    (path / "version.txt").write_text("committed")
    subprocess.run(["git", "-C", str(path), "add", "version.txt"], check=True)
    subprocess.run(["git", "-C", str(path), "-c", "user.name=Test",
                    "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"], check=True)
    return path


@pytest.fixture
def spec(tmp_path):
    repo = repository(tmp_path / "repo")
    data = tmp_path / "data"
    for relative in ("raw/docling/doc_p1.json", "raw/mineru/doc_p1.json",
                     "data/hf/dev/SCIENCE/doc/images/page_1.jpg",
                     "data/hf/dev/SCIENCE/doc/mds/doc_1.md"):
        file = data / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("fixture")
    selection = tmp_path / "pages.json"
    selection.write_text(json.dumps([page()]))
    source = {"repo": str(repo), "ref": "HEAD"}
    variant = {"acessilia": source, "toolbox": source, "policy": "v12"}
    path = tmp_path / "spec.json"
    path.write_text(json.dumps({"data_root": str(data), "pages": str(selection),
                               "evaluator": source,
                               "variants": {"baseline": variant, "candidate": variant}}))
    return path


def test_export_uses_commit_not_dirty_or_untracked_files(tmp_path):
    repo = repository(tmp_path / "repo")
    (repo / "version.txt").write_text("dirty")
    (repo / "private.txt").write_text("untracked")
    metadata = export_revision(repo, "HEAD", tmp_path / "snapshot")
    assert (tmp_path / "snapshot/version.txt").read_text() == "committed"
    assert not (tmp_path / "snapshot/private.txt").exists()
    assert metadata["working_tree_included"] is False


def test_frozen_inputs_survive_mutation_of_originals(spec, tmp_path):
    out = tmp_path / "run"
    metadata = freeze(spec, out)
    original = tmp_path / "data/raw/docling/doc_p1.json"
    original.write_text("changed")
    frozen = out / "raw/docling/doc_p1.json"
    assert frozen.read_text() == "fixture"
    assert sha256(frozen) == metadata["input_hashes"]["raw/docling/doc_p1.json"]
    assert metadata["status"] == "frozen"


def test_existing_run_is_never_overwritten(spec, tmp_path):
    out = tmp_path / "run"
    freeze(spec, out)
    with pytest.raises(FileExistsError):
        freeze(spec, out)


def test_missing_raw_marks_run_failed(spec, tmp_path):
    (tmp_path / "data/raw/mineru/doc_p1.json").unlink()
    out = tmp_path / "run"
    with pytest.raises(FileNotFoundError):
        freeze(spec, out)
    assert json.loads((out / "manifest.json").read_text())["status"] == "freeze_failed"


def test_output_inside_repository_is_rejected(spec, tmp_path):
    with pytest.raises(ValueError, match="outside source"):
        freeze(spec, tmp_path / "repo/run")
    assert not (tmp_path / "repo/run").exists()


@pytest.mark.parametrize("pages", [[], [page(), page()], [dict(page(), image="../private")]])
def test_selection_cannot_be_empty_duplicate_or_escape_data_root(pages):
    with pytest.raises(ValueError):
        validate_pages(pages)
