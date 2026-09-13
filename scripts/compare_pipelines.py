"""Compare legacy pipeline vs PDDL+Toolbox pipeline outputs end-to-end.

Runs both pipelines on the same input document(s) and generates a detailed
diff report comparing canonical documents at structural and text levels.

Usage:
    # Single file
    poetry run python scripts/compare_pipelines.py tests/fixtures/tutorials/java-oo-3pgs.pdf

    # Batch mode (all PDFs in fixtures directory)
    poetry run python scripts/compare_pipelines.py tests/fixtures/ --batch

    # With custom output directory
    poetry run python scripts/compare_pipelines.py input.pdf -o temp/output/comparison
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.agents.orchestrator import AccessibilityOrchestrator
from backend.agents.pddl_orchestrator import PddlAccessibilityOrchestrator
from backend.pipeline.canonical_builder import build_canonical_document
from backend.pipeline.verbosity_manager import verbosity_for_mode


# ---------------------------------------------------------------------------
# Canonical document inspection helpers
# ---------------------------------------------------------------------------


def _flatten_blocks(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Yield all blocks in the document as a flat list with section path."""
    blocks: list[dict[str, Any]] = []
    sections = document.get("sections", [])

    def walk(items: list[dict[str, Any]], path: list[str]) -> None:
        for section in items:
            title = section.get("title", "")
            current_path = path + [title]
            for block in section.get("blocks", []):
                if isinstance(block, dict):
                    block = dict(block)
                    block["_section_path"] = " / ".join(current_path)
                    blocks.append(block)
            children = section.get("children", [])
            if isinstance(children, list):
                walk(children, current_path)

    walk(sections, [])
    return blocks


