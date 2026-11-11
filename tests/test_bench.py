import json
import zipfile

import pytest
from acessilia_sdk.toolbox.capabilities import provider_default
from docstruct.evaluation.holdout import partition

from scripts.bench import __main__ as cli
from scripts.bench import core
from scripts.bench.datasets.base import BenchPage
from scripts.bench.datasets.drdocbench import DrDocBench
from scripts.bench.input_identity import INPUTS_FILE, page_identity
from scripts.bench.report import PROTOCOL_VERSION, SCORE_FILES, compare_runs, score_run

DOC = "0a1b2c3d-0000-4000-8000-000000000001"


def _tree(root, pages=(1, 2), gt=True):
    for n in pages:
        base = root / "MATH" / DOC
        (base / "images").mkdir(parents=True, exist_ok=True)
        (base / "images" / f"page_{n}.jpg").write_bytes(b"jpg")
        if gt:
            (base / "mds").mkdir(exist_ok=True)
            (base / "mds" / f"{DOC}_{n}.md").write_text(f"# Page {n}\n\nBody {n}\n", encoding="utf-8")


def _record_inputs(predictions, pages):
    (predictions.parent / INPUTS_FILE).write_text(
        json.dumps({page.item_id: page_identity(page) for page in pages}), encoding="utf-8"
    )


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
    _record_inputs(preds, pages)
    (preds / f"{DOC}_p1.md").write_text("# Page 1\n\nBody 1\n", encoding="utf-8")

    report = score_run(pages, preds, tmp_path / "base")

    assert report["pages"] == 2
    rows = [json.loads(line) for line in (tmp_path / "base" / "pages.jsonl").read_text().splitlines()]
    assert rows[0]["text"] == pytest.approx(100.0)
    assert rows[1]["text"] == pytest.approx(0.0)
    assert rows[0]["artifact_status"] == "present"
    assert rows[1]["evaluation_status"] == "missing_artifact"
    identity = report["evaluation_identity"]
    assert identity["protocol_version"] == "drdocbench-markdown-v2"
    assert identity["output_mode"] == "markdown"
    assert identity["criterion_ids"] == [f"{DOC}_p1", f"{DOC}_p2"]
    assert (tmp_path / "base" / "drilldown.csv").read_text().splitlines()[1].startswith(f"{DOC}_p2,")
    metadata = json.loads((tmp_path / "base" / "run-metadata.json").read_text())
    assert metadata["runtime"]["python"]
    assert metadata["configuration"]["prediction_digest"] == report["prediction_digest"]
    assert metadata["artifact_storage"]["observability_export"] is False

    (preds / f"{DOC}_p2.md").write_text("# Page 2\n\nBody 2\n", encoding="utf-8")
    score_run(pages, preds, tmp_path / "candidate")
    verdict = compare_runs(tmp_path / "base", tmp_path / "candidate")
    # A single document lands in one subset only: there is nothing to hold out.
    assert not verdict.accepted
    assert verdict.metric_deltas["tune_text"] == pytest.approx(50.0) or (
        verdict.metric_deltas["hold_text"] == pytest.approx(50.0))


def test_compare_runs_refuses_different_dataset_selection(tmp_path):
    _tree(tmp_path / "data")
    pages = DrDocBench().pages(tmp_path / "data")
    predictions = tmp_path / "predictions"
    predictions.mkdir()
    _record_inputs(predictions, pages)
    for page in pages:
        (predictions / f"{page.item_id}.md").write_text("same output", encoding="utf-8")

    score_run(pages, predictions, tmp_path / "full")
    score_run(pages[:1], predictions, tmp_path / "partial")

    with pytest.raises(ValueError, match="incomparable benchmark runs.*selection"):
        compare_runs(tmp_path / "full", tmp_path / "partial")


def test_compare_rejects_changed_images_with_same_references(tmp_path, monkeypatch):
    _tree(tmp_path / "data")
    pages = DrDocBench().pages(tmp_path / "data")
    monkeypatch.setattr(cli.toolbox, "extract_structure", lambda *args: {"document": {"elements": []}})
    base, candidate = tmp_path / "base", tmp_path / "candidate"
    assert cli._run(pages, base, "same", False) == 0
    base_report = score_run(pages, base / "predictions", base)
    pages[0].image_path.write_bytes(b"changed source")
    assert cli._run(pages, candidate, "same", False) == 0
    candidate_report = score_run(pages, candidate / "predictions", candidate)
    assert base_report["evaluation_identity"]["reference_digest"] == (
        candidate_report["evaluation_identity"]["reference_digest"]
    )

    with pytest.raises(ValueError, match="incomparable benchmark runs.*input_digest"):
        compare_runs(base, candidate)


