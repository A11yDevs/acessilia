from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from importlib import import_module
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
        extractor_backend="pymupdf",
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


def _export_outputs(
    canonical: dict[str, Any],
    output_dir: Path,
    engine_name: str,
    export_formats: list[str],
) -> tuple[dict[str, str], list[str]]:
    exported_paths: dict[str, str] = {}
    export_errors: list[str] = []
    output_dir.mkdir(parents=True, exist_ok=True)

    for fmt in export_formats:
        output_path = output_dir / f"{engine_name}.{fmt}"
        try:
            if fmt == "pdf":
                export_pdf = getattr(
                    import_module("backend.export.exporters.pdf_exporter"),
                    "export_pdf",
                )
                export_pdf(canonical, output_path, title=canonical.get("title", engine_name))
            elif fmt == "txt":
                export_txt = getattr(
                    import_module("backend.export.exporters.txt_exporter"),
                    "export_txt",
                )
                export_txt(canonical, output_path, title=canonical.get("title", engine_name))
            elif fmt == "docx":
                export_docx = getattr(
                    import_module("backend.export.exporters.docx_exporter"),
                    "export_docx",
                )
                export_docx(canonical, output_path, filename=canonical.get("title", engine_name))
            else:
                export_errors.append(f"Formato nao suportado no benchmark: {fmt}")
                continue
            exported_paths[fmt] = str(output_path.resolve())
        except Exception as exc:  # pragma: no cover - depende de ambiente externo
            export_errors.append(f"{fmt}: {type(exc).__name__}: {exc}")

    return exported_paths, export_errors


async def run_benchmark(
    file_path: Path,
    output_dir: Path,
    mode: str,
    export_formats: list[str],
) -> Path:
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
        legacy_structured_path = output_dir / "legacy.structured.json"
        legacy_structured_path.write_text(
            json.dumps(legacy["structured"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        legacy_canonical_path = output_dir / "legacy.canonical.json"
        legacy_canonical_path.write_text(
            json.dumps(legacy["canonical"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        legacy_exports, legacy_export_errors = _export_outputs(
            canonical=legacy["canonical"],
            output_dir=output_dir,
            engine_name="legacy",
            export_formats=export_formats,
        )
        report["engines"]["legacy"] = {
            "status": "ok",
            "elapsed_ms": legacy_elapsed,
            "structured_path": str(legacy_structured_path.resolve()),
            "canonical_path": str(legacy_canonical_path.resolve()),
            "exports": legacy_exports,
            "export_errors": legacy_export_errors,
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
        pddl_structured_path = output_dir / "pddl.structured.json"
        pddl_structured_path.write_text(
            json.dumps(pddl["structured"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        pddl_canonical_path = output_dir / "pddl.canonical.json"
        pddl_canonical_path.write_text(
            json.dumps(pddl["canonical"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        pddl_exports, pddl_export_errors = _export_outputs(
            canonical=pddl["canonical"],
            output_dir=output_dir,
            engine_name="pddl",
            export_formats=export_formats,
        )
        report["engines"]["pddl"] = {
            "status": "ok",
            "elapsed_ms": pddl_elapsed,
            "structured_path": str(pddl_structured_path.resolve()),
            "canonical_path": str(pddl_canonical_path.resolve()),
            "exports": pddl_exports,
            "export_errors": pddl_export_errors,
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
    parser.add_argument(
        "--export-formats",
        default="pdf",
        help="Formatos de saida por metodo, separados por virgula (ex.: pdf,txt,docx).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    file_path = args.file.resolve()
    if not file_path.exists():
        print(f"Erro: arquivo não encontrado: {file_path}")
        return 1

    export_formats = [
        item.strip().lower()
        for item in args.export_formats.split(",")
        if item.strip()
    ]
    if not export_formats:
        export_formats = ["pdf"]

    report_path = asyncio.run(
        run_benchmark(
            file_path=file_path,
            output_dir=args.output_dir.resolve(),
            mode=args.mode,
            export_formats=export_formats,
        )
    )
    print(f"Relatório: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