def _count_by_type(blocks: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for block in blocks:
        t = block.get("type", "unknown")
        counts[t] = counts.get(t, 0) + 1
    return dict(sorted(counts.items()))


def _extract_text(document: dict[str, Any]) -> str:
    """Extract all visible text from a canonical document."""
    texts: list[str] = []

    def collect(items: list[dict[str, Any]]) -> None:
        for section in items:
            for block in section.get("blocks", []):
                if isinstance(block, dict):
                    block_type = block.get("type")
                    if isinstance(block.get("text"), str):
                        texts.append(block["text"])
                    if block_type == "heading" and isinstance(block.get("title"), str):
                        texts.append(block["title"])
                    if block_type == "list" and isinstance(block.get("items"), list):
                        texts.extend(str(item) for item in block["items"])
                    if block_type == "table" and isinstance(block.get("rows"), list):
                        for row in block["rows"]:
                            if isinstance(row, list):
                                texts.extend(str(cell) for cell in row)
                    if block_type == "image" and isinstance(block.get("alt_text"), str):
                        texts.append(block["alt_text"])
                children = section.get("children", [])
                if isinstance(children, list):
                    collect(children)

    sections = document.get("sections", [])
    if isinstance(sections, list):
        collect(sections)
    return "\n".join(texts)


def _tokenize(text: str) -> set[str]:
    return set(text.lower().split())


def _jaccard_similarity(a: str, b: str) -> float:
    tokens_a = _tokenize(a)
    tokens_b = _tokenize(b)
    if not tokens_a and not tokens_b:
        return 1.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def _extract_formulas(document: dict[str, Any]) -> list[str]:
    formulas: list[str] = []
    for block in _flatten_blocks(document):
        if block.get("type") == "formula":
            text = block.get("text", "")
            if text:
                formulas.append(text)
        metadata = block.get("metadata", {})
        if isinstance(metadata, dict):
            mathml = metadata.get("mathml")
            if mathml:
                pass  # MathML is derived, not original formula text
    return formulas


def _extract_tables(document: dict[str, Any]) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    for block in _flatten_blocks(document):
        if block.get("type") == "table":
            tables.append(block)
    return tables


# ---------------------------------------------------------------------------
# Pipeline runners (sync wrappers around async orchestrators)
# ---------------------------------------------------------------------------


def _summarize_document(document: dict[str, Any]) -> dict[str, Any]:
    blocks = _flatten_blocks(document)
    text = _extract_text(document)
    return {
        "title": document.get("title"),
        "page_count": document.get("metadata", {}).get("page_count"),
        "section_count": len(document.get("sections", []))
        if isinstance(document.get("sections"), list)
        else 0,
        "block_count": len(blocks),
        "blocks_by_type": _count_by_type(blocks),
        "text_length": len(text),
        "formula_count": len(_extract_formulas(document)),
        "table_count": len(_extract_tables(document)),
    }


async def _run_legacy(file_path: Path, mode: str, tmpdir: Path) -> dict[str, Any]:
    """Run the legacy pipeline (AccessibilityOrchestrator + PyMuPDF structurer)."""
    from backend.tools import structurer as structurer_module

    original = structurer_module.get_structurer
    try:
        structurer_module.get_structurer = lambda: structurer_module.PyMuPDFStructurer()
        orchestrator = AccessibilityOrchestrator(mode=mode)
        structured = await orchestrator.executar(
            file_path=file_path,
            tmpdir=tmpdir,
            structured_output=True,
            mode=mode,
        )
    finally:
        structurer_module.get_structurer = original

    canonical = build_canonical_document(
        structured,
        title=file_path.stem,
        language="pt-BR",
        verbosity=verbosity_for_mode(mode),
        source_name=file_path.name,
        source_path=str(file_path),
        audience=["reader"],
    )
    return {"structured": structured, "canonical": canonical}


async def _run_pddl_toolbox(file_path: Path, tmpdir: Path) -> dict[str, Any]:
    """Run the PDDL pipeline with ToolboxManifestExtractor."""
    orchestrator = PddlAccessibilityOrchestrator(
        planner_backend="internal",
        preferred_plan="internal",
        execute_dry_run=True,
        enable_ocr=False,
        extractor_backend="toolbox",
    )
    structured = await orchestrator.executar(
        file_path=file_path,
        tmpdir=tmpdir,
        structured_output=True,
    )
    canonical_metadata = structured.get("canonical_metadata")
    technical_warnings = structured.get("technical_warnings")

    canonical = build_canonical_document(
        structured,
        title=file_path.stem,
        language="pt-BR",
        verbosity=verbosity_for_mode("normal"),
        source_name=file_path.name,
        source_path=str(file_path),
        audience=["reader"],
        metadata=canonical_metadata if isinstance(canonical_metadata, dict) else None,
        technical_warnings=(
            [str(item) for item in technical_warnings]
            if isinstance(technical_warnings, list)
            else None
        ),
    )
    return {"structured": structured, "canonical": canonical}


# ---------------------------------------------------------------------------
# Comparison logic
# ---------------------------------------------------------------------------


def _compare_documents(
    legacy: dict[str, Any],
    pddl: dict[str, Any],
) -> dict[str, Any]:
    """Compare two canonical documents and return a structured diff report."""
    legacy_blocks = _flatten_blocks(legacy)
    pddl_blocks = _flatten_blocks(pddl)
    legacy_text = _extract_text(legacy)
    pddl_text = _extract_text(pddl)

    legacy_by_type = _count_by_type(legacy_blocks)
    pddl_by_type = _count_by_type(pddl_blocks)

    # Type diff
    all_types = sorted(set(legacy_by_type) | set(pddl_by_type))
    type_deltas: dict[str, dict[str, int]] = {}
    for t in all_types:
        l = legacy_by_type.get(t, 0)
        p = pddl_by_type.get(t, 0)
        if l != p:
            type_deltas[t] = {"legacy": l, "pddl_toolbox": p}

    # Text similarity
    similarity = _jaccard_similarity(legacy_text, pddl_text)

    # Formula comparison
    legacy_formulas = _extract_formulas(legacy)
    pddl_formulas = _extract_formulas(pddl)

    # Table comparison
    legacy_tables = _extract_tables(legacy)
    pddl_tables = _extract_tables(pddl)

    return {
        "structural": {
            "section_count": {
                "legacy": legacy.get("metadata", {}).get("page_count"),
                "pddl_toolbox": pddl.get("metadata", {}).get("page_count"),
            },
            "block_count": {
                "legacy": len(legacy_blocks),
                "pddl_toolbox": len(pddl_blocks),
                "delta": len(pddl_blocks) - len(legacy_blocks),
            },
            "blocks_by_type_delta": type_deltas,
        },
        "text": {
            "legacy_length": len(legacy_text),
            "pddl_toolbox_length": len(pddl_text),
            "jaccard_similarity": round(similarity, 4),
        },
        "formulas": {
            "legacy_count": len(legacy_formulas),
            "pddl_toolbox_count": len(pddl_formulas),
            "common_formulas": len(
                set(legacy_formulas) & set(pddl_formulas)
            ),
        },
        "tables": {
            "legacy_count": len(legacy_tables),
            "pddl_toolbox_count": len(pddl_tables),
        },
    }


def _format_comparison_summary(
    comparison: dict[str, Any],
    legacy_elapsed: float,
    pddl_elapsed: float,
) -> str:
    """Format a human-readable summary of the comparison."""
    lines: list[str] = [
        "=" * 72,
        "  PIPELINE COMPARISON REPORT (legacy vs PDDL+Toolbox)",
        "=" * 72,
    ]

    s = comparison.get("structural", {})
    lines.append("\n[Structural]")
    lines.append(f"  Block count:    legacy={s.get('block_count', {}).get('legacy', '?')}, "
                  f"pddl+toolbox={s.get('block_count', {}).get('pddl_toolbox', '?')} "
                  f"(delta={s.get('block_count', {}).get('delta', 0):+d})")
    type_deltas = s.get("blocks_by_type_delta", {})
    if type_deltas:
        lines.append("  Block type deltas (legacy → pddl+toolbox):")
        for bt, vals in type_deltas.items():
            l = vals.get("legacy", 0)
            p = vals.get("pddl_toolbox", 0)
            delta = p - l
            sign = "+" if delta > 0 else ""
            lines.append(f"    {bt}: {l} → {p} ({sign}{delta})")

    t = comparison.get("text", {})
    lines.append(f"\n[Text]")
    lines.append(f"  Length:       legacy={t.get('legacy_length', '?')}, "
                  f"pddl+toolbox={t.get('pddl_toolbox_length', '?')}")
    sim = t.get("jaccard_similarity", 0)
    bar_len = 30
    filled = int(sim * bar_len)
    bar = "█" * filled + "░" * (bar_len - filled)
    lines.append(f"  Jaccard sim:  {sim:.1%}  [{bar}]")

    f = comparison.get("formulas", {})
    lines.append(f"\n[Formulas]")
    lines.append(f"  Count: legacy={f.get('legacy_count', '?')}, "
                  f"pddl+toolbox={f.get('pddl_toolbox_count', '?')}")
    lines.append(f"  Common: {f.get('common_formulas', '?')}")

    tbl = comparison.get("tables", {})
    lines.append(f"\n[Tables]")
    lines.append(f"  Count: legacy={tbl.get('legacy_count', '?')}, "
                  f"pddl+toolbox={tbl.get('pddl_toolbox_count', '?')}")

    lines.append(f"\n[Performance]")
    lines.append(f"  Legacy:       {legacy_elapsed:.1f}s")
    lines.append(f"  PDDL+Toolbox: {pddl_elapsed:.1f}s")
    delta_time = pddl_elapsed - legacy_elapsed
    sign = "+" if delta_time > 0 else ""
    lines.append(f"  Delta:        {sign}{delta_time:.1f}s")

    verdict = _compute_verdict(comparison)
    lines.append(f"\n[Verdict]")
    lines.append(f"  {verdict}")

    return "\n".join(lines)


def _compute_verdict(comparison: dict[str, Any]) -> str:
    """Compute a qualitative verdict based on the comparison data."""
    sim = comparison.get("text", {}).get("jaccard_similarity", 0)
    block_delta = abs(comparison.get("structural", {}).get("block_count", {}).get("delta", 0))
    type_deltas = comparison.get("structural", {}).get("blocks_by_type_delta", {})

    issues: list[str] = []
    if sim < 0.7:
        issues.append(f"baixa similaridade de texto ({sim:.1%})")
    if block_delta > 20:
        issues.append(f"grande diferença no número de blocos ({block_delta:+d})")
    if type_deltas:
        significant = [f"{k}: {v.get('legacy',0)}→{v.get('pddl_toolbox',0)}"
                       for k, v in type_deltas.items()
                       if abs(v.get('pddl_toolbox',0) - v.get('legacy',0)) > 3]
        if significant:
            issues.append(f"diferenças significativas por tipo: {', '.join(significant)}")

    if not issues:
        return "✅ EQUIVALENTE — pipelines produzem saídas estruturalmente similares"
    else:
        return f"⚠️  DIVERGENTE — {'; '.join(issues)}"


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


async def run_comparison(
    file_path: Path,
    output_dir: Path,
    mode: str,
) -> Path:
    """Run both pipelines on a single file and produce a comparison report."""
    output_dir.mkdir(parents=True, exist_ok=True)
    tmpdir = output_dir / "tmp"
    tmpdir.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "source_file": str(file_path.resolve()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "engines": {},
        "comparison": {},
    }

    # --- Legacy pipeline ---
    legacy_start = time.perf_counter()
    try:
        legacy = await _run_legacy(file_path, mode, tmpdir)
        legacy_elapsed = time.perf_counter() - legacy_start
        _write_artifacts(legacy, output_dir, "legacy")
        report["engines"]["legacy"] = {
            "status": "ok",
            "elapsed_s": round(legacy_elapsed, 2),
            "summary": _summarize_document(legacy["canonical"]),
        }
    except Exception as exc:
        legacy_elapsed = time.perf_counter() - legacy_start
        report["engines"]["legacy"] = {
            "status": "error",
            "elapsed_s": round(legacy_elapsed, 2),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }

    # --- PDDL + Toolbox pipeline ---
    pddl_start = time.perf_counter()
    try:
        pddl = await _run_pddl_toolbox(file_path, tmpdir)
        pddl_elapsed = time.perf_counter() - pddl_start
        _write_artifacts(pddl, output_dir, "pddl_toolbox")
        report["engines"]["pddl_toolbox"] = {
            "status": "ok",
            "elapsed_s": round(pddl_elapsed, 2),
            "summary": _summarize_document(pddl["canonical"]),
        }
    except Exception as exc:
        pddl_elapsed = time.perf_counter() - pddl_start
        report["engines"]["pddl_toolbox"] = {
            "status": "error",
            "elapsed_s": round(pddl_elapsed, 2),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }

    # --- Comparison ---
    legacy_ok = report["engines"].get("legacy", {}).get("status") == "ok"
    pddl_ok = report["engines"].get("pddl_toolbox", {}).get("status") == "ok"
    if legacy_ok and pddl_ok:
        comparison = _compare_documents(legacy["canonical"], pddl["canonical"])
        report["comparison"] = comparison
        verdict = _compute_verdict(comparison)
        report["verdict"] = verdict
    elif legacy_ok and not pddl_ok:
        pddl_error = report["engines"]["pddl_toolbox"].get("error", "unknown error")
        report["verdict"] = f"⚠️  PDDL+Toolbox falhou: {pddl_error}"
    elif pddl_ok and not legacy_ok:
        legacy_error = report["engines"]["legacy"].get("error", "unknown error")
        report["verdict"] = f"⚠️  Legacy falhou: {legacy_error}"
    else:
        report["verdict"] = "❌ Ambos os pipelines falharam"

    # --- Cleanup and save ---
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)

    report_path = output_dir / "comparison_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # Console summary
    print(_format_comparison_summary(
        report.get("comparison", {}),
        report["engines"].get("legacy", {}).get("elapsed_s", 0),
        report["engines"].get("pddl_toolbox", {}).get("elapsed_s", 0),
    ))

    return report_path


