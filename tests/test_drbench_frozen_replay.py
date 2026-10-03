"""Protect experiment identity, coverage and isolation using temporary Git repos."""
import json
import subprocess
from pathlib import Path

import pytest

from scripts.drbench.experiments.eval.frozen_inputs import (
    export_revision, freeze, sha256, validate_pages,
)
from scripts.drbench.experiments.eval.frozen_replay import (
    check_sources, evaluate, verify_inputs, verify_sources,
)
from scripts.drbench.experiments.eval.replay_report import (
    METRICS, check_inventory, metric_score, summarize,
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


def test_changed_frozen_input_is_detected(spec, tmp_path):
    root = tmp_path / "run"
    manifest = freeze(spec, root)
    (root / "raw/docling/doc_p1.json").write_text("tampered")
    with pytest.raises(ValueError, match="input changed"):
        verify_inputs(root, manifest)


def test_missing_and_stale_predictions_are_failures(tmp_path):
    with pytest.raises(ValueError, match="coverage mismatch"):
        check_inventory(tmp_path, [page()])
    (tmp_path / "doc_p1.drbench.md").write_text("ok")
    check_inventory(tmp_path, [page()])
    (tmp_path / "doc_p2.drbench.md").write_text("stale")
    with pytest.raises(ValueError, match="coverage mismatch"):
        check_inventory(tmp_path, [page()])


def result_row(a=80.0, b=80.0):
    row = {"id": "doc_p1"}
    for metric in METRICS:
        row.update({f"baseline_{metric}": a, f"candidate_{metric}": b,
                    f"delta_{metric}": b-a if a is not None and b is not None else None})
    return row


def test_identical_scores_pass_and_keep_paired_denominator():
    summary = summarize([result_row()])
    assert summary["quality_gate"] == "passed"
    assert summary["metrics"]["reading_order"]["delta"] == 0
    assert summary["metrics"]["reading_order"]["equal"] == 1


def test_text_loss_rejects_even_with_reading_order_gain():
    row = result_row(80, 85)
    row.update(baseline_text_block=80, candidate_text_block=79, delta_text_block=-1)
    summary = summarize([row])
    assert summary["quality_gate"] == "rejected"
    assert summary["metrics"]["text_block"]["regressions"] == [{"id": "doc_p1", "delta": -1}]


def test_asymmetric_coverage_is_rejected():
    row = result_row()
    row.update(candidate_text_block=None, delta_text_block=None)
    summary = summarize([result_row(), row])
    assert summary["quality_gate"] == "rejected"
    assert summary["metrics"]["text_block"]["coverage_mismatch"] == ["doc_p1"]


def test_zero_evaluated_pairs_is_inconclusive():
    assert summarize([result_row(None, None)])["quality_gate"] == "inconclusive"


def test_no_samples_is_distinct_from_missing_evaluator_output(tmp_path):
    with pytest.raises(FileNotFoundError):
        metric_score(tmp_path, "batch-01", "reading_order", page())
    (tmp_path / "batch-01_reading_order_result.json").write_text("[]")
    assert metric_score(tmp_path, "batch-01", "reading_order", page()) == (None, "no_official_samples")


def test_nonempty_samples_require_an_official_metric(tmp_path):
    (tmp_path / "batch-01_reading_order_result.json").write_text(json.dumps([{"img_id": "doc_page_1-1.jpg"}]))
    with pytest.raises(FileNotFoundError):
        metric_score(tmp_path, "batch-01", "reading_order", page())
    (tmp_path / "batch-01_reading_order_per_page_edit.json").write_text('{"doc_page_1-1.jpg": 0.25}')
    assert metric_score(tmp_path, "batch-01", "reading_order", page()) == (75, "evaluated")


@pytest.mark.parametrize("default,flags,expected", [(0.0, [], 0.0), (None, [], 0.3),
                                                    (None, ["--garbage-frac", "0.7"], 0.7)])
def test_actual_cli_defaults_and_override_are_recorded(tmp_path, monkeypatch, default, flags, expected):
    import argparse
    from types import SimpleNamespace
    from scripts.drbench.experiments import differ
    from scripts.drbench.experiments.eval.replay_worker import run_fusion

    def main():
        parser = argparse.ArgumentParser()
        for option in ("docling", "mineru", "out"):
            parser.add_argument(f"--{option}", type=Path, required=True)
        parser.add_argument("--policy")
        parser.add_argument("--garbage-frac", type=float, default=default)
        parser.parse_args()

    cli = SimpleNamespace(main=main, policy_by_name=lambda _: SimpleNamespace(to_dict=lambda: {"garbage_frac": 0.3}))
    monkeypatch.setattr(differ, "lib_fuse", cli, raising=False)
    (tmp_path / "baseline").mkdir()
    (tmp_path / "manifest.json").write_text(json.dumps({"variants": {"baseline": {"policy": "v12", "fusion_args": flags}}}))
    run_fusion(tmp_path, "baseline")
    config = json.loads((tmp_path / "baseline/fusion-config.json").read_text())
    assert config["resolved_fusion_args"]["garbage_frac"] == (float(flags[1]) if flags else default)
    assert config["resolved_policy"]["garbage_frac"] == expected


def test_generated_translation_catalogue_is_recorded_but_new_code_is_rejected(tmp_path):
    source = tmp_path / "sources/baseline/acessilia/translations/en_US"
    source.mkdir(parents=True)
    (source / "messages.po").write_text("versioned translation")
    before = verify_sources(tmp_path)
    (source / "messages.mo").write_bytes(b"compiled catalogue")
    generated = check_sources(tmp_path, before)
    assert list(generated) == ["sources/baseline/acessilia/translations/en_US/messages.mo"]
    (source / "orphan.mo").write_bytes(b"no versioned source catalogue")
    with pytest.raises(ValueError, match="Unexpected file"):
        check_sources(tmp_path, before)
    (source / "orphan.mo").unlink()
    (source / "unexpected.py").write_text("new code")
    with pytest.raises(ValueError, match="Unexpected file"):
        check_sources(tmp_path, before)


def test_modified_versioned_source_is_rejected(tmp_path):
    source = tmp_path / "sources/source.py"
    source.parent.mkdir()
    source.write_text("original")
    before = verify_sources(tmp_path)
    source.write_text("modified")
    with pytest.raises(ValueError, match="source changed"):
        check_sources(tmp_path, before)


def test_source_mutation_between_freeze_and_run_fails_before_any_command(spec, tmp_path):
    root = tmp_path / "run"
    freeze(spec, root)
    (root / "sources/baseline/acessilia/version.txt").write_text("changed after freeze")
    with pytest.raises(ValueError, match="before evaluation"):
        evaluate(root)
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["status"] == "failed"
    assert manifest["commands"] == []


@pytest.mark.parametrize("option", ["docling_native_order", "mineru_native_order"])
def test_normalization_mode_is_frozen_and_does_not_default_to_native(spec, tmp_path, option):
    data = json.loads(spec.read_text())
    data["variants"]["candidate"] = {**data["variants"]["candidate"], option: True}
    spec.write_text(json.dumps(data))
    frozen = freeze(spec, tmp_path / "native-run")
    assert frozen["variants"]["baseline"][option] is False
    assert frozen["variants"]["candidate"][option] is True


@pytest.mark.parametrize("option", ["docling_native_order", "mineru_native_order"])
def test_non_boolean_normalization_mode_fails_before_creating_run(spec, tmp_path, option):
    data = json.loads(spec.read_text())
    data["variants"]["candidate"][option] = "false"
    spec.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="must be a boolean"):
        freeze(spec, tmp_path / "invalid-mode")
    assert not (tmp_path / "invalid-mode").exists()
