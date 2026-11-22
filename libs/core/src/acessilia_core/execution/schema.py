from __future__ import annotations

from pathlib import Path
from typing import Any

from acessilia_core.execution.models import ExecutionReport
from acessilia_core.schema_files import write_schema


def execution_report_schema() -> dict[str, Any]:
    return ExecutionReport.model_json_schema(by_alias=True, mode="validation")


def write_execution_report_schema(destination: Path) -> Path:
    return write_schema(execution_report_schema(), destination)
