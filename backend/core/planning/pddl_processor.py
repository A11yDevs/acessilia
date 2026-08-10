from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from backend.core.manifest.models import Obligation, ProcessingManifest
from backend.core.planning.domain_bundle import DomainBundle
from backend.core.planning.models import DomainIdentity, NominalPlan, PlanStep


PDDL_SYMBOL = re.compile(r"^[a-z][a-z0-9-]*$")


@dataclass(frozen=True)
class PlanningProjection:
    problem_name: str
    selected: tuple[str, ...]
    obligations: dict[str, Obligation]
    obligation_symbols: dict[str, str]
    kind_symbols: dict[str, str]
    method_symbols: dict[str, str]
    reverse_obligations: dict[str, str]
    reverse_kinds: dict[str, str]
    reverse_methods: dict[str, str]
    available_methods: frozenset[str]
    initially_satisfied: frozenset[str]
    initially_pending: frozenset[str]
    tried: frozenset[tuple[str, str]]
    lifecycle: str

    def cost(self, obligation_id: str, method: str) -> int:
        return self.obligations[obligation_id].method_costs.get(method, 50)


@dataclass(frozen=True)
class CompiledProblem:
    text: str
    sha256: str
    manifest_sha256: str
    projection: PlanningProjection


class PddlProblemCompiler:
    def __init__(self, domain: DomainBundle) -> None:
        self.domain = domain

    def compile(
        self,
        manifest: ProcessingManifest,
        *,
        selected_roots: Iterable[str] | None = None,
        unavailable_methods: Iterable[str] = (),
    ) -> CompiledProblem:
        obligations = {item.id: item for item in manifest.obligations}
        roots = self._resolve_roots(obligations, selected_roots)
        selected = self._dependency_closure(obligations, roots)
        selected_obligations = {key: obligations[key] for key in selected}

        obligation_symbols = _symbol_table(selected)
        kinds = sorted({item.kind for item in selected_obligations.values()})
        methods = sorted(
            {
                method
                for item in selected_obligations.values()
                for method in item.admissible_methods
            }
        )
        kind_symbols = _symbol_table(kinds)
        method_symbols = _symbol_table(methods)
        unavailable = set(unavailable_methods)
        known_manifest_methods = {
            method
            for item in obligations.values()
            for method in item.admissible_methods
        }
        unknown_unavailable = unavailable - known_manifest_methods
        if unknown_unavailable:
            raise ValueError(
                f"Métodos indisponíveis desconhecidos: {sorted(unknown_unavailable)}"
            )
        available_methods = frozenset(set(methods) - unavailable)

        tried = frozenset(
            (item.id, attempt.method)
            for item in selected_obligations.values()
            for attempt in item.attempts
            if attempt.status in {"failed", "rejected"}
        )
        initially_satisfied = frozenset(
            item.id
            for item in selected_obligations.values()
            if item.status == "satisfied"
        )
        initially_pending = frozenset(selected) - initially_satisfied
        self._validate_causal_state(selected_obligations, initially_satisfied)
        self._validate_methods(
            selected_obligations,
            initially_pending,
            available_methods,
            tried,
        )

        lifecycle = (
            "queued"
            if manifest.status in {"extracted", "planned"}
            else "processing"
        )
        if manifest.status == "completed":
            raise ValueError("O manifesto já está concluído")

        projection = PlanningProjection(
            problem_name=_pddl_symbol(manifest.manifest_id),
            selected=tuple(selected),
            obligations=selected_obligations,
            obligation_symbols=obligation_symbols,
            kind_symbols=kind_symbols,
            method_symbols=method_symbols,
            reverse_obligations={value: key for key, value in obligation_symbols.items()},
            reverse_kinds={value: key for key, value in kind_symbols.items()},
            reverse_methods={value: key for key, value in method_symbols.items()},
            available_methods=available_methods,
            initially_satisfied=initially_satisfied,
            initially_pending=initially_pending,
            tried=tried,
            lifecycle=lifecycle,
        )
        text = self._render(projection)
        PddlProblemValidator(self.domain).validate(text, projection)
        manifest_payload = manifest.model_dump(mode="json", by_alias=True)
        return CompiledProblem(
            text=text,
            sha256=_text_sha256(text),
            manifest_sha256=_json_sha256(manifest_payload),
            projection=projection,
        )

    @staticmethod
    def _resolve_roots(
        obligations: dict[str, Obligation],
        selected_roots: Iterable[str] | None,
    ) -> set[str]:
        if selected_roots is None:
            explicitly_selected = {
                item.id for item in obligations.values() if item.selected
            }
            roots = explicitly_selected or {
                item.id
                for item in obligations.values()
                if item.status != "satisfied"
            }
        else:
            roots = set(selected_roots)
        unknown = roots - set(obligations)
        if unknown:
            raise ValueError(f"Obrigações-raiz desconhecidas: {sorted(unknown)}")
        return roots

    @staticmethod
    def _dependency_closure(
        obligations: dict[str, Obligation],
        roots: set[str],
    ) -> list[str]:
        selected: set[str] = set()

        def visit(obligation_id: str) -> None:
            if obligation_id in selected:
                return
            selected.add(obligation_id)
            for dependency in obligations[obligation_id].dependencies:
                visit(dependency)

        for root in sorted(roots):
            visit(root)
        return sorted(selected)

    @staticmethod
    def _validate_causal_state(
        obligations: dict[str, Obligation],
        satisfied: frozenset[str],
    ) -> None:
        for obligation_id in satisfied:
            unsatisfied = set(obligations[obligation_id].dependencies) - satisfied
            if unsatisfied:
                raise ValueError(
                    f"Estado causalmente inconsistente: {obligation_id} está "
                    f"satisfeita, mas depende de {sorted(unsatisfied)}"
                )

    @staticmethod
    def _validate_methods(
        obligations: dict[str, Obligation],
        pending: frozenset[str],
        available: frozenset[str],
        tried: frozenset[tuple[str, str]],
    ) -> None:
        for obligation_id in pending:
            candidates = {
                method
                for method in obligations[obligation_id].admissible_methods
                if method in available and (obligation_id, method) not in tried
            }
            if not candidates:
                raise ValueError(
                    "Nenhum método disponível, admissível e não tentado para "
                    f"{obligation_id}"
                )

    def _render(self, projection: PlanningProjection) -> str:
        obligation_objects = " ".join(
            projection.obligation_symbols[item] for item in projection.selected
        )
        kind_objects = " ".join(
            projection.kind_symbols[item]
            for item in sorted(projection.kind_symbols)
        )
        method_objects = " ".join(
            projection.method_symbols[item]
            for item in sorted(projection.method_symbols)
        )
        init: list[str] = [f"    ({projection.lifecycle})", "    (= (total-cost) 0)"]

        for obligation_id in projection.selected:
            item = projection.obligations[obligation_id]
            o = projection.obligation_symbols[obligation_id]
            k = projection.kind_symbols[item.kind]
            init.extend((f"    (selected {o})", f"    (kind-of {o} {k})"))
            state = (
                "satisfied"
                if obligation_id in projection.initially_satisfied
                else "pending"
            )
            init.append(f"    ({state} {o})")
            for dependency in sorted(item.dependencies):
                init.append(
                    "    (depends-on "
                    f"{o} {projection.obligation_symbols[dependency]})"
                )
            for method in sorted(item.admissible_methods):
                m = projection.method_symbols[method]
                if method in projection.available_methods:
                    init.append(f"    (available {m})")
                init.extend(
                    (
                        f"    (supports {m} {k})",
                        f"    (admissible {m} {o})",
                        f"    (= (execution-cost {m} {o}) "
                        f"{projection.cost(obligation_id, method)})",
                    )
                )
                if (obligation_id, method) in projection.tried:
                    init.append(f"    (tried {o} {m})")

        init = list(dict.fromkeys(init))
        object_lines: list[str] = []
        if obligation_objects:
            object_lines.append(f"    {obligation_objects} - obligation")
        if kind_objects:
            object_lines.append(f"    {kind_objects} - obligationkind")
        if method_objects:
            object_lines.append(f"    {method_objects} - method")
        rendered_objects = "\n".join(object_lines)
        if rendered_objects:
            rendered_objects += "\n"
        return (
            f"(define (problem {projection.problem_name})\n"
            f"  (:domain {self.domain.name})\n\n"
            "  (:objects\n"
            f"{rendered_objects}"
            "  )\n\n"
            "  (:init\n"
            + "\n".join(init)
            + "\n  )\n\n"
            "  (:goal (completed))\n"
            "  (:metric minimize (total-cost))\n"
            ")\n"
        )


