"""Offline checks for the pinned Dataset contract and local regression evidence."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import csv
from pathlib import Path

import pytest

from scripts.bench.dataset_reference import (
    EXPECTED_DATASET_REVISION,
    EXPECTED_REFERENCES_DIGEST,
    DatasetReferenceError,
    assert_pinned_dataset,
    git_revision,
    load_references,
    EvaluationSelection,
)
from scripts.bench.math_case import resolve_case as resolve_math_case, score_case
from scripts.bench.pipeline_fixtures import load_pipeline_fixtures, resolve_pipeline_input
from scripts.bench.slide_case import resolve_case as resolve_slide_case, score_text

REPO = Path(__file__).resolve().parents[1]
PINNED_CASES = REPO / "tests" / "fixtures" / "pipeline-comparison"


def _configured_dataset() -> Path:
    return Path(os.environ.get("ACESSILIA_TEST_DATASET_DIR") or REPO / "tests" / "dataset")


def test_core_owned_pipeline_fixtures_keep_source_hashes_and_schema() -> None:
    manifest_path = PINNED_CASES / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["purpose"].startswith("Historical regression snapshots")
    assert manifest["source_revision"] == "9ed07b28aeddb69721228f2dd66de6f9794c0001"
    assert manifest["canonical_schema_version"] == "1.0.0"
    assert manifest["protocol"] == "historical-heuristic-v1"
    assert [case["id"] for case in manifest["cases"]] == ["001", "004", "005", "007", "008"]

    checked = load_pipeline_fixtures(PINNED_CASES)
    for case in checked:
        canonical_path = case["canonical_path"]
        assert hashlib.sha256(canonical_path.read_bytes()).hexdigest() == case["canonical_sha256"]
        canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
        assert canonical["schema_version"] == manifest["canonical_schema_version"]


def test_missing_core_owned_fixture_fails_instead_of_skipping(tmp_path: Path) -> None:
    # The fixture verifier is intentionally strict: a missing copied baseline
    # is a broken Core checkout, not an optional Dataset E2E skip.
    with pytest.raises(FileNotFoundError):
        load_pipeline_fixtures(tmp_path)


def test_ci_dataset_contract_and_case_readers_when_checkout_is_provided(tmp_path: Path) -> None:
    root = _configured_dataset()
    if not root.is_dir():
        pytest.skip("set ACESSILIA_TEST_DATASET_DIR to run the pinned Dataset smoke test")

    identity = assert_pinned_dataset(root)
    for case in load_pipeline_fixtures():
        assert resolve_pipeline_input(case, root).is_file()
    math_rows, math_expectations, math_meta = resolve_math_case(root, require_pinned=True)
    slide_rows, slide_expectations, slide_meta = resolve_slide_case(root, require_pinned=True)

    assert identity["revision"] == EXPECTED_DATASET_REVISION
    assert identity["references_digest"] == EXPECTED_REFERENCES_DIGEST
    assert len(math_rows) == 91
    assert len(math_expectations["speech"]["formulas"]) == 8
    assert len(slide_rows) == 237
    assert math_meta["references_schema_version"] == "1.2.0"
    assert slide_meta["references_schema_version"] == "1.2.0"
    assert math_meta["tasks"]["math_formula_speech"]["eligible_count"] == 16
    assert slide_meta["tasks"]["presentation_slide_content"]["availability"] == "partial"
    structure_references = slide_meta["tasks"]["presentation_structure"]["references"]
    assert [(item["reference_type"], item["annotated_count"], item["coverage_unit"])
            for item in structure_references] == [
        ("expectations", 14, "check"),
        ("ground_truth", 12, "check"),
    ]
    assert "annotated_count" not in slide_meta["tasks"]["presentation_structure"]
    structure_ids = set(slide_meta["task_criterion_ids"]["presentation_structure"])
    assert len(structure_ids) == 12
    structure_card = score_text(
        slide_rows,
        slide_expectations,
        "",
        "selected-structure.txt",
        selection=EvaluationSelection(tasks=("presentation_structure",)),
        dataset_metadata=slide_meta,
    )
    unsupported_ids = {
        item["id"] for item in structure_card.not_evaluated
        if item["reason"].startswith("unsupported criterion:")
    }
    assert unsupported_ids == structure_ids
    assert structure_ids <= set(structure_card.criteria_ids)
    assert [item["annotated"] for item in structure_card.summary()["reference_coverage"]["presentation_structure"]] == [14, 12]
    content_id = next(row["id"] for row in slide_rows if row["id"] not in structure_ids)
    with pytest.raises(DatasetReferenceError, match="outside the selected task scope"):
        score_text(
            slide_rows,
            slide_expectations,
            "",
            "wrong-task-object.txt",
            selection=EvaluationSelection(
                tasks=("presentation_structure",), object_ids=(content_id,)
            ),
            dataset_metadata=slide_meta,
        )
    content_card = score_text(
        slide_rows,
        slide_expectations,
        "",
        "selected-content.txt",
        selection=EvaluationSelection(tasks=("presentation_slide_content",)),
        dataset_metadata=slide_meta,
    )
    assert not structure_ids & set(content_card.criteria_ids)
    page_one = score_case(
        math_rows,
        math_expectations,
        {"sections": []},
        txt="",
        selection=EvaluationSelection(pages=(1,)),
        dataset_metadata=math_meta,
    )
    assert [check.id for check in page_one.speech] == ["speech:p1-d01"]
    assert page_one.summary()["speech_presence"]["total"] == 2

    copied = tmp_path / "core-dataset-reference-test"
    shutil.copytree(root / "references", copied / "references")
    csv_path = copied / "references" / "math" / "036" / "ground_truth.csv"
    csv_path.write_text(
        csv_path.read_text(encoding="utf-8").replace(",display,", ",unsupported-kind,", 1),
        encoding="utf-8",
    )
    copied_references = load_references(copied, "036")
    assert copied_references is not None
    with pytest.raises(DatasetReferenceError, match="invalid CSV reference row"):
        copied_references.read_task("math_formula_transcription", "ground_truth")


def test_exported_dataset_tree_without_git_is_supported(tmp_path: Path) -> None:
    root = _configured_dataset()
    if not root.is_dir():
        pytest.skip("set ACESSILIA_TEST_DATASET_DIR to run the local export compatibility check")
    exported = tmp_path / "dataset-export"
    shutil.copytree(root / "references", exported / "references")

    assert git_revision(exported) is None
    references = load_references(exported, "036")
    assert references is not None
    assert references.revision is None
    assert references.digest == load_references(root, "036").digest
    _math_rows, _math_expectations, math_metadata = resolve_math_case(
        exported, require_pinned=True
    )
    _slide_rows, _slide_expectations, slide_metadata = resolve_slide_case(
        exported, require_pinned=True
    )
    assert math_metadata["revision"] == EXPECTED_DATASET_REVISION
    assert slide_metadata["revision"] == EXPECTED_DATASET_REVISION


def test_pinned_readers_reject_legacy_only_layout(tmp_path: Path) -> None:
    case = tmp_path / "input" / "math-reference"
    case.mkdir(parents=True)
    (case / "ground_truth.csv").write_text("id,page,kind,expected_latex\n", encoding="utf-8")
    (case / "expectations.json").write_text("{}", encoding="utf-8")

    with pytest.raises(DatasetReferenceError, match="pinned Dataset references manifest is missing"):
        resolve_math_case(tmp_path, require_pinned=True)


def test_missing_degraded_run_task_is_a_reference_error(tmp_path: Path) -> None:
    root = _configured_dataset()
    if not root.is_dir():
        pytest.skip("set ACESSILIA_TEST_DATASET_DIR to run the pinned Dataset smoke test")
    exported = tmp_path / "dataset-export"
    shutil.copytree(root / "references", exported / "references")
    manifest = exported / "references" / "manifest.csv"
    with manifest.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames
        rows = [row for row in reader if not (
            row["input_id"] == "006"
            and row["task"] == "presentation_degraded_run_behavior"
        )]
    with manifest.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    with pytest.raises(DatasetReferenceError, match="missing required task 'presentation_degraded_run_behavior'"):
        resolve_slide_case(exported)


def test_invalid_new_layout_never_falls_back_to_legacy_case(tmp_path: Path) -> None:
    legacy = tmp_path / "input" / "math-reference"
    legacy.mkdir(parents=True)
    (legacy / "ground_truth.csv").write_text("id,page,kind,expected_latex\n", encoding="utf-8")
    (legacy / "expectations.json").write_text("{}", encoding="utf-8")
    (tmp_path / "references").mkdir()

    with pytest.raises(DatasetReferenceError, match="no manifest"):
        resolve_math_case(tmp_path)


@pytest.mark.parametrize(
    ("resolve_case", "case_dir"),
    [(resolve_math_case, "math-reference"), (resolve_slide_case, "presentation-reference")],
)
def test_explicit_input_paths_require_references_even_if_directory_is_absent(
    tmp_path: Path, resolve_case, case_dir: str,
) -> None:
    legacy = tmp_path / "input" / case_dir
    legacy.mkdir(parents=True)
    (legacy / "ground_truth.csv").write_text("id,page,kind\n", encoding="utf-8")
    (legacy / "expectations.json").write_text("{}", encoding="utf-8")
    manifest = legacy.parent / "manifest.csv"
    manifest.write_text("id\n", encoding="utf-8")
    assert resolve_case(tmp_path)[2]["references_schema_version"] == "legacy"

    manifest.write_text("id,input_path\n", encoding="utf-8-sig")
    with pytest.raises(DatasetReferenceError, match="references manifest is missing"):
        resolve_case(tmp_path)


@pytest.mark.parametrize(
    ("task", "field", "value", "error"),
    [
        ("math_formula_transcription", "eligible_count", "90", "inconsistent coverage"),
        ("math_formula_transcription", "eligible_count", "92", "inconsistent coverage"),
        (
            "math_text_quality", "record_selector",
            json.dumps({"type": "json_pointers", "pointers": ["/structure"], "count_mode": "rules"}),
            "invalid JSON selector for task 'math_text_quality'",
        ),
    ],
)
def test_public_reader_rejects_inconsistent_task_references(tmp_path, task, field, value, error):
    root = _configured_dataset()
    if not root.is_dir():
        pytest.skip("set ACESSILIA_TEST_DATASET_DIR to test the exported contract")
    shutil.copytree(root / "references", tmp_path / "references")
    manifest = tmp_path / "references" / "manifest.csv"
    with manifest.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        fields, rows = reader.fieldnames, list(reader)
    next(row for row in rows if row["task"] == task)[field] = value
    with manifest.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    with pytest.raises(DatasetReferenceError, match=error):
        resolve_math_case(tmp_path)
