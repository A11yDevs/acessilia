"""End-to-end tests for pipeline comparison (requires Toolbox and infrastructure).

These tests exercise the full comparison workflow against a real PDF file
using both the PDDL local extractor and PDDL+Toolbox pipelines. They require:

- All backend dependencies installed
- Toolbox service running and accessible via settings.toolbox_base_url
- A PDF file at the configured path (defaults to a known sample)

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
    run_comparison_with_reference,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures"

SMALL_FIXTURES: list[tuple[str, str, Path]] = [
    (
        "java-oo-3pgs",
        "3-page Java OO tutorial (basic text)",
        FIXTURES_DIR / "tutorials" / "java-oo-3pgs.pdf",
    ),
    (
        "java-oo-tables-pg26",
        "Single page with table structures",
        FIXTURES_DIR / "tutorials" / "java-oo-tables-pg26.pdf",
    ),
    (
        "grandezas-pg3",
        "Single page from grandezas-e-medidas presentation",
        FIXTURES_DIR / "presentations" / "grandezas-e-medidas-pg3-42.pdf",
    ),
    (
        "grandezas-pg7",
        "Single page from grandezas-e-medidas presentation",
        FIXTURES_DIR / "presentations" / "grandezas-e-medidas-pg7-42.pdf",
    ),
]


def _resolve_fixture(label: str, path: Path) -> Path:
    """Return fixture path or skip if missing."""
    if not path.exists():
        pytest.skip(f"Fixture '{label}' not found: {path}")
    return path


@pytest.fixture(params=SMALL_FIXTURES, ids=[f[0] for f in SMALL_FIXTURES])
def small_pdf(request: pytest.FixtureRequest) -> Path:
    """Parametrized fixture over all small PDFs (< 10 pages)."""
    _label, _desc, path = request.param
    return _resolve_fixture(_label, path)


@pytest.fixture
def output_tmpdir(tmp_path: Path) -> Path:
    """Return a temporary output directory for artifacts."""
    return tmp_path / "compare_out"


# ---------------------------------------------------------------------------
# E2E: full comparison run
# ---------------------------------------------------------------------------


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_run_comparison_defaults(small_pdf: Path, output_tmpdir: Path) -> None:
    """Run comparison with default parameters and verify report structure."""
    report_path = await run_comparison(
        file_path=small_pdf,
        output_dir=output_tmpdir,
        mode="normal",
    )
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))

    # Top-level keys
    assert "source_file" in report
    assert "generated_at" in report
    assert "mode" in report
    assert "engines" in report
    assert "comparison" in report
    assert "verdict" in report

    # Both engines should have run
    assert "pddl_local" in report["engines"]
    assert "pddl_toolbox" in report["engines"]

    # Check engine status
    assert report["engines"]["pddl_local"]["status"] == "ok"
    assert report["engines"]["pddl_toolbox"]["status"] == "ok"

    # Engine summaries must be present
    for engine in ("pddl_local", "pddl_toolbox"):
        summary = report["engines"][engine].get("summary", {})
        assert "block_count" in summary
        assert "section_count" in summary
        assert "formula_count" in summary
        assert "table_count" in summary

    # Comparison section
    comparison = report["comparison"]
    assert "structural" in comparison
    assert "text" in comparison
    assert "structural" in comparison
    assert comparison["structural"]["section_count"]["local"] >= 0
    assert comparison["structural"]["section_count"]["toolbox"] >= 0


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_run_comparison_verdict_present(small_pdf: Path, output_tmpdir: Path) -> None:
    """Both pipelines should produce a valid comparison report."""
    report_path = await run_comparison(
        file_path=small_pdf,
        output_dir=output_tmpdir,
        mode="normal",
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    # A verdict must be present (either EQUIVALENTE or DIVERGENTE)
    assert "verdict" in report
    assert report["engines"]["pddl_local"]["status"] == "ok"
    assert report["engines"]["pddl_toolbox"]["status"] == "ok"


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_run_comparison_with_extractor_pymupdf(
    small_pdf: Path, output_tmpdir: Path
) -> None:
    """Run comparison with 'pymupdf' local extractor."""
    report_path = await run_comparison(
        file_path=small_pdf,
        output_dir=output_tmpdir,
        mode="normal",
        extractor="pymupdf",
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["engines"]["pddl_local"]["status"] == "ok"


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_run_comparison_ocr_enabled(small_pdf: Path, output_tmpdir: Path) -> None:
    """Run comparison with OCR enabled."""
    report_path = await run_comparison(
        file_path=small_pdf,
        output_dir=output_tmpdir,
        mode="normal",
        enable_ocr=True,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["engines"]["pddl_local"]["status"] == "ok"
    assert report["engines"]["pddl_toolbox"]["status"] == "ok"


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_run_comparison_execute_plan(small_pdf: Path, output_tmpdir: Path) -> None:
    """Run comparison with plan execution enabled."""
    report_path = await run_comparison(
        file_path=small_pdf,
        output_dir=output_tmpdir,
        mode="normal",
        execute_plan=True,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    # plan execution may affect results but shouldn't crash
    assert report["engines"]["pddl_local"]["status"] == "ok"
    assert report["engines"]["pddl_toolbox"]["status"] == "ok"


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_run_comparison_artifact_files(small_pdf: Path, output_tmpdir: Path) -> None:
    """Verify that structured and canonical JSON artifacts are written."""
    await run_comparison(
        file_path=small_pdf,
        output_dir=output_tmpdir,
        mode="normal",
    )
    for name in ("pddl_local", "pddl_toolbox"):
        structured = output_tmpdir / f"{name}.structured.json"
        canonical = output_tmpdir / f"{name}.canonical.json"
        assert structured.exists(), f"Missing {structured}"
        assert canonical.exists(), f"Missing {canonical}"
        # Validate JSON
        structured_data = json.loads(structured.read_text(encoding="utf-8"))
        canonical_data = json.loads(canonical.read_text(encoding="utf-8"))
        assert isinstance(structured_data, dict)
        assert isinstance(canonical_data, dict)


# ---------------------------------------------------------------------------
# E2E: helper function consistency (smoke tests on real output)
# ---------------------------------------------------------------------------


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_helper_consistency(small_pdf: Path, output_tmpdir: Path) -> None:
    """Run comparison and verify helper functions produce consistent results."""
    report_path = await run_comparison(
        file_path=small_pdf,
        output_dir=output_tmpdir,
        mode="normal",
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))

    local_canonical_path = output_tmpdir / "pddl_local.canonical.json"
    toolbox_canonical_path = output_tmpdir / "pddl_toolbox.canonical.json"

    local = json.loads(local_canonical_path.read_text(encoding="utf-8"))
    toolbox = json.loads(toolbox_canonical_path.read_text(encoding="utf-8"))

    # _flatten_blocks must work
    local_blocks = _flatten_blocks(local)
    toolbox_blocks = _flatten_blocks(toolbox)
    assert isinstance(local_blocks, list)
    assert isinstance(toolbox_blocks, list)

    # _extract_text must work (receives the full document dict)
    local_text = _extract_text(local)
    toolbox_text = _extract_text(toolbox)
    assert isinstance(local_text, str)
    assert isinstance(toolbox_text, str)

    # _jaccard_similarity must produce a value in [0, 1]
    sim = _jaccard_similarity(local_text, toolbox_text)
    assert 0.0 <= sim <= 1.0

    # _summarize_document must match report summary
    reported_summary = report["engines"]["pddl_local"]["summary"]
    direct_summary = _summarize_document(local)
    assert reported_summary["block_count"] == direct_summary["block_count"]

    # _extract_formulas and _extract_tables must return lists
    formulas = _extract_formulas(local)
    tables = _extract_tables(toolbox)
    assert isinstance(formulas, list)
    assert isinstance(tables, list)


# ---------------------------------------------------------------------------
# E2E: reference-based comparison (fastest — uses pre-computed canonical)
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
    """Return (input, reference) or skip if either is missing."""
    if not input_path.exists():
        pytest.skip(f"Input '{label}' not found: {input_path}")
    if not ref_path.exists():
        pytest.skip(f"Reference '{label}' not found: {ref_path}")
    return (input_path, ref_path)


@pytest.fixture(params=REFERENCE_FIXTURES, ids=[f[0] for f in REFERENCE_FIXTURES])
def reference_pair(request: pytest.FixtureRequest) -> tuple[Path, Path]:
    """Parametrized fixture: (input_file, reference_canonical)."""
    _label, _desc, input_path, ref_path = request.param
    return _resolve_pair(_label, input_path, ref_path)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_reference_comparison_defaults(
    reference_pair: tuple[Path, Path], output_tmpdir: Path
) -> None:
    """Compare Toolbox output against pre-computed reference canonical."""
    input_path, ref_path = reference_pair
    report_path = await run_comparison_with_reference(
        file_path=input_path,
        reference_path=ref_path,
        output_dir=output_tmpdir,
        mode="normal",
    )
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))

    # Top-level keys
    assert "source_file" in report
    assert "reference_file" in report
    assert "engines" in report
    assert "comparison" in report
    assert "verdict" in report

    # Toolbox must have run
    assert report["engines"]["pddl_toolbox"]["status"] == "ok"

    # Comparison must have structural and text sections
    comparison = report["comparison"]
    assert "structural" in comparison
    assert "text" in comparison
    assert comparison["structural"]["section_count"]["local"] >= 0
    assert comparison["structural"]["section_count"]["toolbox"] >= 0


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_reference_comparison_artifact_files(
    reference_pair: tuple[Path, Path], output_tmpdir: Path
) -> None:
    """Verify that toolbox artifacts are written during reference comparison."""
    input_path, ref_path = reference_pair
    await run_comparison_with_reference(
        file_path=input_path,
        reference_path=ref_path,
        output_dir=output_tmpdir,
        mode="normal",
    )
    # Only toolbox artifacts are written (no local pipeline)
    structured = output_tmpdir / "pddl_toolbox.structured.json"
    canonical = output_tmpdir / "pddl_toolbox.canonical.json"
    assert structured.exists(), f"Missing {structured}"
    assert canonical.exists(), f"Missing {canonical}"
    structured_data = json.loads(structured.read_text(encoding="utf-8"))
    canonical_data = json.loads(canonical.read_text(encoding="utf-8"))
    assert isinstance(structured_data, dict)
    assert isinstance(canonical_data, dict)


# ---------------------------------------------------------------------------
# E2E: error handling
# ---------------------------------------------------------------------------


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_run_comparison_nonexistent_file(output_tmpdir: Path) -> None:
    """Passing a nonexistent file should not crash — engine gets error status."""
    fake = Path("/tmp/nonexistent_XXXXXXXXXX.pdf")
    report_path = await run_comparison(
        file_path=fake,
        output_dir=output_tmpdir,
        mode="normal",
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    # At least one engine should have an error
    assert any(
        report["engines"].get(e, {}).get("status") == "error"
        for e in ("pddl_local", "pddl_toolbox")
    )