def _write_artifacts(
    result: dict[str, Any],
    output_dir: Path,
    engine_name: str,
) -> None:
    """Write structured and canonical JSON files to disk."""
    structured_path = output_dir / f"{engine_name}.structured.json"
    structured_path.write_text(
        json.dumps(result["structured"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    canonical_path = output_dir / f"{engine_name}.canonical.json"
    canonical_path.write_text(
        json.dumps(result["canonical"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _collect_inputs(file_or_dir: Path, recursive: bool) -> list[Path]:
    """Collect input files from a path (single file or directory)."""
    if file_or_dir.is_file():
        return [file_or_dir]
    pdfs = sorted(file_or_dir.rglob("*.pdf") if recursive else file_or_dir.glob("*.pdf"))
    images = sorted(
        file_or_dir.rglob("*.[pj][np]g") if recursive else file_or_dir.glob("*.[pj][np]g")
    )
    return pdfs + images


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="compare-pipelines",
        description="Compare legacy pipeline vs PDDL+Toolbox pipeline outputs end-to-end.",
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Input file or directory with input files.",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("temp") / "output" / "compare",
        help="Output directory for comparison reports.",
    )
    parser.add_argument(
        "--mode",
        default="normal",
        choices=["normal", "medio", "detalhado"],
        help="Verbosity mode for the legacy pipeline.",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Batch mode: process all PDFs/images in the input directory.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="When used with --batch, recurse into subdirectories.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=0,
        help="Maximum number of files to process in batch mode (0 = unlimited).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    files = _collect_inputs(args.input, args.recursive)

    if not files:
        print(f"Erro: nenhum arquivo encontrado em {args.input}")
        return 1

    if args.batch:
        output_base = args.output_dir.resolve()
        output_base.mkdir(parents=True, exist_ok=True)
        results: list[dict[str, Any]] = []
        max_files = args.max_files or len(files)

        for i, file_path in enumerate(files[:max_files]):
            rel = file_path.relative_to(args.input.resolve() if args.input.is_dir()
                                         else args.input.parent)
            stem = "_".join(rel.with_suffix("").parts)
            out_dir = output_base / stem
            print(f"\n[{i + 1}/{min(max_files, len(files))}] {rel}")

            report_path = asyncio.run(
                run_comparison(
                    file_path=file_path,
                    output_dir=out_dir,
                    mode=args.mode,
                )
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            results.append({
                "file": str(file_path),
                "status": report.get("verdict", "?"),
                "report_path": str(report_path),
            })

        summary_path = output_base / "batch_summary.json"
        summary_path.write_text(
            json.dumps(results, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        # Print batch summary
        passed = sum(1 for r in results if "EQUIVALENTE" in r.get("status", ""))
        failed = sum(1 for r in results if "DIVERGENTE" in r.get("status", ""))
        errors = sum(1 for r in results if "falhou" in r.get("status", ""))
        print("\n" + "=" * 72)
        print(f"  BATCH SUMMARY: {len(results)} files")
        print(f"  ✅ Equivalentes:  {passed}")
        print(f"  ⚠️  Divergentes:  {failed}")
        print(f"  ❌ Erros:         {errors}")
        print(f"  Relatório: {summary_path}")
        print("=" * 72)

        return 1 if errors > 0 else 0

    else:
        # Single file mode
        output_dir = args.output_dir.resolve() / args.input.stem
        asyncio.run(
            run_comparison(
                file_path=args.input.resolve(),
                output_dir=output_dir,
                mode=args.mode,
            )
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())