from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.core.execution.models import ExecutionReport


def execution_report_schema() -> dict[str, Any]:
    return ExecutionReport.model_json_schema(by_alias=True, mode="validation")


def write_execution_report_schema(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(execution_report_schema(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination
