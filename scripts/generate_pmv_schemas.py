#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.execution.schema import write_execution_report_schema
from backend.core.manifest.schema import write_processing_manifest_schema
from backend.core.planning.schema import (
    write_nominal_plan_schema,
    write_planning_comparison_schema,
)


if __name__ == "__main__":
    destinations = (
        write_processing_manifest_schema(
            ROOT / "schemas" / "processing_manifest.schema.json"
        ),
        write_nominal_plan_schema(ROOT / "schemas" / "nominal_plan.schema.json"),
        write_planning_comparison_schema(
            ROOT / "schemas" / "planning_comparison.schema.json"
        ),
        write_execution_report_schema(
            ROOT / "schemas" / "execution_report.schema.json"
        ),
    )
    for destination in destinations:
        print(destination)
