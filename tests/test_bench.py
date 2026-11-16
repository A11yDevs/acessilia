import json
import zipfile
from pathlib import Path

import pytest

from scripts.bench import __main__ as cli
from scripts.bench import core
from scripts.bench.datasets.drdocbench import DrDocBench
from scripts.bench.report import (
    _coverage_pair_issues,
    _identity_pair_issues,
    _read_windows,
    compare_runs,
    score_run,
)
from scripts.bench.run_manifest import STRUCTURE_PROTOCOL, _dataset_revision, selection_snapshot

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
    verdict = compare_runs(tmp_path / "base", tmp_path / "candidate")
    # A single document lands in one subset only: there is nothing to hold out.
    assert not verdict.accepted
    assert verdict.metric_deltas["tune_text"] == pytest.approx(50.0) or (
        verdict.metric_deltas["hold_text"] == pytest.approx(50.0))


def test_cli_run_writes_markdown_and_blocks(tmp_path, monkeypatch):
    _tree(tmp_path / "data", pages=(1,))
    monkeypatch.setattr(cli, "VAR", tmp_path / "var")
    monkeypatch.setattr(cli.toolbox, "extract_structure", lambda image, provider: {
        "document": {"elements": [{"type": "title", "text": "Page 1", "reading_order": 0},
                                  {"type": "text", "text": "Body 1", "reading_order": 1}]}})

    assert cli.main(["run", "--dataset", "drdocbench", "--root", str(tmp_path / "data")]) == 0
    assert cli.main(["score", "--dataset", "drdocbench", "--root", str(tmp_path / "data")]) == 0

    run = tmp_path / "var" / "drdocbench" / "dev" / "latest"
    assert (run / "predictions" / f"{DOC}_p1.md").read_text() == "# Page 1\n\nBody 1\n"
    assert (run / "predictions" / f"{DOC}_p1.blocks.json").exists()
    assert json.loads((run / "report.json").read_text())["overall"] == pytest.approx(100.0)


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


def test_cli_run_rejects_input_changed_during_extraction(tmp_path, monkeypatch):
    _tree(tmp_path / "data", pages=(1,))
    monkeypatch.setattr(cli, "VAR", tmp_path / "var")
    image_path = tmp_path / "data" / "MATH" / DOC / "images" / "page_1.jpg"

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
    assert out["metric_deltas"]["tune_teds"] is None or out["metric_deltas"]["hold_teds"] is None
