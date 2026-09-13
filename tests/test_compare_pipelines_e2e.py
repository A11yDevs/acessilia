"""End-to-end tests for pipeline comparison (requires Toolbox and infrastructure).

These tests exercise the full comparison workflow against a real PDF file
using both the legacy and PDDL+Toolbox pipelines. They require:

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
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_PDF = (
    Path(__file__).resolve().parents[1] / "data" / "pdf" / "sample.pdf"
)


@pytest.fixture
def sample_pdf() -> Path:
    """Return path to a sample PDF that exists in the repository."""
    pdf = SAMPLE_PDF
    if not pdf.exists():
        pytest.skip(f"Sample PDF not found: {pdf}")
    return pdf


@pytest.fixture
def output_tmpdir(tmp_path: Path) -> Path:
    """Return a temporary output directory for artifacts."""
    return tmp_path / "compare_out"


# ---------------------------------------------------------------------------
# E2E: full comparison run
# ---------------------------------------------------------------------------


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_run_comparison_defaults(sample_pdf: Path, output_tmpdir: Path) -> None:
    """Run comparison with default parameters and verify report structure."""
    report_path = await run_comparison(
        file_path=sample_pdf,
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
    assert "legacy" in report["engines"]
    assert "pddl_toolbox" in report["engines"]

    # Check engine status
    assert report["engines"]["legacy"]["status"] == "ok"
    assert report["engines"]["pddl_toolbox"]["status"] == "ok"

    # Engine summaries must be present
    for engine in ("legacy", "pddl_toolbox"):
        summary = report["engines"][engine].get("summary", {})
        assert "block_count" in summary
        assert "section_count" in summary
        assert "has_formulas" in summary
        assert "has_tables" in summary

    # Comparison section
    comparison = report["comparison"]
    assert "structural" in comparison
    assert "text" in comparison
    assert "text_summary" in comparison
    assert "structural" in comparison
    assert comparison["structural"]["section_count"]["legacy"] >= 0
    assert comparison["structural"]["section_count"]["pddl_toolbox"] >= 0


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_run_comparison_verdict_equivalent(sample_pdf: Path, output_tmpdir: Path) -> None:
    """With a simple PDF, the verdict should be 'EQUIVALENTE'."""
    report_path = await run_comparison(
        file_path=sample_pdf,
        output_dir=output_tmpdir,
        mode="normal",
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert "EQUIVALENTE" in report["verdict"]


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_run_comparison_with_structurer_docling(
    sample_pdf: Path, output_tmpdir: Path
) -> None:
    """Run comparison with 'docling' structurer on the legacy pipeline."""
    report_path = await run_comparison(
        file_path=sample_pdf,
        output_dir=output_tmpdir,
        mode="normal",
        structurer="docling",
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["engines"]["legacy"]["status"] == "ok"


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_run_comparison_ocr_enabled(sample_pdf: Path, output_tmpdir: Path) -> None:
    """Run comparison with OCR enabled."""
    report_path = await run_comparison(
        file_path=sample_pdf,
        output_dir=output_tmpdir,
        mode="normal",
        enable_ocr=True,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["engines"]["legacy"]["status"] == "ok"
    assert report["engines"]["pddl_toolbox"]["status"] == "ok"


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_run_comparison_execute_plan(sample_pdf: Path, output_tmpdir: Path) -> None:
    """Run comparison with plan execution enabled."""
    report_path = await run_comparison(
        file_path=sample_pdf,
        output_dir=output_tmpdir,
        mode="normal",
        execute_plan=True,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    # plan execution may affect results but shouldn't crash
    assert report["engines"]["pddl_toolbox"]["status"] == "ok"


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_run_comparison_artifact_files(sample_pdf: Path, output_tmpdir: Path) -> None:
    """Verify that structured and canonical JSON artifacts are written."""
    await run_comparison(
        file_path=sample_pdf,
        output_dir=output_tmpdir,
        mode="normal",
    )
    for name in ("legacy", "pddl_toolbox"):
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
async def test_helper_consistency(sample_pdf: Path, output_tmpdir: Path) -> None:
    """Run comparison and verify helper functions produce consistent results."""
    report_path = await run_comparison(
        file_path=sample_pdf,
        output_dir=output_tmpdir,
        mode="normal",
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))

    legacy_canonical_path = output_tmpdir / "legacy.canonical.json"
    pddl_canonical_path = output_tmpdir / "pddl_toolbox.canonical.json"

    legacy = json.loads(legacy_canonical_path.read_text(encoding="utf-8"))
    pddl = json.loads(pddl_canonical_path.read_text(encoding="utf-8"))

    # _flatten_blocks must work
    legacy_blocks = _flatten_blocks(legacy)
    pddl_blocks = _flatten_blocks(pddl)
    assert isinstance(legacy_blocks, list)
    assert isinstance(pddl_blocks, list)

    # _extract_text must work
    legacy_text = _extract_text(legacy_blocks)
    pddl_text = _extract_text(pddl_blocks)
    assert isinstance(legacy_text, str)
    assert isinstance(pddl_text, str)

    # _jaccard_similarity must produce a value in [0, 1]
    sim = _jaccard_similarity(legacy_text, pddl_text)
    assert 0.0 <= sim <= 1.0

    # _summarize_document must match report summary
    reported_summary = report["engines"]["legacy"]["summary"]
    direct_summary = _summarize_document(legacy)
    assert reported_summary["block_count"] == direct_summary["block_count"]

    # _extract_formulas and _extract_tables must return lists
    formulas = _extract_formulas({"blocks": legacy_blocks})
    tables = _extract_tables({"blocks": pddl_blocks})
    assert isinstance(formulas, list)
    assert isinstance(tables, list)


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
        for e in ("legacy", "pddl_toolbox")
    )