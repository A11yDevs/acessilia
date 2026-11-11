"""Core-owned historical fixtures for the pipeline heuristic comparison."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "pipeline-comparison"


def load_pipeline_fixtures(root: Path = FIXTURE_DIR) -> list[dict[str, Any]]:
    """Read the local inventory and verify the Core-owned canonicals."""
    root = Path(root).resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("canonical_schema_version") != "1.0.0":
        raise ValueError("historical pipeline fixture schema must remain 1.0.0")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("pipeline fixture manifest has no cases")
    checked = []
    for case in cases:
        path = _verified_path(root, case, "canonical")
        canonical = json.loads(path.read_bytes())
        if canonical.get("schema_version") != manifest["canonical_schema_version"]:
            raise ValueError(f"pipeline fixture schema mismatch for {case['id']}: {path}")
        checked.append({**case, "canonical_path": path})
    return checked


def resolve_pipeline_input(case: dict[str, Any], dataset_root: Path) -> Path:
    """Resolve and verify the original input from a separate Dataset checkout."""
    return _verified_path(dataset_root.resolve(), case, "input")


def _verified_path(root: Path, case: dict[str, Any], field: str) -> Path:
    path = (root / case[field]).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"pipeline fixture path escapes its root: {case[field]}")
    if hashlib.sha256(path.read_bytes()).hexdigest() != case[f"{field}_sha256"]:
        raise ValueError(f"pipeline fixture hash mismatch for {case['id']} {field}: {path}")
    return path