def test_compare_requires_verified_prediction_inputs(tmp_path):
    _tree(tmp_path / "data")
    pages = DrDocBench().pages(tmp_path / "data")
    run = tmp_path / "legacy"
    assert score_run(pages, run / "predictions", run)["pages"] == 2

    with pytest.raises(ValueError, match="prediction inputs were not verified"):
        compare_runs(run, run)


@pytest.mark.parametrize("resume", [False, True], ids=["replace", "resume"])
def test_cli_compare_requires_rescoring_after_run_changes(tmp_path, monkeypatch, capsys, resume):
    root = tmp_path / "data"
    _tree(root)
    monkeypatch.setattr(cli, "VAR", tmp_path / "var")
    monkeypatch.setattr(cli.toolbox, "extract_structure", lambda *_: {"document": {"elements": []}})
    args = ["--dataset", "drdocbench", "--root", str(root)]
    run = tmp_path / "var" / "drdocbench" / "dev" / "latest"
    compare = ["compare", str(run), str(run)]

    assert cli.main(["run", *args, "--sample", "1"]) == 0
    assert cli.main(["score", *args]) == 0
    assert cli.main(["run", *args, "--sample", "1", "--resume"]) == 0
    assert all((run / name).is_file() for name in SCORE_FILES)

    options = ["--resume"] if resume else []
    if not resume:
        image = DrDocBench().pages(root)[0].image_path
        image.write_bytes(b"different image")
    assert cli.main(["run", *args, *options]) == 0
    assert all(not (run / name).exists() for name in SCORE_FILES)

    capsys.readouterr()
    assert cli.main(compare) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "incomparable"
    assert "rescore" in result["reason"]
    assert cli.main(["score", *args]) == 0
    assert cli.main(compare) == 1  # This single document cannot populate both splits.


