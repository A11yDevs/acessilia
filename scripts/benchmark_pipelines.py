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


def _count_blocks(document: dict[str, Any]) -> int:
    total = 0

    def walk_sections(sections: list[dict[str, Any]]) -> None:
        nonlocal total
        for section in sections:
            blocks = section.get("blocks", [])
            if isinstance(blocks, list):
                total += len(blocks)
            children = section.get("children", [])
            if isinstance(children, list):
                walk_sections(children)

    sections = document.get("sections", [])
    if isinstance(sections, list):
        walk_sections(sections)
    return total


def _summarize_document(document: dict[str, Any]) -> dict[str, Any]:
    text = ""
    sections = document.get("sections", [])
    if isinstance(sections, list):
        texts: list[str] = []

        def collect_from_blocks(blocks: list[dict[str, Any]]) -> None:
            for block in blocks:
                if not isinstance(block, dict):
                    continue
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

        def walk_sections(items: list[dict[str, Any]]) -> None:
            for section in items:
                blocks = section.get("blocks", [])
                if isinstance(blocks, list):
                    collect_from_blocks(blocks)
                children = section.get("children", [])
                if isinstance(children, list):
                    walk_sections(children)

        walk_sections(sections)
        text = "\n".join(texts)

    return {
        "title": document.get("title"),
        "page_count": document.get("metadata", {}).get("page_count"),
        "section_count": len(document.get("sections", []))
        if isinstance(document.get("sections"), list)
        else 0,
        "block_count": _count_blocks(document),
        "text_length": len(text),
    }


async def _run_legacy(file_path: Path, mode: str, tmpdir: Path) -> dict[str, Any]:
    orchestrator = AccessibilityOrchestrator(mode=mode)
    structured = await orchestrator.executar(
        file_path=file_path,
        tmpdir=tmpdir,
        structured_output=True,
        mode=mode,
    )
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


async def _run_pddl(file_path: Path, tmpdir: Path) -> dict[str, Any]:
    orchestrator = PddlAccessibilityOrchestrator(
        planner_backend="internal",
        preferred_plan="internal",
        execute_dry_run=True,
        enable_ocr=False,
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
        technical_warnings=
        [str(item) for item in technical_warnings]
        if isinstance(technical_warnings, list)
        else None,
    )
    return {"structured": structured, "canonical": canonical}


async def run_benchmark(file_path: Path, output_dir: Path, mode: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "source_file": str(file_path.resolve()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "engines": {},
        "comparison": {},
    }

    tmpdir = output_dir / "tmp"
    tmpdir.mkdir(parents=True, exist_ok=True)

    legacy_start = time.perf_counter()
    try:
        legacy = await _run_legacy(file_path, mode, tmpdir)
        legacy_elapsed = round((time.perf_counter() - legacy_start) * 1000)
        legacy_canonical_path = output_dir / "legacy.canonical.json"
        legacy_canonical_path.write_text(
            json.dumps(legacy["canonical"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        report["engines"]["legacy"] = {
            "status": "ok",
            "elapsed_ms": legacy_elapsed,
            "canonical_path": str(legacy_canonical_path.resolve()),
            "summary": _summarize_document(legacy["canonical"]),
        }
    except Exception as exc:
        report["engines"]["legacy"] = {
            "status": "error",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }

    pddl_start = time.perf_counter()
    try:
        pddl = await _run_pddl(file_path, tmpdir)
        pddl_elapsed = round((time.perf_counter() - pddl_start) * 1000)
        pddl_canonical_path = output_dir / "pddl.canonical.json"
        pddl_canonical_path.write_text(
            json.dumps(pddl["canonical"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        report["engines"]["pddl"] = {
            "status": "ok",
            "elapsed_ms": pddl_elapsed,
            "canonical_path": str(pddl_canonical_path.resolve()),
            "summary": _summarize_document(pddl["canonical"]),
        }
    except Exception as exc:
        report["engines"]["pddl"] = {
            "status": "error",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }

    # limpar tmpdir após benchmark
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)

    legacy_summary = report["engines"].get("legacy", {}).get("summary")
    pddl_summary = report["engines"].get("pddl", {}).get("summary")
    if isinstance(legacy_summary, dict) and isinstance(pddl_summary, dict):
        report["comparison"] = {
            "elapsed_ms_delta_pddl_minus_legacy": report["engines"]["pddl"][
                "elapsed_ms"
            ]
            - report["engines"]["legacy"]["elapsed_ms"],
            "section_count_delta": pddl_summary["section_count"]
            - legacy_summary["section_count"],
            "block_count_delta": pddl_summary["block_count"]
            - legacy_summary["block_count"],
            "text_length_delta": pddl_summary["text_length"]
            - legacy_summary["text_length"],
        }

    report_path = output_dir / "benchmark_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="benchmark-pipelines",
        description="Benchmark simples entre pipeline legacy e PDDL.",
    )
    parser.add_argument("file", type=Path, help="Arquivo de entrada (PDF/imagem)")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("temp") / "output" / "benchmark",
        help="Diretório de saída para o relatório e canônicos.",
    )
    parser.add_argument(
        "--mode",
        default="normal",
        choices=["normal", "medio", "detalhado"],
        help="Modo do pipeline legacy para comparação.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    file_path = args.file.resolve()
    if not file_path.exists():
        print(f"Erro: arquivo não encontrado: {file_path}")
        return 1

    report_path = asyncio.run(
        run_benchmark(
            file_path=file_path,
            output_dir=args.output_dir.resolve(),
            mode=args.mode,
        )
    )
    print(f"Relatório: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
