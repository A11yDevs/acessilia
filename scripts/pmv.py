#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any

from backend.core.agents.informational_structural import InformationalStructuralAgent
from backend.core.execution.executor import ExecutorAgent, MethodRegistry
from backend.core.manifest.docling_extractor import DoclingManifestExtractor
from backend.core.manifest.models import ProcessingManifest
from backend.core.manifest.schema import validate_manifest
from backend.core.planning.domain_bundle import (
    DEFAULT_DESCRIPTION_PATH,
    DEFAULT_DOMAIN_PATH,
    DomainBundle,
)
from backend.core.planning.models import NominalPlan
from backend.core.planning.planner_agent import PlannerAgent


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST_SCHEMA = (
    PROJECT_ROOT / "schemas" / "processing_manifest.schema.json"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="a11y-pmv",
        description="PMV Agno + Docling + PDDL para processamento acessível.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    manifest = subparsers.add_parser(
        "manifest",
        help="Executa o Agente IE e gera o manifesto.",
    )
    manifest.add_argument("document", type=Path)
    manifest.add_argument("-o", "--output", type=Path, required=True)
    manifest.add_argument("--language", default="pt-BR")
    manifest.add_argument("--no-ocr", action="store_true")

    plan = subparsers.add_parser(
        "plan",
        help="Compila problem.pddl e gera o plano nominal JSON.",
    )
    _add_plan_arguments(plan)

    execute = subparsers.add_parser(
        "execute",
        help="Executa ou simula o plano em um Agno Workflow.",
    )
    execute.add_argument("manifest", type=Path)
    execute.add_argument("plan", type=Path)
    execute.add_argument("-o", "--output-directory", type=Path, required=True)
    execute.add_argument(
        "--live",
        action="store_true",
        help="Executa handlers reais; sem esta opção, faz dry-run.",
    )
    execute.add_argument(
        "--handler-module",
        help=(
            "Módulo Python com register_handlers(registry), necessário para "
            "registrar ferramentas reais."
        ),
    )
    _add_domain_arguments(execute)

    pipeline = subparsers.add_parser(
        "pipeline",
        help="Executa IE, compilação PDDL e planejamento em uma chamada.",
    )
    pipeline.add_argument("document", type=Path)
    pipeline.add_argument("-o", "--output-directory", type=Path, required=True)
    pipeline.add_argument("--language", default="pt-BR")
    pipeline.add_argument("--no-ocr", action="store_true")
    pipeline.add_argument(
        "--execute-dry-run",
        action="store_true",
        help="Também valida o plano em um workflow sem confirmar efeitos.",
    )
    _add_planner_backend_arguments(pipeline)
    _add_domain_arguments(pipeline)
    return parser


def _add_plan_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("manifest", type=Path)
    parser.add_argument("-o", "--output-directory", type=Path, required=True)
    parser.add_argument(
        "--select",
        action="append",
        dest="selected_roots",
        help="Obrigação-raiz; pode ser repetida. Padrão: selecionadas ou todas.",
    )
    parser.add_argument(
        "--unavailable-method",
        action="append",
        default=[],
        help="Método indisponível nesta execução; pode ser repetido.",
    )
    _add_planner_backend_arguments(parser)
    _add_domain_arguments(parser)


def _add_planner_backend_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--planner",
        choices=("internal", "fast-downward", "both"),
        default="internal",
        help=(
            "Backend de planejamento. 'both' executa os dois sobre o mesmo "
            "problem.pddl e gera planning-comparison.json."
        ),
    )
    parser.add_argument(
        "--preferred-plan",
        choices=("internal", "fast-downward"),
        default="internal",
        help=(
            "No modo both, define qual plano também será gravado como "
            "nominal-plan.json e usado pelo Executor."
        ),
    )
    parser.add_argument("--fast-downward", type=Path)
    parser.add_argument(
        "--fast-downward-search",
        default="astar(blind())",
        help="Busca compatível com axiomas, usada quando --fast-downward-alias não é informado.",
    )
    parser.add_argument("--fast-downward-alias")