@pytest.mark.parametrize(("change", "reason"), [
    ("drop", "missing criteria"),
    ("duplicate", "duplicate criterion"),
    ("move", "criteria identify different pages"),
    ("metric", "cdm coverage differs"),
])
def test_compare_runs_refuses_score_rows_that_disagree_with_report(tmp_path, change, reason):
    _tree(tmp_path / "data")
    pages = DrDocBench().pages(tmp_path / "data")
    predictions = tmp_path / "predictions"
    predictions.mkdir()
    _record_inputs(predictions, pages)
    pages[0].gt_path.write_text("Text\n\n$$x$$\n", encoding="utf-8")
    (predictions / f"{pages[0].item_id}.md").write_text(
        pages[0].gt_path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    base, candidate = tmp_path / "base", tmp_path / "candidate"
    score_run(pages, predictions, base)
    score_run(pages, predictions, candidate)
    assert (base / "report.json").read_bytes() == (candidate / "report.json").read_bytes()

    path = candidate / "pages.jsonl"
    first, second = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows = {
        "drop": [first],
        "duplicate": [first, first],
        "move": [first, {**second, "page": 3}],
        "metric": [{**first, "cdm": None}, second],
    }[change]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    with pytest.raises(ValueError, match=reason):
        compare_runs(base, candidate)


def test_score_run_rejects_pages_from_mixed_dataset_revisions(tmp_path):
    _tree(tmp_path / "data")
    pages = DrDocBench().pages(tmp_path / "data")
    pages[0].meta["dataset_revision"] = "revision-a"
    pages[1].meta["dataset_revision"] = "revision-b"

    with pytest.raises(ValueError, match="cannot mix Dataset revisions"):
        score_run(pages, tmp_path / "predictions", tmp_path / "out")


@pytest.mark.parametrize("configured_provider", [None, "", "custom-structure"])
def test_cli_run_writes_markdown_and_blocks(tmp_path, monkeypatch, configured_provider):
    if configured_provider is None:
        monkeypatch.delenv("TOOLBOX_PROVIDER", raising=False)
    else:
        monkeypatch.setenv("TOOLBOX_PROVIDER", configured_provider)
    expected_provider = configured_provider or provider_default("toolbox_provider")
    _tree(tmp_path / "data", pages=(1,))
    monkeypatch.setattr(cli, "VAR", tmp_path / "var")
    monkeypatch.setattr(cli.toolbox, "extract_structure", lambda image, provider: {
        "provider": provider,
        "provenance": {
            "provider_version": "2.1",
            "model_versions": {"extractor": "1.2"},
            "capability_version": 1,
        },
        "document": {"elements": [{"type": "title", "text": "Page 1", "reading_order": 0},
                                  {"type": "text", "text": "Body 1", "reading_order": 1}]}})

    assert cli.main(["run", "--dataset", "drdocbench", "--root", str(tmp_path / "data")]) == 0
    assert cli.main(["score", "--dataset", "drdocbench", "--root", str(tmp_path / "data")]) == 0

    run = tmp_path / "var" / "drdocbench" / "dev" / "latest"
    assert (run / "predictions" / f"{DOC}_p1.md").read_text() == "# Page 1\n\nBody 1\n"
    assert (run / "predictions" / f"{DOC}_p1.blocks.json").exists()
    assert json.loads((run / "report.json").read_text())["overall"] == pytest.approx(100.0)
    metadata = json.loads((run / "run-metadata.json").read_text())
    assert metadata["configuration"]["extraction"]["provider"] == expected_provider
    extraction = json.loads((run / "pages.jsonl").read_text())["extraction"]
    assert extraction == {
        "provider": expected_provider,
        "provider_version": "2.1",
        "model_versions": {"extractor": "1.2"},
        "capability_version": 1,
        "input": cli.page_identity(DrDocBench().pages(tmp_path / "data")[0]),
    }


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
    seen = []
    monkeypatch.setattr(cli.toolbox, "extract_structure",
                        lambda image, provider: seen.append((image.name, provider)) or {"document": {"elements": []}})
    command = ["run", "--dataset", "drdocbench", "--root", str(tmp_path / "data")]

    assert cli.main([*command, "--provider", "provider-a", "--sample", "1"]) == 0
    (preds / f"{DOC}_p1.md").write_text("kept", encoding="utf-8")
    assert cli.main([*command, "--provider", "provider-b", "--resume"]) == 2
    assert seen == [("page_1.jpg", "provider-a")]
    assert (preds.parent / "pages.txt").read_text().split() == [f"{DOC}_p1"]
    assert cli.main([*command, "--provider", "provider-a", "--resume"]) == 0
    assert seen == [("page_1.jpg", "provider-a"), ("page_2.jpg", "provider-a")]
    assert (preds / f"{DOC}_p1.md").read_text() == "kept"
    # Resuming keeps the run covering both pages, not only the resumed ones.
    manifest = (preds.parent / "pages.txt").read_text().split()
    assert manifest == [f"{DOC}_p1", f"{DOC}_p2"]

    # A finished run resumes as a no-op with success.
    assert cli.main([*command, "--provider", "provider-a", "--resume"]) == 0
    assert len(seen) == 2


def test_cli_scores_legacy_predictions_but_does_not_mix_them_on_resume(tmp_path, monkeypatch):
    _tree(tmp_path / "data")
    monkeypatch.setattr(cli, "VAR", tmp_path / "var")
    run = tmp_path / "var" / "drdocbench" / "dev" / "latest"
    (run / "predictions").mkdir(parents=True)
    (run / "predictions" / f"{DOC}_p1.md").write_text("kept", encoding="utf-8")
    args = ["--dataset", "drdocbench", "--root", str(tmp_path / "data")]

    assert cli.main(["run", *args, "--resume"]) == 2
    assert not (run / "extraction.json").exists()
    assert cli.main(["score", *args]) == 0
    metadata = json.loads((run / "run-metadata.json").read_text())
    assert metadata["configuration"]["extraction"] is None
    assert metadata["configuration"]["prediction_inputs_verified"] is False


@pytest.mark.parametrize("change", ["revision", "dataset", "image", "missing", "empty"])
def test_resume_rejects_changed_or_unrecorded_source_inputs(tmp_path, monkeypatch, change):
    _tree(tmp_path / "data")
    pages = DrDocBench().pages(tmp_path / "data")
    monkeypatch.setattr(cli.toolbox, "extract_structure", lambda *args: {"document": {"elements": []}})
    run = tmp_path / "run"
    assert cli._run(pages[:1], run, "same", False) == 0
    before = {p.name: p.read_bytes() for p in run.glob("*.json")}
    if change == "revision":
        for page in pages:
            page.meta["dataset_revision"] = "B"
    elif change == "dataset":
        for page in pages:
            page.meta["dataset_id"] = "another-dataset"
    elif change == "image":
        pages[0].image_path.write_bytes(b"changed source")
    elif change == "missing":
        (run / "inputs.json").unlink()
    else:
        (run / "inputs.json").write_text("{}")
    current = {p.name: p.read_bytes() for p in run.glob("*.json")}
    assert cli._run(pages, run, "same", False, resume=True) == 2
    assert {p.name: p.read_bytes() for p in run.glob("*.json")} == current
    assert not (run / "predictions" / f"{DOC}_p2.md").exists()
    assert (run / "extraction.json").read_bytes() == before["extraction.json"]


def test_relocated_identical_inputs_can_resume_and_keep_all_source_identities(tmp_path, monkeypatch):
    import shutil

    _tree(tmp_path / "data")
    monkeypatch.setattr(cli.toolbox, "extract_structure", lambda *args: {"document": {"elements": []}})
    run = tmp_path / "run"
    assert cli._run(DrDocBench().pages(tmp_path / "data")[:1], run, "same", False) == 0
    shutil.copytree(tmp_path / "data", tmp_path / "moved")
    pages = DrDocBench().pages(tmp_path / "moved")
    assert cli._run(pages, run, "same", False, resume=True) == 0
    score_run(pages, run / "predictions", run)
    metadata = json.loads((run / "run-metadata.json").read_text())
    assert metadata["configuration"]["prediction_inputs_verified"] is True
    assert len(json.loads((run / "inputs.json").read_text())) == 2


@pytest.mark.parametrize("change", ["image", "revision", "missing", "empty"])
def test_score_rejects_predictions_bound_to_other_inputs(tmp_path, monkeypatch, change):
    _tree(tmp_path / "data")
    pages = DrDocBench().pages(tmp_path / "data")
    monkeypatch.setattr(cli.toolbox, "extract_structure", lambda *args: {"document": {"elements": []}})
    run = tmp_path / "run"
    assert cli._run(pages, run, "same", False) == 0
    if change == "image":
        pages[0].image_path.write_bytes(b"changed source")
    elif change == "revision":
        for page in pages:
            page.meta["dataset_revision"] = "B"
    elif change == "missing":
        (run / "inputs.json").unlink()
    else:
        (run / "inputs.json").write_text("{}")
    with pytest.raises(ValueError, match="input identit"):
        score_run(pages, run / "predictions", run)
    assert not (run / "report.json").exists()


def _stub_toolbox(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "VAR", tmp_path / "var")
    monkeypatch.setattr(cli.toolbox, "extract_structure", lambda image, provider: {
        "document": {"elements": [{"type": "text", "text": "Body", "reading_order": 0}]}})
    return tmp_path / "var" / "drdocbench" / "dev" / "latest"


@pytest.mark.parametrize("remove_image", [False, True], ids=["changed", "missing"])
def test_failed_rescore_invalidates_the_previous_gate_report(tmp_path, monkeypatch, capsys, remove_image):
    root = tmp_path / "data"
    _tree(root, pages=(1,))
    run = _stub_toolbox(tmp_path, monkeypatch)
    data = ["--dataset", "drdocbench", "--root", str(root)]
    assert cli.main(["run", *data]) == 0
    assert cli.main(["score", *data]) == 0
    assert (run / "report.json").is_file()

    image = DrDocBench().pages(root)[0].image_path
    if remove_image:
        image.unlink()
    else:
        image.write_bytes(b"changed source")
    assert cli.main(["score", *data]) == (1 if remove_image else 2)
    assert all(not (run / name).exists() for name in SCORE_FILES)
    assert (run / "predictions" / f"{DOC}_p1.md").is_file()

    capsys.readouterr()
    assert cli.main(["compare", str(run), str(run)]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "incomparable"


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
    _tree(tmp_path / "data", pages=(1,))
    pages = DrDocBench().pages(tmp_path / "data")
    _record_inputs(tmp_path / "predictions", pages)
    for name in ("base", "candidate"):
        score_run(pages, tmp_path / "predictions", tmp_path / name)

    cli.main(["compare", str(tmp_path / "base"), str(tmp_path / "candidate")])

    out = json.loads(capsys.readouterr().out, parse_constant=lambda c: pytest.fail(f"non-JSON {c}"))
    assert out["metric_deltas"]["tune_teds"] is None or out["metric_deltas"]["hold_teds"] is None


def test_compare_rejects_cdm_regression_despite_text_gain(tmp_path):
    documents = {}
    for index in range(100):
        document = f"doc-{index}"
        documents.setdefault(partition(f"{document}_page_1"), document)
        if len(documents) == 2:
            break
    assert len(documents) == 2
    reference = tmp_path / "reference.md"
    reference.write_text("Reference text.", encoding="utf-8")
    image = tmp_path / "page.jpg"
    image.write_bytes(b"jpg")
    pages = [BenchPage(f"{document}_p1", document, 1, image, reference) for document in documents.values()]
    _record_inputs(tmp_path / "predictions", pages)
    base, candidate = tmp_path / "base", tmp_path / "candidate"
    for path, text, cdm in ((base, 60, 100), (candidate, 80, 90)):
        score_run(pages, tmp_path / "predictions", path)
        scores = path / "pages.jsonl"
        rows = [json.loads(line) for line in scores.read_text().splitlines()]
        scores.write_text("".join(json.dumps({**row, "text": text, "cdm": cdm}) + "\n" for row in rows))

    verdict = compare_runs(base, candidate)
    assert not verdict.accepted
    assert verdict.metric_deltas["hold_cdm"] == -10
    assert "cdm" in verdict.reason


def test_omitting_failed_formulas_does_not_improve_cdm(tmp_path):
    documents = ("doc0", "doc5")
    assert {partition(document) for document in documents} == {"tune", "hold"}
    base_predictions = tmp_path / "base-predictions"
    candidate_predictions = tmp_path / "candidate-predictions"
    base_predictions.mkdir()
    candidate_predictions.mkdir()
    text = "Faithfully transcribed surrounding text. " * 120
    reference = tmp_path / "reference.md"
    reference.write_text(text + "$$abc$$", encoding="utf-8")
    pages = []
    image = tmp_path / "page.jpg"
    image.write_bytes(b"jpg")
    for document in documents:
        for number in (1, 2):
            item_id = f"{document}_p{number}"
            pages.append(BenchPage(item_id, document, number, image, reference))
            (base_predictions / f"{item_id}.md").write_text(
                text + ("$$xyz$$" if number == 1 else "$$abc$$"), encoding="utf-8"
            )
            (candidate_predictions / f"{item_id}.md").write_text(
                text + ("" if number == 1 else "$$abc$$"), encoding="utf-8"
            )

    _record_inputs(base_predictions, pages)
    base, candidate = tmp_path / "base", tmp_path / "candidate"
    base_report = score_run(pages, base_predictions, base)
    candidate_report = score_run(pages, candidate_predictions, candidate)
    assert base_report["evaluation_identity"] == candidate_report["evaluation_identity"]

    verdict = compare_runs(base, candidate)
    assert not verdict.accepted
    assert verdict.metric_deltas["tune_cdm"] == 0.0
    assert verdict.metric_deltas["hold_cdm"] == 0.0


def test_compare_requires_rescoring_obsolete_protocols(tmp_path):
    base, candidate = tmp_path / "base", tmp_path / "candidate"
    for run in (base, candidate):
        report = score_run([], tmp_path / "predictions", run)
        report["evaluation_identity"]["protocol_version"] = "drdocbench-markdown-v1"
        (run / "report.json").write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(ValueError, match=f"rescore it with {PROTOCOL_VERSION}"):
        compare_runs(base, candidate)


@pytest.mark.parametrize("report", [None, {"evaluation_identity": {}}])
def test_compare_reports_old_runs_as_incomparable(tmp_path, capsys, report):
    for name in ("base", "candidate"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "pages.jsonl").write_text("{}\n")
        if report is not None:
            (tmp_path / name / "report.json").write_text(json.dumps(report))

    assert cli.main(["compare", str(tmp_path / "base"), str(tmp_path / "candidate")]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "incomparable"
    assert "rescore" in report["reason"]