class PddlProblemValidator:
    def __init__(self, domain: DomainBundle) -> None:
        self.domain = domain

    def validate(
        self,
        problem_text: str,
        projection: PlanningProjection | None = None,
    ) -> None:
        if _parenthesis_balance(problem_text) != 0:
            raise ValueError("Parênteses desbalanceados no problem.pddl")
        required = (
            f"(:domain {self.domain.name})",
            "(:goal (completed))",
            "(:metric minimize (total-cost))",
            "(= (total-cost) 0)",
        )
        missing = [fragment for fragment in required if fragment not in problem_text]
        if missing:
            raise ValueError(
                "problem.pddl não cumpre o contrato do domínio: "
                + ", ".join(missing)
            )
        if projection is None:
            return
        for obligation_id in projection.selected:
            symbol = projection.obligation_symbols[obligation_id]
            if f"(selected {symbol})" not in problem_text:
                raise ValueError(f"Obrigação selecionada ausente: {obligation_id}")
        if "(queued)" in problem_text and "(processing)" in problem_text:
            raise ValueError("O problema não pode estar queued e processing")


class InternalReferencePlanner:
    name = "internal-reference"

    def __init__(self) -> None:
        self.last_statistics: dict[str, int | float | str | bool] = {}

    def solve(
        self,
        compiled: CompiledProblem,
        manifest: ProcessingManifest,
        domain: DomainBundle,
    ) -> NominalPlan:
        projection = compiled.projection
        satisfied = set(projection.initially_satisfied)
        remaining = set(projection.initially_pending)
        steps: list[PlanStep] = []
        if projection.lifecycle == "queued":
            steps.append(PlanStep(index=len(steps), action="start-job"))

        while remaining:
            ready = sorted(
                obligation_id
                for obligation_id in remaining
                if set(
                    projection.obligations[obligation_id].dependencies
                ).issubset(satisfied)
            )
            if not ready:
                raise ValueError("Não foi possível ordenar as obrigações selecionadas")
            obligation_id = ready[0]
            item = projection.obligations[obligation_id]
            methods = [
                method
                for method in item.admissible_methods
                if method in projection.available_methods
                and (obligation_id, method) not in projection.tried
            ]
            method = min(methods, key=lambda value: (projection.cost(obligation_id, value), value))
            steps.append(
                PlanStep(
                    index=len(steps),
                    action="execute-obligation",
                    obligation_id=obligation_id,
                    obligation_kind=item.kind,
                    method=method,
                    expected_cost=projection.cost(obligation_id, method),
                )
            )
            satisfied.add(obligation_id)
            remaining.remove(obligation_id)
        steps.append(PlanStep(index=len(steps), action="complete-job"))
        _validate_action_sequence(steps, projection)
        self.last_statistics = {
            "selected_obligations": len(projection.selected),
            "execution_steps": sum(
                step.action == "execute-obligation" for step in steps
            ),
            "algorithm": "topological-order-plus-minimum-local-cost",
        }
        return _build_plan(
            manifest=manifest,
            domain=domain,
            compiled=compiled,
            planner=self.name,
            steps=steps,
        )


