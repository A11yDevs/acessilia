"""End-to-end tests for pipeline comparison (requires Toolbox and infrastructure).

Compares PDDL+Toolbox output against pre-computed reference canonical documents
from tests/dataset/intermediate/canonical-document/.

Requires:
- All backend dependencies installed
- Toolbox service running and accessible via settings.toolbox_base_url
- Dataset files at tests/dataset/input/ and tests/dataset/intermediate/

Marked with @pytest.mark.e2e so they can be skipped in CI:
    pytest tests/ -m e2e
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.compare_pipelines import (
    _compare_documents,
    _compute_verdict,
    _extract_formulas,
    _extract_tables,
    _extract_text,
    _flatten_blocks,
    _jaccard_similarity,
    _summarize_document,
    run_comparison,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DATASET_DIR = Path(__file__).resolve().parents[1] / "tests" / "dataset"

REFERENCE_FIXTURES: list[tuple[str, str, Path, Path]] = [
    (
        "001-java-oo-3pgs",
        "3-page Java OO tutorial",
        DATASET_DIR / "input" / "001.pdf",
        DATASET_DIR / "intermediate" / "canonical-document" / "001.json",
    ),
    (
        "004-java-oo-tables",
        "Single page with tables",
        DATASET_DIR / "input" / "004.pdf",
        DATASET_DIR / "intermediate" / "canonical-document" / "004.json",
    ),
    (
        "005-sunset-skyline",
        "Sunset photograph (JPEG)",
        DATASET_DIR / "input" / "005.jpeg",
        DATASET_DIR / "intermediate" / "canonical-document" / "005.json",
    ),
    (
        "007-grandezas-formulas",
        "Single page with formulas",
        DATASET_DIR / "input" / "007.pdf",
        DATASET_DIR / "intermediate" / "canonical-document" / "007.json",
    ),
    (
        "008-grandezas-chart",
        "Single page with bar chart",
        DATASET_DIR / "input" / "008.pdf",
        DATASET_DIR / "intermediate" / "canonical-document" / "008.json",
    ),
]


def _resolve_pair(label: str, input_path: Path, ref_path: Path) -> tuple[Path, Path]:
    if not input_path.exists():
        pytest.skip(f"Input '{label}' not found: {input_path}")
    if not ref_path.exists():
        pytest.skip(f"Reference '{label}' not found: {ref_path}")
    return (input_path, ref_path)


@pytest.fixture(params=REFERENCE_FIXTURES, ids=[f[0] for f in REFERENCE_FIXTURES])
def reference_pair(request: pytest.FixtureRequest) -> tuple[Path, Path]:
    _label, _desc, input_path, ref_path = request.param
    return _resolve_pair(_label, input_path, ref_path)


@pytest.fixture
def output_tmpdir(tmp_path: Path) -> Path:
    return tmp_path / "compare_out"


# ---------------------------------------------------------------------------
# E2E: reference-based comparison
# ---------------------------------------------------------------------------


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_reference_comparison_defaults(
    reference_pair: tuple[Path, Path], output_tmpdir: Path
) -> None:
    """Compare Toolbox output against pre-computed reference canonical."""
    input_path, ref_path = reference_pair
    report_path = await run_comparison(
        file_path=input_path,
        reference_path=ref_path,
        output_dir=output_tmpdir,
        mode="normal",
    )
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert "source_file" in report
    assert "reference_file" in report
    assert "engines" in report
    assert "comparison" in report
    assert "verdict" in report
    assert report["engines"]["toolbox"]["status"] == "ok"
    comparison = report["comparison"]
    assert "structural" in comparison
    assert "text" in comparison
    assert comparison["structural"]["section_count"]["reference"] >= 0
    assert comparison["structural"]["section_count"]["toolbox"] >= 0


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_reference_comparison_artifact_files(
    reference_pair: tuple[Path, Path], output_tmpdir: Path
) -> None:
    """Verify that toolbox artifacts are written."""
    input_path, ref_path = reference_pair
    await run_comparison(
        file_path=input_path,
        reference_path=ref_path,
        output_dir=output_tmpdir,
        mode="normal",
    )
    structured = output_tmpdir / "toolbox.structured.json"
    canonical = output_tmpdir / "toolbox.canonical.json"
    assert structured.exists()
    assert canonical.exists()
    assert isinstance(json.loads(structured.read_text(encoding="utf-8")), dict)
    assert isinstance(json.loads(canonical.read_text(encoding="utf-8")), dict)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_reference_comparison_ocr_enabled(
    reference_pair: tuple[Path, Path], output_tmpdir: Path
) -> None:
    """Run comparison with OCR enabled."""
    input_path, ref_path = reference_pair
    report_path = await run_comparison(
        file_path=input_path,
        reference_path=ref_path,
        output_dir=output_tmpdir,
        mode="normal",
        enable_ocr=True,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["engines"]["toolbox"]["status"] == "ok"


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_reference_comparison_execute_plan(
    reference_pair: tuple[Path, Path], output_tmpdir: Path
) -> None:
    """Run comparison with plan execution enabled."""
    input_path, ref_path = reference_pair
    report_path = await run_comparison(
        file_path=input_path,
        reference_path=ref_path,
        output_dir=output_tmpdir,
        mode="normal",
        execute_plan=True,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["engines"]["toolbox"]["status"] == "ok"


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_helper_consistency(
    reference_pair: tuple[Path, Path], output_tmpdir: Path
) -> None:
    """Verify helper functions produce consistent results on real output."""
    input_path, ref_path = reference_pair
    report_path = await run_comparison(
        file_path=input_path,
        reference_path=ref_path,
        output_dir=output_tmpdir,
        mode="normal",
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    toolbox = json.loads(
        (output_tmpdir / "toolbox.canonical.json").read_text(encoding="utf-8")
    )
    blocks = _flatten_blocks(toolbox)
    assert isinstance(blocks, list)
    text = _extract_text(toolbox)
    assert isinstance(text, str)
    reported = report["engines"]["toolbox"]["summary"]
    direct = _summarize_document(toolbox)
    assert reported["block_count"] == direct["block_count"]
    assert isinstance(_extract_formulas(toolbox), list)
    assert isinstance(_extract_tables(toolbox), list)


# ---------------------------------------------------------------------------
# E2E: error handling
# ---------------------------------------------------------------------------


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_run_comparison_nonexistent_file(output_tmpdir: Path) -> None:
    """Passing a nonexistent file should not crash."""
    fake = Path("/tmp/nonexistent_XXXXXXXXXX.pdf")
    # Create a minimal valid reference so the comparison can proceed
    fake_ref = output_tmpdir / "fake_ref.json"
    fake_ref.parent.mkdir(parents=True, exist_ok=True)
    fake_ref.write_text('{"sections": []}', encoding="utf-8")
    report_path = await run_comparison(
        file_path=fake,
        reference_path=fake_ref,
        output_dir=output_tmpdir,
        mode="normal",
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["engines"]["toolbox"]["status"] == "error"
