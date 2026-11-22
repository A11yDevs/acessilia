"""The committed PDDL schemas match their generators (#737)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import acessilia_core.i18n as i8n
from acessilia_core.execution.schema import execution_report_schema
from acessilia_core.manifest.schema import processing_manifest_schema
from acessilia_core.planning.schema import (
    nominal_plan_schema,
    planning_comparison_schema,
)
from tests.locale_support import use_server_locale

ROOT = Path(__file__).resolve().parents[1]

SCHEMAS = {
    "execution_report.schema.json": execution_report_schema,
    "nominal_plan.schema.json": nominal_plan_schema,
    "planning_comparison.schema.json": planning_comparison_schema,
    "processing_manifest.schema.json": processing_manifest_schema,
}


@pytest.mark.parametrize("locale", ["en_US", "pt_BR"])
def test_committed_pddl_schemas_match_their_generators(monkeypatch, locale) -> None:
    use_server_locale(monkeypatch, locale)
    i8n._catalog_for.cache_clear()
    for name, schema in SCHEMAS.items():
        expected = json.dumps(schema(), ensure_ascii=False, indent=2) + "\n"
        committed = (ROOT / "schemas" / name).read_text(encoding="utf-8")

        assert committed == expected, (
            f"schemas/{name} is stale; run scripts/generate_pddl_schemas.py"
        )
