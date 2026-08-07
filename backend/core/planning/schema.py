from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.core.planning.models import NominalPlan, PlanningComparison


def nominal_plan_schema() -> dict[str, Any]:
    return NominalPlan.model_json_schema(by_alias=True, mode="validation")


def write_nominal_plan_schema(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(nominal_plan_schema(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination


def planning_comparison_schema() -> dict[str, Any]:
    return PlanningComparison.model_json_schema(
        by_alias=True, mode="validation"
    )


def write_planning_comparison_schema(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(
            planning_comparison_schema(),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return destination
