import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from docstruct.evaluation.holdout import partition
from scripts.bench import __main__ as cli
from scripts.bench import core
from scripts.bench.datasets import BenchPage
from scripts.bench.datasets.drdocbench import DrDocBench
from scripts.bench.report import (
    _coverage_pair_issues,
    _identity_pair_issues,
    _read_windows,
    compare_run_report,
    score_run,
)
from scripts.bench.run_manifest import (
    STRUCTURE_PROTOCOL,
    _dataset_revision,
    completed_artifacts_are_valid,
    digest,
    load_run_manifest,
    lock_run_directory,
    selection_snapshot,
)

DOC = "0a1b2c3d-0000-4000-8000-000000000001"


def _tree(root, pages=(1, 2), gt=True):
    for n in pages:
        base = root / "MATH" / DOC
        (base / "images").mkdir(parents=True, exist_ok=True)
        (base / "images" / f"page_{n}.jpg").write_bytes(b"jpg")
        if gt:
            (base / "mds").mkdir(exist_ok=True)
            (base / "mds" / f"{DOC}_{n}.md").write_text(f"# Page {n}\n\nBody {n}\n", encoding="utf-8")


def test_manifest_elements_map_to_canonical_blocks():
    elements = [
        {"type": "paragraph", "text": "$x^2$", "reading_order": 3},
        {"type": "title", "text": "Title", "reading_order": 1},
        {"type": "picture", "text": "ignored", "reading_order": 2},
        {"type": "formula", "text": "$$ a  +  b $$", "reading_order": 4},
        {"type": "table", "text": "", "reading_order": 5,
         "metadata": {"table_ast": {"body": [{"cells": [{"text": "1"}]}]}}},
    ]
    assert core.elements_to_canonical_blocks(elements) == [
        {"type": "heading", "level": 1, "text": "Title"},
        {"type": "math", "text": "x^2"},
        {"type": "math", "text": "a + b"},
        {"type": "table", "html": "<table><tr><td>1</td></tr></table>"},
    ]


def test_payload_without_heading_has_no_synthetic_title():
    result = {"document": {"elements": [{"type": "paragraph", "text": "Only text"}]}}
    assert core.payload_to_canonical(result)["title"] == ""


def test_provider_blocks_carry_bbox_and_page_size():
    result = {"document": {
        "pages": [{"page_number": 1, "size": {"width": 100, "height": 200}}],
        "elements": [{"id": "e1", "type": "Text", "text": "t", "reading_order": 0,
                      "provenance": [{"page_number": 1, "bbox": {
                          "left": 1, "top": 2, "right": 3, "bottom": 4, "coord_origin": "TOPLEFT"}}]}],
    }}
    [block] = core.provider_blocks(result)
    assert block["bbox"] == [1, 2, 3, 4]
    assert block["page_size"] == [100, 200]
    assert block["type"] == "text"


def test_drdocbench_reads_both_layouts(tmp_path):
    _tree(tmp_path)
    flat = tmp_path / "SCI" / "doc9"
    flat.mkdir(parents=True)
    (flat / "page_3.jpg").write_bytes(b"jpg")

    pages = DrDocBench().pages(tmp_path)

    assert [p.item_id for p in pages] == [f"{DOC}_p1", f"{DOC}_p2", "doc9_p3"]
    assert pages[0].meta == {"subject": "MATH"} and pages[0].gt_path.name == f"{DOC}_1.md"
    assert pages[2].gt_path is None and pages[2].meta == {"subject": "SCI"}


def test_submission_requires_every_page(tmp_path):
    _tree(tmp_path / "data")
    pages = DrDocBench().pages(tmp_path / "data")
    preds = tmp_path / "preds"
    preds.mkdir()
    (preds / f"{DOC}_p1.md").write_text("one", encoding="utf-8")
    with pytest.raises(SystemExit):
        DrDocBench().build_submission(pages, preds, tmp_path / "out")

    (preds / f"{DOC}_p2.md").write_text("two", encoding="utf-8")
    zip_path = DrDocBench().build_submission(pages, preds, tmp_path / "out")

    rows = [json.loads(line) for line in
            zipfile.ZipFile(zip_path).read("predictions.jsonl").decode().splitlines()]
    assert rows[0] == {"subject": "MATH", "document_id": DOC, "page": 1, "markdown": "one"}