class FastDownwardPlanner:
    name = "fast-downward"

    def __init__(
        self,
        executable: Path,
        *,
        alias: str | None = None,
        search: str = "astar(blind())",
        timeout_seconds: int = 300,
    ) -> None:
        self.executable = executable.resolve()
        self.alias = alias
        self.search = search
        self.timeout_seconds = timeout_seconds
        self.last_statistics: dict[str, int | float | str | bool] = {}

    def solve(
        self,
        compiled: CompiledProblem,
        manifest: ProcessingManifest,
        domain: DomainBundle,
    ) -> NominalPlan:
        if not self.executable.is_file():
            raise FileNotFoundError(
                f"Fast Downward não encontrado: {self.executable}"
            )
        with tempfile.TemporaryDirectory(prefix="acessilia-pddl-") as temp_dir:
            workdir = Path(temp_dir)
            problem_path = workdir / "problem.pddl"
            problem_path.write_text(compiled.text, encoding="utf-8")
            planner_options = (
                ["--alias", self.alias]
                if self.alias
                else ["--search", self.search]
            )
            executable_command = (
                [sys.executable, str(self.executable)]
                if self.executable.suffix == ".py"
                else [str(self.executable)]
            )
            completed = subprocess.run(
                [
                    *executable_command,
                    str(domain.domain_path),
                    str(problem_path),
                    *planner_options,
                ],
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
            plan_paths = sorted(
                workdir.glob("sas_plan*"),
                key=lambda p: int(p.suffix[1:]) if p.suffix and p.suffix[1:].isdigit() else 0,
            )
            if completed.returncode != 0 or not plan_paths:
                detail = (completed.stderr or completed.stdout).strip()
                raise RuntimeError(
                    "Fast Downward não produziu um plano"
                    + (f": {detail[-1000:]}" if detail else "")
                )
            self.last_statistics = _parse_fast_downward_statistics(
                completed.stdout
            )
            self.last_statistics["return_code"] = completed.returncode
            self.last_statistics["configuration"] = (
                f"alias={self.alias}"
                if self.alias
                else f"search={self.search}"
            )
            steps = _parse_fast_downward_plan(
                plan_paths[-1].read_text(encoding="utf-8"),
                compiled.projection,
            )
        return _build_plan(
            manifest=manifest,
            domain=domain,
            compiled=compiled,
            planner=(
                f"{self.name}:alias={self.alias}"
                if self.alias
                else f"{self.name}:search={self.search}"
            ),
            steps=steps,
        )


def _parse_fast_downward_plan(
    text: str,
    projection: PlanningProjection,
) -> list[PlanStep]:
    steps: list[PlanStep] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(";"):
            continue
        match = re.match(r"^\(([^()]+)\)", line)
        if not match:
            continue
        tokens = match.group(1).split()
        action = tokens[0]
        if action == "start-job" and len(tokens) == 1:
            steps.append(PlanStep(index=len(steps), action="start-job"))
        elif action == "complete-job" and len(tokens) == 1:
            steps.append(PlanStep(index=len(steps), action="complete-job"))
        elif action == "execute-obligation" and len(tokens) == 4:
            obligation_id = projection.reverse_obligations[tokens[1]]
            kind = projection.reverse_kinds[tokens[2]]
            method = projection.reverse_methods[tokens[3]]
            steps.append(
                PlanStep(
                    index=len(steps),
                    action="execute-obligation",
                    obligation_id=obligation_id,
                    obligation_kind=kind,
                    method=method,
                    expected_cost=projection.cost(obligation_id, method),
                )
            )
        else:
            raise ValueError(f"Ação inesperada no plano: {line}")
    _validate_action_sequence(steps, projection)
    return steps


def _validate_action_sequence(
    steps: list[PlanStep],
    projection: PlanningProjection,
) -> None:
    processing = projection.lifecycle == "processing"
    completed = False
    satisfied = set(projection.initially_satisfied)
    for step in steps:
        if completed:
            raise ValueError("O plano contém ação depois de complete-job")
        if step.action == "start-job":
            if processing or projection.lifecycle != "queued":
                raise ValueError("start-job aplicado fora do estado queued")
            processing = True
        elif step.action == "execute-obligation":
            assert step.obligation_id is not None
            assert step.method is not None
            if step.obligation_id not in projection.obligations:
                raise ValueError(
                    f"Obrigação não selecionada: {step.obligation_id}"
                )
            item = projection.obligations[step.obligation_id]
            if step.obligation_id in satisfied:
                raise ValueError(
                    f"Obrigação executada mais de uma vez: {step.obligation_id}"
                )
            if not processing or not set(item.dependencies).issubset(
                satisfied
            ):
                raise ValueError(
                    f"Precondições não satisfeitas para {step.obligation_id}"
                )
            if step.obligation_kind != item.kind:
                raise ValueError(
                    f"Tipo incorreto para {step.obligation_id}: "
                    f"{step.obligation_kind}"
                )
            if step.method not in item.admissible_methods:
                raise ValueError(f"Método não admissível: {step.method}")
            if step.method not in projection.available_methods:
                raise ValueError(f"Método indisponível: {step.method}")
            if (step.obligation_id, step.method) in projection.tried:
                raise ValueError(
                    f"Método já tentado: {step.obligation_id}/{step.method}"
                )
            expected_cost = projection.cost(
                step.obligation_id, step.method
            )
            if step.expected_cost != expected_cost:
                raise ValueError(
                    f"Custo incorreto para {step.obligation_id}: "
                    f"{step.expected_cost}; esperado {expected_cost}"
                )
            satisfied.add(step.obligation_id)
        elif step.action == "complete-job":
            if not processing:
                raise ValueError("complete-job aplicado fora de processing")
            if not set(projection.selected).issubset(satisfied):
                raise ValueError("complete-job antes de satisfazer o fechamento")
            processing = False
            completed = True
    if not steps or steps[-1].action != "complete-job":
        raise ValueError("Plano externo não termina com complete-job")


def validate_nominal_plan(
    plan: NominalPlan,
    compiled: CompiledProblem,
    domain: DomainBundle,
) -> None:
    """Valida identidade, projeção causal, métodos e custos do plano."""
    if plan.problem_sha256 != compiled.sha256:
        raise ValueError("Hash do problem.pddl diverge do plano")
    if plan.domain.domain_sha256 != domain.domain_sha256:
        raise ValueError("Hash do domínio diverge do plano")
    if plan.domain.description_sha256 != domain.description_sha256:
        raise ValueError("Hash da descrição do domínio diverge do plano")
    if set(plan.selected_obligations) != set(
        compiled.projection.selected
    ):
        raise ValueError("Fechamento selecionado diverge do problema compilado")
    _validate_action_sequence(plan.steps, compiled.projection)


def _parse_fast_downward_statistics(
    stdout: str,
) -> dict[str, int | float | str | bool]:
    statistics: dict[str, int | float | str | bool] = {}
    patterns: tuple[tuple[str, str, type], ...] = (
        ("expanded_states", r"Expanded ([0-9]+) state", int),
        ("evaluated_states", r"Evaluated ([0-9]+) state", int),
        ("generated_states", r"Generated ([0-9]+) state", int),
        ("dead_ends", r"Dead ends: ([0-9]+) state", int),
        ("search_time_seconds", r"Search time: ([0-9.]+)s", float),
        ("total_time_seconds", r"Total time: ([0-9.]+)s", float),
        ("reported_plan_cost", r"Plan cost: ([0-9]+)", int),
        ("plan_length", r"Plan length: ([0-9]+) step", int),
    )
    for key, pattern, converter in patterns:
        matches = re.findall(pattern, stdout)
        if matches:
            statistics[key] = converter(matches[-1])
    return statistics


def _build_plan(
    *,
    manifest: ProcessingManifest,
    domain: DomainBundle,
    compiled: CompiledProblem,
    planner: str,
    steps: list[PlanStep],
) -> NominalPlan:
    timestamp = datetime.now(timezone.utc)
    seed = f"{manifest.manifest_id}:{manifest.revision}:{compiled.sha256}:{planner}"
    plan_id = f"plan-{hashlib.sha256(seed.encode()).hexdigest()[:16]}"
    return NominalPlan(
        plan_id=plan_id,
        generated_at=timestamp,
        manifest_id=manifest.manifest_id,
        manifest_revision=manifest.revision,
        manifest_sha256=compiled.manifest_sha256,
        domain=DomainIdentity(
            name=domain.name,
            version=domain.version,
            domain_sha256=domain.domain_sha256,
            description_sha256=domain.description_sha256,
        ),
        problem_name=compiled.projection.problem_name,
        problem_sha256=compiled.sha256,
        planner=planner,
        selected_obligations=list(compiled.projection.selected),
        expected_total_cost=sum(step.expected_cost for step in steps),
        steps=steps,
    )


def _symbol_table(values: Iterable[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    used: dict[str, str] = {}
    for value in sorted(set(values)):
        symbol = _pddl_symbol(value)
        if symbol in used and used[symbol] != value:
            suffix = hashlib.sha256(value.encode()).hexdigest()[:8]
            symbol = f"{symbol}-{suffix}"
        used[symbol] = value
        result[value] = symbol
    return result


def _pddl_symbol(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9-]+", "-", value.lower().replace("_", "-"))
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    if not normalized or not normalized[0].isalpha():
        normalized = f"x-{normalized or 'item'}"
    if not PDDL_SYMBOL.fullmatch(normalized):
        raise ValueError(f"Não foi possível gerar símbolo PDDL para: {value!r}")
    return normalized


def _parenthesis_balance(text: str) -> int:
    balance = 0
    for raw_line in text.splitlines():
        line = raw_line.split(";", 1)[0]
        balance += line.count("(") - line.count(")")
        if balance < 0:
            return balance
    return balance


def _text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


from backend.core.hashing import json_sha256 as _json_sha256