def _add_domain_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--domain", type=Path, default=DEFAULT_DOMAIN_PATH)
    parser.add_argument(
        "--domain-description",
        type=Path,
        default=DEFAULT_DESCRIPTION_PATH,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "manifest":
            _run_manifest(args.document, args.output, args.language, args.no_ocr)
        elif args.command == "plan":
            _run_plan(args)
        elif args.command == "execute":
            _run_execute(args)
        elif args.command == "pipeline":
            _run_pipeline(args)
        else:
            raise ValueError(f"Comando desconhecido: {args.command}")
    except Exception as exc:
        print(f"Erro: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


def _run_manifest(
    document: Path,
    output: Path,
    language: str,
    no_ocr: bool,
) -> ProcessingManifest:
    agent = InformationalStructuralAgent(
        DoclingManifestExtractor(enable_ocr=not no_ocr)
    )
    manifest = agent.process(document.resolve(), language=language)
    payload = manifest.model_dump(mode="json", by_alias=True)
    errors = validate_manifest(payload, DEFAULT_MANIFEST_SCHEMA)
    if errors:
        raise ValueError("Manifesto inválido: " + "; ".join(errors))
    _write_json(output, payload)
    print(f"Manifesto: {output.resolve()}")
    return manifest


def _planner_from_args(args: argparse.Namespace) -> PlannerAgent:
    return PlannerAgent(
        domain_path=args.domain,
        description_path=args.domain_description,
    )


def _run_plan(args: argparse.Namespace) -> tuple[Path, Path]:
    manifest = ProcessingManifest.model_validate_json(
        args.manifest.read_text(encoding="utf-8")
    )
    planner = _planner_from_args(args)
    output = args.output_directory.resolve()
    output.mkdir(parents=True, exist_ok=True)
    problem_path = output / "problem.pddl"
    plan_path = output / "nominal-plan.json"
    if args.planner == "both":
        compiled, plans, comparison = planner.compare(
            manifest,
            selected_roots=args.selected_roots,
            unavailable_methods=args.unavailable_method,
            fast_downward=args.fast_downward,
            fast_downward_alias=args.fast_downward_alias,
            fast_downward_search=args.fast_downward_search,
            preferred_backend=args.preferred_plan,
        )
        for backend, backend_plan in plans.items():
            backend_path = output / f"nominal-plan.{backend}.json"
            _write_json(
                backend_path,
                backend_plan.model_dump(mode="json", by_alias=True),
            )
            print(f"Plano {backend}: {backend_path}")
        comparison_path = output / "planning-comparison.json"
        _write_json(
            comparison_path,
            comparison.model_dump(mode="json", by_alias=True),
        )
        problem_path.write_text(compiled.text, encoding="utf-8")
        print(f"Comparação: {comparison_path}")
        print(f"Veredito: {comparison.comparison.verdict}")
        if args.preferred_plan not in plans:
            raise RuntimeError(
                "O backend preferido não produziu plano válido: "
                f"{args.preferred_plan}. Consulte {comparison_path}."
            )
        nominal_plan = plans[args.preferred_plan]
    else:
        compiled, nominal_plan = planner.plan(
            manifest,
            selected_roots=args.selected_roots,
            unavailable_methods=args.unavailable_method,
            backend=args.planner,
            fast_downward=args.fast_downward,
            fast_downward_alias=args.fast_downward_alias,
            fast_downward_search=args.fast_downward_search,
        )
    problem_path.write_text(compiled.text, encoding="utf-8")
    _write_json(
        plan_path,
        nominal_plan.model_dump(mode="json", by_alias=True),
    )
    print(f"Problema PDDL: {problem_path}")
    print(f"Plano nominal: {plan_path}")
    return problem_path, plan_path


def _run_execute(args: argparse.Namespace) -> tuple[Path, Path]:
    manifest = ProcessingManifest.model_validate_json(
        args.manifest.read_text(encoding="utf-8")
    )
    plan = NominalPlan.model_validate_json(args.plan.read_text(encoding="utf-8"))
    registry = MethodRegistry()
    if args.handler_module:
        module = importlib.import_module(args.handler_module)
        register = getattr(module, "register_handlers", None)
        if not callable(register):
            raise ValueError(
                "O módulo deve expor register_handlers(registry)"
            )
        register(registry)
    executor = ExecutorAgent(
        registry,
        domain=DomainBundle.load(args.domain, args.domain_description),
    )
    updated_manifest, report = executor.execute(
        plan,
        manifest,
        dry_run=not args.live,
    )
    output = args.output_directory.resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "manifest-after-execution.json"
    report_path = output / "execution-report.json"
    _write_json(
        manifest_path,
        updated_manifest.model_dump(mode="json", by_alias=True),
    )
    _write_json(report_path, report.model_dump(mode="json", by_alias=True))
    print(f"Manifesto resultante: {manifest_path}")
    print(f"Relatório de execução: {report_path}")
    return manifest_path, report_path


def _run_pipeline(args: argparse.Namespace) -> None:
    output = args.output_directory.resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "processing-manifest.json"
    _run_manifest(
        args.document,
        manifest_path,
        args.language,
        args.no_ocr,
    )
    plan_args = argparse.Namespace(
        manifest=manifest_path,
        output_directory=output,
        selected_roots=None,
        unavailable_method=[],
        planner=args.planner,
        fast_downward=args.fast_downward,
        fast_downward_alias=args.fast_downward_alias,
        fast_downward_search=args.fast_downward_search,
        preferred_plan=args.preferred_plan,
        domain=args.domain,
        domain_description=args.domain_description,
    )
    _, plan_path = _run_plan(plan_args)
    if args.execute_dry_run:
        execute_args = argparse.Namespace(
            manifest=manifest_path,
            plan=plan_path,
            output_directory=output,
            live=False,
            handler_module=None,
            domain=args.domain,
            domain_description=args.domain_description,
        )
        _run_execute(execute_args)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
