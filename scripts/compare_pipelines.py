"""Compare reference canonical document vs PDDL+Toolbox pipeline output.

Loads a pre-computed reference canonical document (from tests/dataset/)
and compares it against the PDDL+Toolbox pipeline output on the same input.

Usage:
    # Single file with reference
    poetry run python scripts/compare_pipelines.py tests/dataset/input/001.pdf \
        --reference tests/dataset/intermediate/canonical-document/001.json

    # Batch mode (all dataset inputs)
    poetry run python scripts/compare_pipelines.py tests/dataset/input/ --batch \
        --reference-dir tests/dataset/intermediate/canonical-document/

    # With custom output directory
    poetry run python scripts/compare_pipelines.py input.pdf -o temp/output/comparison \
        --reference ref.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


async def _run_toolbox(
    file_path: Path,
    tmpdir: Path,
    mode: str = "normal",
    *,
    planner_backend: str = "internal",
    execute_plan: bool = False,
    enable_ocr: bool = False,
) -> dict[str, Any]:
    """Run the PDDL pipeline with ToolboxManifestExtractor."""
    orchestrator = PddlAccessibilityOrchestrator(
        planner_backend=planner_backend,
        preferred_plan=planner_backend,
        execute_dry_run=not execute_plan,
        enable_ocr=enable_ocr,
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
        verbosity=verbosity_for_mode(mode),
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


async def _run_toolbox(
    file_path: Path,
    tmpdir: Path,
    mode: str = "normal",
    *,
    planner_backend: str = "internal",
    execute_plan: bool = False,
    enable_ocr: bool = False,
) -> dict[str, Any]:
    """Run the PDDL pipeline with ToolboxManifestExtractor."""
    orchestrator = PddlAccessibilityOrchestrator(
        planner_backend=planner_backend,
        preferred_plan=planner_backend,
        execute_dry_run=not execute_plan,
        enable_ocr=enable_ocr,
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
        verbosity=verbosity_for_mode(mode),
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
    reference: dict[str, Any],
    toolbox: dict[str, Any],
) -> dict[str, Any]:
    """Compare two canonical documents and return a structured diff report."""
    ref_blocks = _flatten_blocks(reference)
    tb_blocks = _flatten_blocks(toolbox)
    ref_text = _extract_text(reference)
    tb_text = _extract_text(toolbox)

    ref_by_type = _count_by_type(ref_blocks)
    tb_by_type = _count_by_type(tb_blocks)

    # Type diff
    all_types = sorted(set(ref_by_type) | set(tb_by_type))
    type_deltas: dict[str, dict[str, int]] = {}
    for t in all_types:
        l = ref_by_type.get(t, 0)
        p = tb_by_type.get(t, 0)
        if l != p:
            type_deltas[t] = {"reference": l, "toolbox": p}

    # Text similarity
    similarity = _jaccard_similarity(ref_text, tb_text)

    # Formula comparison
    ref_formulas = _extract_formulas(reference)
    tb_formulas = _extract_formulas(toolbox)

    # Table comparison
    ref_tables = _extract_tables(reference)
    tb_tables = _extract_tables(toolbox)

    return {
        "structural": {
            "section_count": {
                "reference": len(reference.get("sections", [])),
                "toolbox": len(toolbox.get("sections", [])),
            },
            "block_count": {
                "reference": len(ref_blocks),
                "toolbox": len(tb_blocks),
                "delta": len(tb_blocks) - len(ref_blocks),
            },
            "blocks_by_type_delta": type_deltas,
        },
        "text": {
            "reference_length": len(ref_text),
            "toolbox_length": len(tb_text),
            "jaccard_similarity": round(similarity, 4),
        },
        "formulas": {
            "reference_count": len(ref_formulas),
            "toolbox_count": len(tb_formulas),
            "common_formulas": len(
                set(ref_formulas) & set(tb_formulas)
            ),
        },
        "tables": {
            "reference_count": len(ref_tables),
            "toolbox_count": len(tb_tables),
        },
    }


def _format_comparison_summary(
    comparison: dict[str, Any],
    toolbox_elapsed: float,
) -> str:
    """Format a human-readable summary of the comparison."""
    lines: list[str] = [
        "=" * 72,
        "  COMPARISON REPORT (reference canonical vs PDDL+Toolbox)",
        "=" * 72,
    ]

    s = comparison.get("structural", {})
    lines.append("\n[Structural]")
    lines.append(f"  Block count:    reference={s.get('block_count', {}).get('reference', '?')}, "
                  f"toolbox={s.get('block_count', {}).get('toolbox', '?')} "
                  f"(delta={s.get('block_count', {}).get('delta', 0):+d})")
    type_deltas = s.get("blocks_by_type_delta", {})
    if type_deltas:
        lines.append("  Block type deltas (reference \u2192 toolbox):")
        for bt, vals in type_deltas.items():
            l = vals.get("reference", 0)
            p = vals.get("toolbox", 0)
            delta = p - l
            sign = "+" if delta > 0 else ""
            lines.append(f"    {bt}: {l} \u2192 {p} ({sign}{delta})")

    t = comparison.get("text", {})
    lines.append(f"\n[Text]")
    lines.append(f"  Length:       reference={t.get('reference_length', '?')}, "
                  f"toolbox={t.get('toolbox_length', '?')}")
    sim = t.get("jaccard_similarity", 0)
    bar_len = 30
    filled = int(sim * bar_len)
    bar = "\u2588" * filled + "\u2591" * (bar_len - filled)
    lines.append(f"  Jaccard sim:  {sim:.1%}  [{bar}]")

    f = comparison.get("formulas", {})
    lines.append(f"\n[Formulas]")
    lines.append(f"  Count: reference={f.get('reference_count', '?')}, "
                  f"toolbox={f.get('toolbox_count', '?')}")
    lines.append(f"  Common: {f.get('common_formulas', '?')}")

    tbl = comparison.get("tables", {})
    lines.append(f"\n[Tables]")
    lines.append(f"  Count: reference={tbl.get('reference_count', '?')}, "
                  f"toolbox={tbl.get('toolbox_count', '?')}")

    lines.append(f"\n[Performance]")
    lines.append(f"  Toolbox:     {toolbox_elapsed:.1f}s")

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
        significant = [f"{k}: {v.get('reference',0)}\u2192{v.get('toolbox',0)}"
                       for k, v in type_deltas.items()
                       if abs(v.get('toolbox',0) - v.get('reference',0)) > 3]
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
    reference_path: Path,
    output_dir: Path,
    mode: str = "normal",
    *,
    planner_backend: str = "internal",
    execute_plan: bool = False,
    enable_ocr: bool = False,
) -> Path:
    """Run PDDL+Toolbox and compare against a reference canonical document.

    Args:
        file_path: Input file to process with Toolbox.
        reference_path: Path to the reference canonical JSON.
        output_dir: Output directory for artifacts and report.
        mode: Verbosity mode.
        planner_backend: PDDL planner backend.
        execute_plan: Whether to execute the plan.
        enable_ocr: Whether to enable OCR.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    tmpdir = output_dir / "tmp"
    tmpdir.mkdir(parents=True, exist_ok=True)

    # Load reference
    reference = json.loads(reference_path.read_text(encoding="utf-8"))

    report: dict[str, Any] = {
        "source_file": str(file_path.resolve()),
        "reference_file": str(reference_path.resolve()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "engines": {},
        "comparison": {},
    }

    # --- PDDL + Toolbox pipeline ---
    toolbox_start = time.perf_counter()
    try:
        toolbox = await _run_toolbox(
            file_path, tmpdir, mode=mode,
            planner_backend=planner_backend,
            execute_plan=execute_plan,
            enable_ocr=enable_ocr,
        )
        toolbox_elapsed = time.perf_counter() - toolbox_start
        _write_artifacts(toolbox, output_dir, "toolbox")
        report["engines"]["toolbox"] = {
            "status": "ok",
            "elapsed_s": round(toolbox_elapsed, 2),
            "summary": _summarize_document(toolbox["canonical"]),
        }
    except Exception as exc:
        toolbox_elapsed = time.perf_counter() - toolbox_start
        report["engines"]["toolbox"] = {
            "status": "error",
            "elapsed_s": round(toolbox_elapsed, 2),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }

    # --- Comparison ---
    toolbox_ok = report["engines"].get("toolbox", {}).get("status") == "ok"
    if toolbox_ok:
        comparison = _compare_documents(reference, toolbox["canonical"])
        report["comparison"] = comparison
        report["reference_summary"] = _summarize_document(reference)
        verdict = _compute_verdict(comparison)
        report["verdict"] = verdict
    else:
        tb_error = report["engines"]["toolbox"].get("error", "unknown error")
        report["verdict"] = f"\u26a0\ufe0f  Toolbox falhou: {tb_error}"

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
        report["engines"].get("toolbox", {}).get("elapsed_s", 0),
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


async def run_comparison_with_reference(
    file_path: Path,
    reference_path: Path,
    output_dir: Path,
    mode: str = "normal",
    *,
    planner_backend: str = "internal",
    execute_plan: bool = False,
    enable_ocr: bool = False,
) -> Path:
    """Run PDDL+Toolbox and compare against a reference canonical document.

    This is the fastest E2E validation: it loads a pre-computed reference
    canonical document (from tests/dataset/intermediate/canonical-document/)
    and compares it against the toolbox output, without running any local
    pipeline.

    Args:
        file_path: Input file to process with Toolbox.
        reference_path: Path to the reference canonical JSON.
        output_dir: Output directory for artifacts and report.
        mode: Verbosity mode.
        planner_backend: PDDL planner backend.
        execute_plan: Whether to execute the plan.
        enable_ocr: Whether to enable OCR.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    tmpdir = output_dir / "tmp"
    tmpdir.mkdir(parents=True, exist_ok=True)

    # Load reference
    reference = json.loads(reference_path.read_text(encoding="utf-8"))

    report: dict[str, Any] = {
        "source_file": str(file_path.resolve()),
        "reference_file": str(reference_path.resolve()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "engines": {},
        "comparison": {},
    }

    # --- PDDL + Toolbox pipeline ---
    toolbox_start = time.perf_counter()
    try:
        toolbox = await _run_pddl_toolbox(
            file_path, tmpdir, mode=mode,
            planner_backend=planner_backend,
            execute_plan=execute_plan,
            enable_ocr=enable_ocr,
        )
        toolbox_elapsed = time.perf_counter() - toolbox_start
        _write_artifacts(toolbox, output_dir, "pddl_toolbox")
        report["engines"]["pddl_toolbox"] = {
            "status": "ok",
            "elapsed_s": round(toolbox_elapsed, 2),
            "summary": _summarize_document(toolbox["canonical"]),
        }
    except Exception as exc:
        toolbox_elapsed = time.perf_counter() - toolbox_start
        report["engines"]["pddl_toolbox"] = {
            "status": "error",
            "elapsed_s": round(toolbox_elapsed, 2),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }

    # --- Comparison ---
    toolbox_ok = report["engines"].get("pddl_toolbox", {}).get("status") == "ok"
    if toolbox_ok:
        comparison = _compare_documents(reference, toolbox["canonical"])
        report["comparison"] = comparison
        report["reference_summary"] = _summarize_document(reference)
        verdict = _compute_verdict(comparison)
        report["verdict"] = verdict
    else:
        tb_error = report["engines"]["pddl_toolbox"].get("error", "unknown error")
        report["verdict"] = f"\u26a0\ufe0f  Toolbox falhou: {tb_error}"

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
        0,
        report["engines"].get("pddl_toolbox", {}).get("elapsed_s", 0),
    ))

    return report_path
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
        description="Compare reference canonical document vs PDDL+Toolbox extraction.",
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
        help="Verbosity mode for canonical document generation.",
    )
    parser.add_argument(
        "--reference",
        type=Path,
        default=None,
        help="Path to reference canonical JSON file (required for single-file mode).",
    )
    parser.add_argument(
        "--reference-dir",
        type=Path,
        default=None,
        help="Directory with reference canonical JSONs (used in batch mode).",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Batch mode: process all files in the input directory.",
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
    parser.add_argument(
        "--planner",
        default="internal",
        choices=["internal", "fast-downward"],
        help="PDDL planner backend (default: internal).",
    )
    parser.add_argument(
        "--execute-plan",
        action="store_true",
        help="Actually execute the PDDL plan (default: dry-run / simulate only).",
    )
    parser.add_argument(
        "--enable-ocr",
        action="store_true",
        help="Enable OCR in the pipeline.",
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
        ref_dir = args.reference_dir

        for i, file_path in enumerate(files[:max_files]):
            rel = file_path.relative_to(args.input.resolve() if args.input.is_dir()
                                         else args.input.parent)
            stem = "_".join(rel.with_suffix("").parts)
            out_dir = output_base / stem

            # Resolve reference path
            if ref_dir:
                ref_path = ref_dir / f"{stem}.json"
            elif args.reference:
                ref_path = args.reference
            else:
                print(f"  [{i + 1}/{min(max_files, len(files))}] {rel} -- ERRO: --reference ou --reference-dir necessario")
                results.append({"file": str(file_path), "status": "ERRO: sem referencia", "report_path": ""})
                continue

            print(f"\n[{i + 1}/{min(max_files, len(files))}] {rel}")

            report_path = asyncio.run(
                run_comparison(
                    file_path=file_path,
                    reference_path=ref_path,
                    output_dir=out_dir,
                    mode=args.mode,
                    planner_backend=args.planner,
                    execute_plan=args.execute_plan,
                    enable_ocr=args.enable_ocr,
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
        errors = sum(1 for r in results if "falhou" in r.get("status", "") or "ERRO" in r.get("status", ""))
        print("\n" + "=" * 72)
        print(f"  BATCH SUMMARY: {len(results)} files")
        print(f"  \u2705 Equivalentes:  {passed}")
        print(f"  \u26a0\ufe0f  Divergentes:  {failed}")
        print(f"  \u274c Erros:         {errors}")
        print(f"  Relatorio: {summary_path}")
        print("=" * 72)

        return 1 if errors > 0 else 0

    else:
        # Single file mode
        if not args.reference:
            print("Erro: --reference e obrigatorio no modo single-file")
            return 1
        output_dir = args.output_dir.resolve() / args.input.stem
        asyncio.run(
            run_comparison(
                file_path=args.input.resolve(),
                reference_path=args.reference,
                output_dir=output_dir,
                mode=args.mode,
                planner_backend=args.planner,
                execute_plan=args.execute_plan,
                enable_ocr=args.enable_ocr,
            )
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())