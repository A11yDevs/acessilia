from __future__ import annotations

import json
from time import perf_counter
from pathlib import Path
from typing import Any, Iterable

from core.agno_support import build_agent
from core.manifest.models import ProcessingManifest
from core.planning.comparison import build_planning_comparison
from core.planning.domain_bundle import (
    DEFAULT_DESCRIPTION_PATH,
    DEFAULT_DOMAIN_PATH,
    DomainBundle,
)
from core.planning.models import (
    NominalPlan,
    PlannerOutcome,
    PlanningComparison,
)
from core.planning.pddl_processor import (
    CompiledProblem,
    FastDownwardPlanner,
    InternalReferencePlanner,
    PddlProblemCompiler,
    PddlProblemValidator,
    validate_nominal_plan,
)


class PlannerAgent:
    """Agente Planejador Agno com ferramentas PDDL determinísticas."""

    def __init__(
        self,
        *,
        domain_path: Path = DEFAULT_DOMAIN_PATH,
        description_path: Path = DEFAULT_DESCRIPTION_PATH,
        model: Any | None = None,
    ) -> None:
        self.domain = DomainBundle.load(domain_path, description_path)
        self.compiler = PddlProblemCompiler(self.domain)
        self.validator = PddlProblemValidator(self.domain)
        self.agent = build_agent(
            name="Agente Planejador",
            instructions=(
                "Use somente as ferramentas PDDL para compilar e validar problemas.",
                "Nunca invente efeitos, métodos, custos ou dependências.",
                "O resultado é nominal; o Executor confirma cada efeito observado.",
            ),
            tools=(
                self.inspect_domain,
                self.validate_problem_text,
                self.compile_manifest_file,
                self.generate_nominal_plan_files,
            ),
            model=model,
        )

    def inspect_domain(self) -> dict[str, str]:
        """Retorna a identidade validada do par domínio/descrição."""
        return {
            "name": self.domain.name,
            "version": self.domain.version,
            "domain_sha256": self.domain.domain_sha256,
            "description_sha256": self.domain.description_sha256,
        }

    def validate_problem_text(self, problem_text: str) -> dict[str, bool]:
        """Valida requisitos estruturais obrigatórios de um problem.pddl."""
        self.validator.validate(problem_text)
        return {"valid": True}

    def compile_manifest_file(
        self,
        manifest_path: str,
        problem_path: str,
        selected_roots: list[str] | None = None,
    ) -> dict[str, str]:
        """Compila um manifesto JSON validado em um problem.pddl."""
        manifest = ProcessingManifest.model_validate_json(
            Path(manifest_path).read_text(encoding="utf-8")
        )
        compiled = self.compile_problem(
            manifest,
            selected_roots=selected_roots,
        )
        destination = Path(problem_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(compiled.text, encoding="utf-8")
        return {
            "problem_path": str(destination.resolve()),
            "problem_sha256": compiled.sha256,
        }

    def generate_nominal_plan_files(
        self,
        manifest_path: str,
        output_directory: str,
        selected_roots: list[str] | None = None,
        backend: str = "internal",
        fast_downward_path: str | None = None,
        preferred_backend: str = "internal",
    ) -> dict[str, str]:
        """Gera problema, plano(s) e comparação opcional."""
        manifest = ProcessingManifest.model_validate_json(
            Path(manifest_path).read_text(encoding="utf-8")
        )
        destination = Path(output_directory)
        destination.mkdir(parents=True, exist_ok=True)
        problem_path = destination / "problem.pddl"
        plan_path = destination / "nominal-plan.json"
        fast_downward = (
            Path(fast_downward_path) if fast_downward_path else None
        )
        comparison_path: Path | None = None
        if backend == "both":
            compiled, plans, comparison = self.compare(
                manifest,
                selected_roots=selected_roots,
                fast_downward=fast_downward,
                preferred_backend=preferred_backend,
            )
            for planner_backend, backend_plan in plans.items():
                self._write_plan(
                    destination / f"nominal-plan.{planner_backend}.json",
                    backend_plan,
                )
            comparison_path = destination / "planning-comparison.json"
            comparison_path.write_text(
                json.dumps(
                    comparison.model_dump(mode="json", by_alias=True),
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            problem_path.write_text(compiled.text, encoding="utf-8")
            if preferred_backend not in plans:
                raise RuntimeError(
                    f"Backend preferido não gerou plano: {preferred_backend}"
                )
            plan = plans[preferred_backend]
        else:
            compiled, plan = self.plan(
                manifest,
                selected_roots=selected_roots,
                backend=backend,
                fast_downward=fast_downward,
            )
        problem_path.write_text(compiled.text, encoding="utf-8")
        self._write_plan(plan_path, plan)
        result = {
            "problem_path": str(problem_path.resolve()),
            "plan_path": str(plan_path.resolve()),
            "plan_id": plan.plan_id,
        }
        if comparison_path is not None:
            result["comparison_path"] = str(comparison_path.resolve())
        return result

    def compile_problem(
        self,
        manifest: ProcessingManifest,
        *,
        selected_roots: Iterable[str] | None = None,
        unavailable_methods: Iterable[str] = (),
    ) -> CompiledProblem:
        return self.compiler.compile(
            manifest,
            selected_roots=selected_roots,
            unavailable_methods=unavailable_methods,
        )

    def plan(
        self,
        manifest: ProcessingManifest,
        *,
        selected_roots: Iterable[str] | None = None,
        unavailable_methods: Iterable[str] = (),
        backend: str = "internal",
        fast_downward: Path | None = None,
        fast_downward_alias: str | None = None,
        fast_downward_search: str = "astar(blind())",
    ) -> tuple[CompiledProblem, NominalPlan]:
        compiled = self.compile_problem(
            manifest,
            selected_roots=selected_roots,
            unavailable_methods=unavailable_methods,
        )
        planner = self._planner(
            backend=backend,
            fast_downward=fast_downward,
            fast_downward_alias=fast_downward_alias,
            fast_downward_search=fast_downward_search,
        )
        nominal_plan = planner.solve(compiled, manifest, self.domain)
        validate_nominal_plan(nominal_plan, compiled, self.domain)
        return compiled, nominal_plan

    def compare(
        self,
        manifest: ProcessingManifest,
        *,
        selected_roots: Iterable[str] | None = None,
        unavailable_methods: Iterable[str] = (),
        fast_downward: Path | None = None,
        fast_downward_alias: str | None = None,
        fast_downward_search: str = "astar(blind())",
        preferred_backend: str = "internal",
    ) -> tuple[
        CompiledProblem,
        dict[str, NominalPlan],
        PlanningComparison,
    ]:
        """Executa ambos os planners sobre a mesma projeção e os compara."""
        if preferred_backend not in {"internal", "fast-downward"}:
            raise ValueError(
                f"Backend preferido desconhecido: {preferred_backend}"
            )
        compiled = self.compile_problem(
            manifest,
            selected_roots=selected_roots,
            unavailable_methods=unavailable_methods,
        )
        plans: dict[str, NominalPlan] = {}
        outcomes: dict[str, PlannerOutcome] = {}
        configurations = (
            ("internal", None),
            ("fast-downward", fast_downward),
        )
        for backend, executable in configurations:
            started = perf_counter()
            planner_name = backend
            try:
                planner = self._planner(
                    backend=backend,
                    fast_downward=executable,
                    fast_downward_alias=fast_downward_alias,
                    fast_downward_search=fast_downward_search,
                )
                planner_name = planner.name
                plan = planner.solve(compiled, manifest, self.domain)
                validate_nominal_plan(plan, compiled, self.domain)
                runtime_ms = max(
                    0, round((perf_counter() - started) * 1000)
                )
                plans[backend] = plan
                outcomes[backend] = PlannerOutcome(
                    backend=backend,
                    status="solved",
                    planner=plan.planner,
                    runtime_ms=runtime_ms,
                    plan_file=f"nominal-plan.{backend}.json",
                    plan_id=plan.plan_id,
                    expected_total_cost=plan.expected_total_cost,
                    step_count=len(plan.steps),
                    execution_step_count=sum(
                        step.action == "execute-obligation"
                        for step in plan.steps
                    ),
                    validation_passed=True,
                    statistics=getattr(
                        planner, "last_statistics", {}
                    ),
                )
            except Exception as exc:
                runtime_ms = max(
                    0, round((perf_counter() - started) * 1000)
                )
                outcomes[backend] = PlannerOutcome(
                    backend=backend,
                    status="failed",
                    planner=planner_name,
                    runtime_ms=runtime_ms,
                    validation_passed=False,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
        comparison = build_planning_comparison(
            manifest=manifest,
            domain=self.domain,
            compiled=compiled,
            outcomes=outcomes,
            plans=plans,
            preferred_backend=preferred_backend,
        )
        return compiled, plans, comparison

    @staticmethod
    def _write_plan(destination: Path, plan: NominalPlan) -> None:
        destination.write_text(
            json.dumps(
                plan.model_dump(mode="json", by_alias=True),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _planner(
        *,
        backend: str,
        fast_downward: Path | None,
        fast_downward_alias: str | None,
        fast_downward_search: str,
    ) -> InternalReferencePlanner | FastDownwardPlanner:
        if backend == "internal":
            return InternalReferencePlanner()
        elif backend == "fast-downward":
            if fast_downward is None:
                raise ValueError(
                    "fast_downward é obrigatório para o backend fast-downward"
                )
            return FastDownwardPlanner(
                fast_downward,
                alias=fast_downward_alias,
                search=fast_downward_search,
            )
        raise ValueError(f"Backend de planejamento desconhecido: {backend}")
