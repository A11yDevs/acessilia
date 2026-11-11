"""Bind predictions to their source pages without tying them to local paths."""

import hashlib
import json
from pathlib import Path

from scripts.bench.datasets.base import BenchPage

INPUTS_FILE = "inputs.json"


def page_identity(page: BenchPage) -> dict:
    return {
        "dataset": page.meta.get("dataset_id") or page.meta.get("dataset") or "local",
        "dataset_revision": page.meta.get("dataset_revision") or page.meta.get("revision"),
        "document_id": page.document_id,
        "page": page.page,
        "image_sha256": hashlib.sha256(page.image_path.read_bytes()).hexdigest(),
    }


def run_inputs(run_dir: Path, *, required: bool = False) -> dict:
    path = run_dir / INPUTS_FILE
    if not path.exists() and not required:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("run has no valid recorded input identities") from exc
    if not isinstance(value, dict):
        raise ValueError("run has invalid recorded input identities")
    return value


def check_input(page: BenchPage, recorded: dict) -> None:
    if recorded.get(page.item_id) != page_identity(page):
        raise ValueError(f"input identity changed or is missing for {page.item_id}")
