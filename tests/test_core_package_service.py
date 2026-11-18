"""The service depends on the core distribution (ADR-0016, step 6)."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_service_depends_on_the_core_package() -> None:
    root = tomllib.loads((ROOT / "pyproject.toml").read_text())

    assert "acessilia-core" in root["project"]["dependencies"]
    assert root["tool"]["uv"]["sources"]["acessilia-core"] == {"path": "libs/core", "editable": True}
