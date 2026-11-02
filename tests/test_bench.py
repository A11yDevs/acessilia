import json
import zipfile

import pytest

from scripts.bench import __main__ as cli
from scripts.bench import core
from scripts.bench.datasets.drdocbench import DrDocBench
from scripts.bench.report import compare_runs, score_run

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

    report = score_run(pages, preds, tmp_path / "base")

    assert report["pages"] == 2
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
    seen = []
    monkeypatch.setattr(cli.toolbox, "extract_structure",
                        lambda image, provider: seen.append(image.name) or {"document": {"elements": []}})

    assert cli.main(["run", "--dataset", "drdocbench", "--root", str(tmp_path / "data"), "--resume"]) == 0
    assert seen == ["page_2.jpg"]
    assert (preds / f"{DOC}_p1.md").read_text() == "kept"
    # Resuming keeps the run covering both pages, not only the resumed ones.
    manifest = (preds.parent / "pages.txt").read_text().split()
    assert manifest == [f"{DOC}_p1", f"{DOC}_p2"]

    # A finished run resumes as a no-op with success.
    assert cli.main(["run", "--dataset", "drdocbench", "--root", str(tmp_path / "data"), "--resume"]) == 0
    assert seen == ["page_2.jpg"]


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
