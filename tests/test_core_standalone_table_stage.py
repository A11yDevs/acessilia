"""ADR-0016's acceptance evidence: one enrichment stage runs from a script.

``libs/core/examples/table_stage.py`` runs the table-structure stage with an
explicit ``CoreConfig`` and a model-call runner of its own, importing neither
FastAPI nor ``backend``. On the same manifest it must return the same
manifest as the service, which runs the stage with the configuration built
from its settings and its own runner.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "libs" / "core" / "examples" / "table_stage.py"
FIXTURE = ROOT / "libs" / "core" / "examples" / "fixtures" / "tables_manifest.json"


def _by_script(tmp_path: Path) -> dict:
    output = tmp_path / "script.json"
    completed = subprocess.run(
        [sys.executable, str(EXAMPLE), str(FIXTURE), str(tmp_path / "tables.pdf"), str(output)],
        capture_output=True, text=True, timeout=120, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(output.read_text(encoding="utf-8"))


def _by_service(tmp_path: Path) -> dict:
    from acessilia_core.agents.model_calls import model_call_scope
    from acessilia_core.manifest.models import ProcessingManifest
    from acessilia_core.pipeline.enrichment.tables import _enrich_table_structures

    from backend.config.core_config import core_config_from_settings
    from backend.services.model_calls import ModelCallExecutor, ModelCallLimits

    manifest = ProcessingManifest.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    config = core_config_from_settings()
    runner = ModelCallExecutor(ModelCallLimits(workers=1, max_pending=1))
    try:
        with model_call_scope(runner):
            asyncio.run(
                _enrich_table_structures(
                    manifest, tmp_path / "tables.pdf",
                    vision=config.vision, toolbox=config.toolbox, models=config.models,
                )
            )
    finally:
        runner.close()
    return manifest.model_dump(mode="json", by_alias=True)


def test_the_script_returns_the_service_manifest(tmp_path) -> None:
    by_script = _by_script(tmp_path)
    by_service = _by_service(tmp_path)

    assert by_script == by_service
    tables = [e for e in by_script["elements"] if e["type"] == "table"]
    assert len(tables) == 2
    assert all(t["metadata"]["table_linearization_hint"] == "text-heuristic" for t in tables)
    assert [t["metadata"]["table_column_count"] for t in tables] == [2, 3]


def test_the_script_imports_neither_the_service_nor_fastapi(tmp_path) -> None:
    """In the repository's environment both are importable; the script must
    still not load them (it exits 3 when it does)."""
    probe = (
        "import runpy, sys\n"
        f"sys.argv = [{str(EXAMPLE)!r}, {str(FIXTURE)!r}, {str(tmp_path / 'x.pdf')!r}, "
        f"{str(tmp_path / 'out.json')!r}]\n"
        "try:\n"
        f"    runpy.run_path({str(EXAMPLE)!r}, run_name='__main__')\n"
        "except SystemExit as exit_:\n"
        "    assert exit_.code == 0, exit_.code\n"
        "print(sorted(m for m in sys.modules if m.split('.')[0] in ('backend', 'frontend', 'fastapi')))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, timeout=120, check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip().splitlines()[-1] == "[]"


def _example_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("core_table_stage_example", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_table_read_by_the_model_goes_through_the_script_runner_and_config(
    monkeypatch, tmp_path
) -> None:
    """A table whose text holds no rows is read by the model: the call goes
    through the script's own runner, with the model built from the script's
    explicit config (review of #575). The model and the crop are fakes; the
    stage, the agent and the runner are real."""
    from acessilia_core.agents import data_agent
    from acessilia_core.agents.output_schemas import DataOutput
    from acessilia_core.manifest.models import ProcessingManifest
    from acessilia_core.pipeline.enrichment import tables as table_stage
    from acessilia_sdk.toolbox import provider_default

    example = _example_module()
    labels: list[str] = []
    models_seen = []

    class RecordingRunner(example.ThreadRunner):
        async def run(self, call, *, timeout, label):
            labels.append(label)
            return await super().run(call, timeout=timeout, label=label)

    class FakeAgent:
        def __init__(self, **_kwargs):
            pass

        def run(self, **_kwargs):
            return "model answer"

    reading = DataOutput(
        kind="table",
        rows=[
            {"cells": [{"text": "Name", "scope": "col"}, {"text": "Score", "scope": "col"}]},
            {"cells": [{"text": "Ana", "scope": "none"}, {"text": "9", "scope": "none"}]},
        ],
        language="en-US", confidence=0.9, warnings=[],
    )
    monkeypatch.setattr(example, "ThreadRunner", RecordingRunner)
    monkeypatch.setattr(
        data_agent, "get_agno_model",
        lambda models, toolbox, **_kwargs: models_seen.append((models, toolbox)) or "model",
    )
    monkeypatch.setattr(data_agent, "Agent", FakeAgent)
    monkeypatch.setattr(data_agent, "validate_structured_run", lambda response, schema: reading)
    monkeypatch.setattr(
        table_stage, "_extract_picture_bytes", lambda *_args, **_kwargs: (b"png", 1)
    )
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    table = next(e for e in data["elements"] if e["id"] == "t-1")
    table["text"] = "a table the extractor could not read"
    manifest = ProcessingManifest.model_validate(data)
    config = example.explicit_config(toolbox_url="http://127.0.0.1:9", data_dir=tmp_path)

    example.enrich_tables(manifest, tmp_path / "tables.pdf", config)

    read = next(e for e in manifest.elements if e.id == "t-1")
    assert labels == ["DataAgent/table/page-1"]
    assert read.metadata["table_linearization_hint"] == "data-agent-structured"
    [(models, toolbox)] = models_seen
    assert models is config.models and toolbox is config.toolbox
    assert models.ai_client == "toolbox"
    assert models.toolbox_vlm_provider == provider_default("toolbox_vlm_provider")
