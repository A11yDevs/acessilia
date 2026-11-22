from __future__ import annotations

from pathlib import Path
from typing import Any

from acessilia_core.planning.models import NominalPlan, PlanningComparison
from acessilia_core.schema_files import write_schema


def nominal_plan_schema() -> dict[str, Any]:
    return NominalPlan.model_json_schema(by_alias=True, mode="validation")


def write_nominal_plan_schema(destination: Path) -> Path:
    return write_schema(nominal_plan_schema(), destination)


def planning_comparison_schema() -> dict[str, Any]:
    return PlanningComparison.model_json_schema(
        by_alias=True, mode="validation"
    )


def write_planning_comparison_schema(destination: Path) -> Path:
    return write_schema(planning_comparison_schema(), destination)
