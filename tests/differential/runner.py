"""Run one differential case through the whole pipeline (#849).

The run is the backend's (``backend/service.py``): the PDDL orchestrator's
``execute`` with a structured output, the paragraph merge, then
``build_canonical_document``. Every Toolbox and model call goes to
:class:`~tests.differential.fake_toolbox.FakeToolbox`. The runner uses only
what core 0.3.11 already had, so ``scripts/record_differential_references.py``
runs it unchanged on an older tree to record its references.

``python -m tests.differential.runner <case.json>... --out <dir>`` writes each
case's normalized canonical document to ``<dir>/<case>.json``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CASES = HERE / "cases"
REFERENCES = HERE / "references"
SOURCE_PDF = HERE / "source.pdf"

#: The run's settings: every call to the fake, no cache, no retry, the
#: availability gate off (the fake publishes no catalogue).
ENVIRONMENT = {
    "TOOLBOX_BASE_URL": "http://toolbox.differential.test",
    "TOOLBOX_BASE_URLS": "",
    "AI_CLIENT": "toolbox",
    "PIPELINE_ENGINE": "pddl",
    "TOOLBOX_USE_REMOTE_CACHE": "false",
    "TOOLBOX_USE_ARTIFACT_STORE": "true",
    "TOOLBOX_AVAILABILITY_GATE": "off",
    "TOOLBOX_RETRIES": "0",
    "TOOLBOX_RETRY_BACKOFF_SECONDS": "0",
    "VISION_REGION_CACHE_ENABLED": "false",
    "VISION_RETRY_PASS_DELAY_SECONDS": "0",
    "FUSION_MODE": "single",
}

#: Keys whose values change from run to run, at any depth of the output.
VOLATILE_KEYS = frozenset({
    "created_at", "generated_at", "started_at", "completed_at", "updated_at",
    "duration_ms", "elapsed_ms", "elapsed_seconds", "timestamp",
    "source_path", "path", "file_path", "tmpdir", "data_dir",
})

#: Keys that identify the planning state or price the plan, not the
#: document: they change with every migration by design (the obligations
#: and methods the plan has), so they are not compared.
PLANNING_KEYS = frozenset({
    "pddl_plan_id", "pddl_execution_id", "pddl_manifest_id",
    "pddl_expected_total_cost",
})


def load_case(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_case(case_path: Path) -> dict[str, Any]:
    """The normalized canonical document of ``case_path``, and what the fake saw."""
    from tests.differential.fake_toolbox import FakeToolbox, installed

    case = load_case(case_path)
    saved = {key: os.environ.get(key) for key in ENVIRONMENT}
    os.environ.update(ENVIRONMENT)
    os.environ.update(case.get("environment", {}))
    fake = FakeToolbox(case)
    workdir = Path(tempfile.mkdtemp(prefix="differential-"))
    try:
        source = workdir / f"{case_path.parent.name}.pdf"
        shutil.copy(SOURCE_PDF, source)
        with installed(fake):
            canonical = asyncio.run(_run(source, case.get("mode", "normal")))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    # The document's id hashes its metadata, planning ids included.
    canonical.pop("id", None)
    return {
        "canonical": normalize(canonical),
        "calls": sorted(set(fake.calls)),
        "unhandled": sorted(set(fake.unhandled)),
    }


async def _run(source: Path, mode: str) -> dict[str, Any]:
    # Imported here: the settings read the environment when they are built.
    from acessilia_core.pipeline.canonical_builder import build_canonical_document
    from acessilia_core.pipeline.orchestrator import PddlAccessibilityOrchestrator
    from acessilia_core.ports import RunPorts
    from backend.config.core_config import core_config_from_settings
    from backend.config.settings import Settings
    from backend.services.model_calls import get_model_calls
    from docstruct.profiles import verbosity_for_mode
    from docstruct.text.paragraphs import merge_broken_paragraphs

    settings = Settings()
    config = core_config_from_settings(settings)
    orchestrator = _orchestrator(PddlAccessibilityOrchestrator, settings)
    result = await orchestrator.execute(
        source, source.parent, None, mode=mode, structured_output=True,
        config=config, model_calls=get_model_calls(), ports=RunPorts.none(),
    )
    if not isinstance(result, dict):
        raise RuntimeError(f"the run returned {type(result).__name__}, not a structured payload")
    processed = {**result, "text": merge_broken_paragraphs(result["text"])}
    metadata = result.get("canonical_metadata")
    warnings = result.get("technical_warnings")
    return build_canonical_document(
        processed,
        toolbox=config.toolbox,
        title=source.stem,
        language="pt-BR",
        verbosity=verbosity_for_mode(mode),
        source_name=source.name,
        source_path=str(source),
        audience=["reader"],
        metadata=metadata if isinstance(metadata, dict) else None,
        technical_warnings=[str(item) for item in warnings] if isinstance(warnings, list) else None,
    )


def _orchestrator(cls: Any, settings: Any) -> Any:
    """The orchestrator ``backend/service.py`` builds, without Fast Downward:
    each argument only when this version's constructor takes it."""
    import inspect

    wanted = {
        "planner_backend": "internal",
        "preferred_plan": settings.pddl_preferred_plan,
        "execute_dry_run": False,
        "enable_ocr": False,
        "extractor_backend": "toolbox",
        "max_replans": getattr(settings, "pddl_max_replans", None),
        "max_discovery_replans": getattr(settings, "pddl_max_discovery_replans", None),
    }
    accepted = inspect.signature(cls).parameters
    return cls(**{
        name: value for name, value in wanted.items()
        if name in accepted and value is not None
    })


def normalize(value: Any) -> Any:
    """``value`` without what changes from run to run (``VOLATILE_KEYS``)."""
    if isinstance(value, dict):
        return {
            key: normalize(item) for key, item in sorted(value.items())
            if key not in VOLATILE_KEYS and key not in PLANNING_KEYS
        }
    if isinstance(value, list):
        return [normalize(item) for item in value]
    return value


def differences(reference: Any, current: Any, path: str = "") -> list[dict[str, str]]:
    """Where ``current`` departs from ``reference``: each ``{kind, path}``,
    ``kind`` being ``added``, ``removed`` or ``changed`` and ``path`` a JSON
    pointer (``/sections/0/blocks/2/alt_text``)."""
    if isinstance(reference, dict) and isinstance(current, dict):
        found: list[dict[str, str]] = []
        for key in sorted(set(reference) | set(current)):
            child = f"{path}/{key}"
            if key not in reference:
                found.append({"kind": "added", "path": child})
            elif key not in current:
                found.append({"kind": "removed", "path": child})
            else:
                found.extend(differences(reference[key], current[key], child))
        return found
    if isinstance(reference, list) and isinstance(current, list):
        found = []
        for index in range(max(len(reference), len(current))):
            child = f"{path}/{index}"
            if index >= len(reference):
                found.append({"kind": "added", "path": child})
            elif index >= len(current):
                found.append({"kind": "removed", "path": child})
            else:
                found.extend(differences(reference[index], current[index], child))
        return found
    return [] if reference == current else [{"kind": "changed", "path": path or "/"}]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", nargs="*", type=Path, help="case.json files (default: every case)")
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    arguments.out.mkdir(parents=True, exist_ok=True)
    for case_path in arguments.cases or sorted(CASES.glob("*/case.json")):
        outcome = run_case(case_path)
        target = arguments.out / f"{case_path.parent.name}.json"
        target.write_text(json.dumps(outcome, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"{case_path.parent.name}: {len(outcome['unhandled'])} unhandled call(s) -> {target}")


if __name__ == "__main__":
    main()
