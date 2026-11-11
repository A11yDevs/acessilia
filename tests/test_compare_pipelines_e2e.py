"""End-to-end tests for pipeline comparison (requires Toolbox and infrastructure).

Compares PDDL+Toolbox output against Core-owned historical canonical fixtures.

Requires:
- All backend dependencies installed
- Toolbox service running and accessible via settings.toolbox_base_url
- Local canonicals in tests/fixtures/pipeline-comparison/ and inputs from the Dataset (hash-checked, required)

Marked with @pytest.mark.e2e so they can be skipped in CI:
    pytest tests/ -m e2e
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.compare_pipelines import (
    _extract_formulas,
    _extract_tables,
    _extract_text,
    _flatten_blocks,
    _summarize_document,
    run_comparison,
)
from scripts.bench.dataset_reference import dataset_dir
from scripts.bench.pipeline_fixtures import load_pipeline_fixtures, resolve_pipeline_input


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(params=load_pipeline_fixtures(), ids=lambda case: f"{case['id']}-historical-canonical")
def reference_pair(request: pytest.FixtureRequest) -> tuple[Path, Path]:
    case = request.param
    return resolve_pipeline_input(case, dataset_dir()), case["canonical_path"]


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
