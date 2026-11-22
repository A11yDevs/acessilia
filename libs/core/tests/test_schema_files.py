"""The core's JSON Schema writers share one formatting policy (#656)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from acessilia_core.execution.schema import (
    execution_report_schema,
    write_execution_report_schema,
)
from acessilia_core.manifest.schema import (
    processing_manifest_schema,
    write_processing_manifest_schema,
)
from acessilia_core.planning.schema import (
    nominal_plan_schema,
    planning_comparison_schema,
    write_nominal_plan_schema,
    write_planning_comparison_schema,
)
from acessilia_core.schema_files import write_schema


def test_write_schema_creates_the_parent_and_adds_a_newline(tmp_path: Path) -> None:
    destination = tmp_path / "nested" / "schema.json"

    result = write_schema({"description": "日本語", "type": "object"}, destination)

    assert result == destination
    assert destination.read_text(encoding="utf-8").endswith("\n")
    assert json.loads(destination.read_text(encoding="utf-8")) == {
        "description": "日本語",
        "type": "object",
    }


@pytest.mark.parametrize(
    ("writer", "schema"),
    [
        (write_execution_report_schema, execution_report_schema),
        (write_processing_manifest_schema, processing_manifest_schema),
        (write_nominal_plan_schema, nominal_plan_schema),
        (write_planning_comparison_schema, planning_comparison_schema),
    ],
)
def test_each_writer_uses_the_shared_formatting(tmp_path: Path, writer, schema) -> None:
    destination = writer(tmp_path / "schema.json")

    assert json.loads(destination.read_text(encoding="utf-8")) == schema()