def test_submit_blocks_run_until_zip_is_written(tmp_path, monkeypatch, capsys):
    root = tmp_path / "data"
    _tree(root)
    run_dir = _stub_toolbox(tmp_path, monkeypatch)
    args = ["--dataset", "drdocbench", "--root", str(root)]
    assert cli.main(["run", *args]) == 0
    zip_path = run_dir / "submission" / "submission.zip"

    with lock_run_directory(run_dir):
        assert cli.main(["submit", *args]) == 1
    assert "Run is already in use" in capsys.readouterr().err
    assert not zip_path.exists()

    read_text = Path.read_text
    write_entry = zipfile.ZipFile.writestr

    def read_prediction(path, *read_args, **read_kwargs):
        result = read_text(path, *read_args, **read_kwargs)
        if path == run_dir / "predictions" / f"{DOC}_p1.md":
            assert cli.main(["run", *args]) == 1
            assert "Run is already in use" in capsys.readouterr().err
        return result

    def write_prediction_entry(archive, *write_args, **write_kwargs):
        assert cli.main(["run", *args]) == 1
        assert "Run is already in use" in capsys.readouterr().err
        return write_entry(archive, *write_args, **write_kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_text", read_prediction)
        patch.setattr(zipfile.ZipFile, "writestr", write_prediction_entry)
        assert cli.main(["submit", *args]) == 0

    with zipfile.ZipFile(zip_path) as submission:
        rows = [json.loads(line) for line in submission.read("predictions.jsonl").splitlines()]
    assert [row["page"] for row in rows] == [1, 2]
    assert [row["markdown"] for row in rows] == [
        read_text(run_dir / "predictions" / f"{DOC}_p{page}.md", encoding="utf-8")
        for page in (1, 2)
    ]
    assert cli.main(["run", *args]) == 0


def test_score_counts_missing_prediction_as_miss_and_compare_runs(tmp_path):
    _tree(tmp_path / "data")
    pages = DrDocBench().pages(tmp_path / "data")
    preds = tmp_path / "preds"
    preds.mkdir()
    (preds / f"{DOC}_p1.md").write_text("# Page 1\n\nBody 1\n", encoding="utf-8")

    base_run = tmp_path / "base"
    base_run.mkdir()
    (base_run / "comparison.json").write_text("stale", encoding="utf-8")
    report = score_run(pages, preds, base_run)

    assert report["pages"] == 2
    assert not (base_run / "comparison.json").exists()
    rows = [json.loads(line) for line in (tmp_path / "base" / "pages.jsonl").read_text().splitlines()]
    assert rows[0]["text"] == pytest.approx(100.0)
    assert rows[1]["text"] == pytest.approx(0.0)
    assert (tmp_path / "base" / "drilldown.csv").read_text().splitlines()[1].startswith(f"{DOC}_p2,")

    (preds / f"{DOC}_p2.md").write_text("# Page 2\n\nBody 2\n", encoding="utf-8")
    score_run(pages, preds, tmp_path / "candidate")
    comparison = compare_run_report(tmp_path / "base", tmp_path / "candidate")
    assert not comparison["verdict"]["accepted"]
    assert not comparison["measurement"]["gate_applied"]
    subset = partition(f"{DOC}_page_1")
    assert comparison["diagnostic_metric_deltas"]["text"][subset] == pytest.approx(50.0)


def test_cli_run_writes_markdown_and_blocks(tmp_path, monkeypatch):
    _tree(tmp_path / "data", pages=(1,))
    monkeypatch.setattr(cli, "VAR", tmp_path / "var")
    monkeypatch.setattr(cli.toolbox, "extract_structure", lambda image, provider: {
        "document": {"elements": [{"type": "title", "text": "Page 1", "reading_order": 0},
                                  {"type": "text", "text": "Body 1", "reading_order": 1}]},
        "provenance": {"provider": "docling", "provider_version": "1", "duration_ms": 21,
                       "cache_hit": True, "model_versions": {"layout": "model-v1"},
                       "cache_key": "do-not-persist"}})

    assert cli.main(["run", "--dataset", "drdocbench", "--root", str(tmp_path / "data")]) == 0
    assert cli.main(["score", "--dataset", "drdocbench", "--root", str(tmp_path / "data")]) == 0

    run = tmp_path / "var" / "drdocbench" / "dev" / "latest"
    assert (run / "predictions" / f"{DOC}_p1.md").read_text() == "# Page 1\n\nBody 1\n"
    assert (run / "predictions" / f"{DOC}_p1.blocks.json").exists()
    assert json.loads((run / "report.json").read_text())["overall"] == pytest.approx(100.0)
    manifest = json.loads((run / "run-manifest.json").read_text())
    call = manifest["items"][f"{DOC}_p1"]["observed_calls"][0]
    assert call["toolbox_provenance"]["cache_hit"] is True
    assert call["toolbox_provenance"]["duration_ms"] == 21
    assert call["toolbox_provenance"]["model_versions"] == {"layout": "model-v1"}
    assert "cache_key" not in call["toolbox_provenance"]
    assert manifest["evaluation"]["gate"]["kind"] == "improvement"


def test_official_tree_uses_one_page_windows(tmp_path):
    _tree(tmp_path / "data")
    pages = DrDocBench().pages(tmp_path / "data")
    preds = tmp_path / "preds"
    preds.mkdir()
    (preds / f"{DOC}_p2.md").write_text("two", encoding="utf-8")

    assert DrDocBench().build_official_tree(pages, preds, tmp_path / "official") == 1
    assert (tmp_path / "official" / "MATH" / f"{DOC}_page_2-2.md").read_text() == "two"


def test_cli_resume_skips_existing_predictions(tmp_path, monkeypatch):
    _tree(tmp_path / "data")
    monkeypatch.setenv("BENCH_VAR", str(tmp_path / "var"))
    monkeypatch.setattr(cli, "VAR", tmp_path / "var")
    preds = tmp_path / "var" / "drdocbench" / "dev" / "latest" / "predictions"
    preds.mkdir(parents=True)
    (preds / f"{DOC}_p1.md").write_text("kept", encoding="utf-8")
    for name in ("report.json", "pages.jsonl", "drilldown.csv", "comparison.json"):
        (preds.parent / name).write_text("stale", encoding="utf-8")
    seen = []
    monkeypatch.setattr(cli.toolbox, "extract_structure",
                        lambda image, provider: seen.append(image.name) or {"document": {"elements": []}})

    assert cli.main(["run", "--dataset", "drdocbench", "--root", str(tmp_path / "data"), "--resume"]) == 1
    assert seen == ["page_2.jpg"]
    assert (preds / f"{DOC}_p1.md").read_text() == "kept"
    # Resuming keeps the run covering both pages, not only the resumed ones.
    manifest = (preds.parent / "pages.txt").read_text().split()
    assert manifest == [f"{DOC}_p1", f"{DOC}_p2"]
    run_manifest = json.loads((preds.parent / "run-manifest.json").read_text())
    assert run_manifest["status"] == "partial"
    assert run_manifest["items"][f"{DOC}_p1"]["status"] == "legacy_unverified"
    assert all(not (preds.parent / name).exists() for name in (
        "report.json", "pages.jsonl", "drilldown.csv", "comparison.json"
    ))

    # A legacy-only no-op remains partial and must not return success.
    assert cli.main(["run", "--dataset", "drdocbench", "--root", str(tmp_path / "data"), "--resume"]) == 1
    assert seen == ["page_2.jpg"]


def test_cli_rejects_concurrent_run_and_score_before_touching_artifacts(tmp_path, monkeypatch):
    root = tmp_path / "data"
    _tree(root, pages=(1,))
    run = _stub_toolbox(tmp_path, monkeypatch)
    data = ["--dataset", "drdocbench", "--root", str(root)]
    write_bytes = cli.atomic_write_bytes
    child_cli = """
from scripts.bench import __main__ as cli
cli.toolbox.extract_structure = lambda *args: {
    "document": {"elements": [{"type": "text", "text": "Other process"}]}
}
raise SystemExit(cli.main())
"""

    def try_competing_processes(path, payload):
        write_bytes(path, payload)
        if path.suffix != ".md":
            return
        for command in (["run", "--resume"], ["run"], ["score"]):
            result = subprocess.run(
                [sys.executable, "-c", child_cli, *command, *data],
                env={**os.environ, "BENCH_VAR": str(cli.VAR)},
                capture_output=True,
                text=True,
                timeout=15,
            )
            assert result.returncode == 1, result.stdout + result.stderr
            assert "Run is already in use" in result.stderr
        assert not (run / "report.json").exists()

    monkeypatch.setattr(cli, "atomic_write_bytes", try_competing_processes)
    assert cli.main(["run", "--resume", *data]) == 0

    manifest = load_run_manifest(run)
    assert manifest["status"] == "completed"
    item_id = f"{DOC}_p1"
    assert completed_artifacts_are_valid(
        run / "predictions", manifest["items"][item_id], item_id, require_raw_payload=False
    )
    assert cli.main(["run", "--resume", *data]) == 0
    assert cli.main(["score", *data]) == 0


def test_cli_resume_completed_verified_run_returns_success(tmp_path, monkeypatch):
    _tree(tmp_path / "data", pages=(1,))
    run = _stub_toolbox(tmp_path, monkeypatch)
    data = [
        "--dataset", "drdocbench", "--root", str(tmp_path / "data"),
        "--dataset-revision", "a" * 40,
    ]
    seen = []
    monkeypatch.setattr(cli.toolbox, "extract_structure", lambda image, provider: seen.append(image.name) or {
        "document": {"elements": []}
    })

    assert cli.main(["run", *data]) == 0
    assert cli.main(["run", *data, "--resume"]) == 0
    assert seen == ["page_1.jpg"]
    saved = json.loads((run / "run-manifest.json").read_text())
    assert saved["status"] == "completed"
    assert saved["dataset"]["revision"] == "a" * 40
    assert saved["dataset"]["revision_source"] == "explicit"


@pytest.mark.parametrize("change", ["route", "provider", "provider_version", "model_versions"])
def test_cli_resume_rejects_toolbox_changes_and_can_retry(tmp_path, monkeypatch, change):
    root = tmp_path / "data"
    _tree(root)
    run = _stub_toolbox(tmp_path, monkeypatch)
    data = ["--dataset", "drdocbench", "--root", str(root)]
    run_args = ["run", *data, "--dataset-revision", "a" * 40]
    monkeypatch.delenv("TOOLBOX_BASE_URLS", raising=False)
    monkeypatch.setenv("TOOLBOX_BASE_URL", "https://toolbox.example/blue-private-route")
    provenance = {"provider": "docling", "provider_version": "v1", "model_versions": {"layout": "v1"}}
    calls = []
    second_page_fails = True

    def extract(image, provider):
        calls.append(image.name)
        if second_page_fails and image.name == "page_2.jpg":
            raise TimeoutError
        return {"document": {"elements": []}, "provenance": dict(provenance)}

    monkeypatch.setattr(cli.toolbox, "extract_structure", extract)
    assert cli.main(run_args) == 1
    manifest_path = run / "run-manifest.json"
    initial_manifest = manifest_path.read_text()
    assert "blue-private-route" not in initial_manifest
    assert json.loads(initial_manifest)["configuration"]["endpoints"] == ["https://toolbox.example"]
    second_page_fails = False
    original_provenance = dict(provenance)
    if change == "route":
        monkeypatch.setenv("TOOLBOX_BASE_URL", "https://toolbox.example/green-private-route")
    else:
        provenance[change] = {
            "provider": "other", "provider_version": "v2", "model_versions": {"layout": "v2"},
        }[change]

    calls.clear()
    assert cli.main([*run_args, "--resume"]) == 1
    assert not (run / "predictions" / f"{DOC}_p2.md").exists()
    if change == "route":
        assert calls == []
        assert manifest_path.read_text() == initial_manifest
    else:
        assert calls == ["page_2.jpg"]
        saved = json.loads(manifest_path.read_text())
        assert saved["status"] == "partial"
        assert saved["items"][f"{DOC}_p2"]["last_error_type"] == "ToolboxProvenanceMismatch"
    assert cli.main(["score", *data]) == 0
    assert not compare_run_report(run, run)["measurement"]["gate_applied"]

    monkeypatch.setenv("TOOLBOX_BASE_URL", "https://toolbox.example/blue-private-route/")
    provenance.update(original_provenance, cache_hit=True, duration_ms=123)
    calls.clear()
    assert cli.main([*run_args, "--resume"]) == 0
    assert calls == ["page_2.jpg"]


def test_slurm_resume_reuses_pages_across_ports_for_same_deployment(tmp_path, monkeypatch):
    root = tmp_path / "data"
    _tree(root)
    run = _stub_toolbox(tmp_path, monkeypatch)
    args = ["run", "--dataset", "drdocbench", "--root", str(root), "--resume",
            "--dataset-revision", "a" * 40]
    monkeypatch.delenv("TOOLBOX_BASE_URLS", raising=False)
    monkeypatch.setenv("TOOLBOX_BASE_URL", "http://localhost:8012")
    monkeypatch.setenv("BENCH_SLURM_TOOLBOX_SHA256", "b" * 64)
    calls = []

    def extract(image, provider):
        calls.append(image.name)
        if image.name == "page_2.jpg" and len(calls) == 2:
            raise TimeoutError
        return {"document": {"elements": []}}

    monkeypatch.setattr(cli.toolbox, "extract_structure", extract)
    assert cli.main(args) == 1
    assert calls == ["page_1.jpg", "page_2.jpg"]
    monkeypatch.setenv("TOOLBOX_BASE_URL", "http://localhost:8022")
    monkeypatch.setenv("BENCH_SLURM_TOOLBOX_SHA256", "c" * 64)
    assert cli.main(args) == 1
    assert calls == ["page_1.jpg", "page_2.jpg"]

    monkeypatch.setenv("BENCH_SLURM_TOOLBOX_SHA256", "b" * 64)
    assert cli.main(args) == 0
    assert calls == ["page_1.jpg", "page_2.jpg", "page_2.jpg"]
    assert json.loads((run / "run-manifest.json").read_text())["status"] == "completed"


def test_cli_run_rejects_input_changed_during_extraction(tmp_path, monkeypatch):
    _tree(tmp_path / "data", pages=(1,))
    monkeypatch.setattr(cli, "VAR", tmp_path / "var")
    def mutate_input(image, provider):
        image.write_bytes(b"changed")
        return {"document": {"elements": []}}

    monkeypatch.setattr(cli.toolbox, "extract_structure", mutate_input)

    assert cli.main([
        "run", "--dataset", "drdocbench", "--root", str(tmp_path / "data"),
        "--dataset-revision", "a" * 40,
    ]) == 1
    run = tmp_path / "var" / "drdocbench" / "dev" / "latest"
    manifest = json.loads((run / "run-manifest.json").read_text())
    assert manifest["status"] == "failed"
    assert manifest["items"][f"{DOC}_p1"]["last_error_type"] == "RuntimeError"
    assert not (run / "predictions" / f"{DOC}_p1.md").exists()


def test_selection_records_input_representation_and_transform_boundary(tmp_path):
    _tree(tmp_path / "data", pages=(1,))
    [page] = DrDocBench().pages(tmp_path / "data")

    selection = selection_snapshot([page])

    assert selection["items"][0]["input_representation"] == {
        "media_type": "image/jpeg",
        "media_type_source": "filename_extension",
        "size_bytes": 3,
    }
    assert selection["items"][0]["reference_representation"]["media_type"] == "text/markdown"
    assert STRUCTURE_PROTOCOL["input_representation"] == {
        "unit": "one dataset page image",
        "core_transform": "none",
        "crop": "not_applicable",
        "toolbox_internal_transform": "not_observed",
    }


def test_comparison_rejects_unknown_dataset_revision():
    run = {"dataset": {"name": "drdocbench", "split": "dev", "revision": None}}

    issues = _identity_pair_issues(run, run)

    assert "base dataset revision is unavailable" in issues
    assert "candidate dataset revision is unavailable" in issues


def test_comparison_rejects_mutable_dataset_revision_names():
    run = {
        "dataset": {
            "name": "drdocbench",
            "split": "dev",
            "revision": "main",
            "revision_source": "explicit",
        }
    }

    issues = _identity_pair_issues(run, run)

    assert "base dataset revision is unavailable" in issues
    assert "candidate dataset revision is unavailable" in issues


def test_dataset_revision_does_not_use_an_ancestor_repository_commit():
    nested_data = Path(__file__).resolve().parents[1] / "tests"

    assert _dataset_revision(nested_data) is None


def test_comparison_rejects_malformed_coverage_without_crashing():
    malformed = {
        "coverage": {
            "expected_item_ids": [{}],
            "expected_reference_item_ids": [],
            "scored_reference_item_ids": [],
            "scorable_by_metric": {
                "text": {"item_ids": [{}], "expected": 0, "scorable": 0},
            },
        },
        "measurement": {},
    }

    issues = _coverage_pair_issues(malformed, malformed, [], [])

    assert any("expected item ids is invalid" in issue for issue in issues)
    assert any("text score rows do not match recorded coverage" in issue for issue in issues)


def test_compare_rows_reject_boolean_page_numbers(tmp_path):
    (tmp_path / "pages.jsonl").write_text(
        json.dumps({"item_id": "item", "document_id": "doc", "page": True}) + "\n"
    )

    _windows, rows, issues = _read_windows(tmp_path)

    assert rows == []
    assert "pages.jsonl has an invalid row at line 1" in issues[0]


def _stub_toolbox(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "VAR", tmp_path / "var")
    monkeypatch.setattr(cli.toolbox, "extract_structure", lambda image, provider: {
        "document": {"elements": [{"type": "text", "text": "Body", "reading_order": 0}]}})
    return tmp_path / "var" / "drdocbench" / "dev" / "latest"


def test_score_covers_only_the_pages_of_the_run(tmp_path, monkeypatch):
    _tree(tmp_path / "data", pages=(1, 2, 3))
    run = _stub_toolbox(tmp_path, monkeypatch)
    data = ["--dataset", "drdocbench", "--root", str(tmp_path / "data")]

    assert cli.main(["run", *data]) == 0
    assert cli.main(["run", *data, "--sample", "1"]) == 0
    assert cli.main(["score", *data]) == 0

    assert sorted(p.name for p in (run / "predictions").glob("*.md")) == [f"{DOC}_p1.md"]
    assert json.loads((run / "report.json").read_text())["pages"] == 1


def test_score_without_ground_truth_fails(tmp_path, monkeypatch):
    _tree(tmp_path / "data", pages=(1,), gt=False)
    _stub_toolbox(tmp_path, monkeypatch)
    data = ["--dataset", "drdocbench", "--root", str(tmp_path / "data")]

    assert cli.main(["run", *data]) == 0
    assert cli.main(["score", *data]) == 1


def test_compare_prints_strict_json(tmp_path, capsys):
    for name in ("base", "candidate"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "pages.jsonl").write_text(json.dumps(
            {"document_id": "doc", "page": 1, "text": 90.0, "reading_order": None, "teds": None}) + "\n")

    cli.main(["compare", str(tmp_path / "base"), str(tmp_path / "candidate")])

    out = json.loads(capsys.readouterr().out, parse_constant=lambda c: pytest.fail(f"non-JSON {c}"))
    assert out["metric_deltas"] == {}
    assert out["tune_delta"] is None and out["holdout_delta"] is None


def test_compare_blocks_run_and_score_until_report_is_published(tmp_path, monkeypatch, capsys):
    root = tmp_path / "data"
    _tree(root, pages=(1,))
    candidate = _stub_toolbox(tmp_path, monkeypatch)
    base = candidate.with_name("base")
    data = ["--dataset", "drdocbench", "--root", str(root)]
    run_args = [*data, "--dataset-revision", "a" * 40]
    for run in (base, candidate):
        assert cli.main(["run", *run_args, "--run", run.name]) == 0
        assert cli.main(["score", *data, "--run", run.name]) == 0
    compare = ["compare", str(base), str(candidate)]
    comparison_path = candidate / "comparison.json"
    capsys.readouterr()

    with lock_run_directory(candidate):
        assert cli.main(compare) == 1
    assert "Run is already in use" in capsys.readouterr().err
    assert not comparison_path.exists()

    write_json = cli.atomic_write_json

    def try_replacing_runs_before_write(path, report):
        assert path == comparison_path
        assert report["compatibility"]["compatible"]
        for run in (base, candidate):
            for command, args in (("run", run_args), ("score", data)):
                assert cli.main([command, *args, "--run", run.name]) == 1
                assert "Run is already in use" in capsys.readouterr().err
            assert (run / "report.json").exists()
        write_json(path, report)

    with monkeypatch.context() as patch:
        patch.setattr(cli, "atomic_write_json", try_replacing_runs_before_write)
        assert cli.main(compare) == 1  # Identical predictions do not pass the improvement gate.
    assert json.loads(comparison_path.read_text())["compatibility"]["compatible"]

    # Once comparison has published, a fresh run can replace and invalidate its artifacts.
    assert cli.main(["run", *run_args]) == 0
    assert not comparison_path.exists()


def test_comparison_applies_gate_only_to_matching_verified_scores(tmp_path, monkeypatch):
    doc_ids = [next(str(i) for i in range(20) if partition(f"{i}_page_1") == subset)
               for subset in ("tune", "hold")]
    pages = []
    for doc_id in doc_ids:
        image = tmp_path / f"{doc_id}.jpg"
        image.write_bytes(b"input")
        reference = tmp_path / f"{doc_id}.md"
        reference.write_text("correct text\n\n$$x$$\n\n$$y$$\n")
        pages.append(BenchPage(doc_id, doc_id, 1, image, reference))

    base = tmp_path / "base"
    candidate = tmp_path / "candidate"

    def extract(image, provider):
        elements = [{"type": "text", "text": "incorrect baseline" if provider == "base"
                     else "correct text", "reading_order": 0},
                    {"type": "formula", "text": "x", "reading_order": 1},
                    {"type": "formula", "text": "y" if provider == "base" else "z",
                     "reading_order": 2}]
        return {"document": {"elements": elements}, "provenance": {"provider_version": "v1"}}

    monkeypatch.setattr(cli.toolbox, "extract_structure", extract)

    def unexpected_math_configuration():
        pytest.fail("structure-only conversion consulted the remote math configuration")

    monkeypatch.setattr(core, "core_config_from_settings", unexpected_math_configuration)
    for run in (base, candidate):
        assert cli._run(pages, run, run.name, False, dataset="drdocbench", split="dev",
                        root=tmp_path, dataset_revision="a" * 40) == 0
        score_run(pages, run / "predictions", run)

    report = compare_run_report(base, candidate)
    assert report["measurement"]["gate_applied"]
    assert report["verdict"]["accepted"], report["verdict"]
    assert report["diagnostic_metric_deltas"]["cdm"]["tune"] == pytest.approx(-50.0)
    assert "tune_cdm" not in report["verdict"]["metric_deltas"]

    prediction = candidate / "predictions" / f"{pages[0].item_id}.md"
    original = prediction.read_bytes()
    prediction.write_text("substituted\n")
    score_run(pages, candidate / "predictions", candidate)
    prediction.write_bytes(original)
    report = compare_run_report(base, candidate)
    assert not report["measurement"]["gate_applied"]
    assert "candidate scored predictions or references do not match the run manifest" in (
        report["compatibility"]["issues"]
    )

    score_run(pages[:1], candidate / "predictions", candidate)
    report = compare_run_report(base, candidate)
    assert not report["measurement"]["gate_applied"]
    assert "candidate scored pages do not match its reference selection" in (
        report["compatibility"]["issues"]
    )

    score_run(pages, candidate / "predictions", candidate)
    manifest_path = candidate / "run-manifest.json"
    original_manifest = json.loads(manifest_path.read_text())
    mixed_manifest = json.loads(manifest_path.read_text())
    call = mixed_manifest["items"][pages[0].item_id]["observed_calls"][-1]
    call["toolbox_provenance"]["provider_version"] = "v2"
    manifest_path.write_text(json.dumps(mixed_manifest))
    report = compare_run_report(base, candidate)
    assert not report["measurement"]["gate_applied"]
    assert "candidate completed pages have conflicting Toolbox provenance" in report["compatibility"]["issues"]

    original_manifest["configuration"].pop("endpoint_path_sha256")
    original_manifest["identity"]["configuration"] = original_manifest["configuration"]
    original_manifest["identity_sha256"] = digest(original_manifest["identity"])
    manifest_path.write_text(json.dumps(original_manifest))
    score_run(pages, candidate / "predictions", candidate)
    report = compare_run_report(base, candidate)
    assert not report["measurement"]["gate_applied"]
    assert "candidate Toolbox endpoint paths are unverified" in report["compatibility"]["issues"]
