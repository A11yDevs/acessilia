"""The core is a regular package of its own distribution (ADR-0016, step 6)."""

from __future__ import annotations

import tomllib
from pathlib import Path

import acessilia_core

ROOT = Path(__file__).resolve().parents[3]


def test_the_core_is_a_regular_package() -> None:
    """Not a namespace package, which a stale ``acessilia_core`` left in
    site-packages could silently merge with (review of #572)."""
    assert acessilia_core.__file__ is not None
    installed = Path(acessilia_core.__file__).resolve().parent
    editable = (ROOT / "libs" / "core" / "src" / "acessilia_core").resolve()
    # The checkout suite imports the editable install; the wheel jobs
    # (core alone and the production image) import from site-packages.
    assert installed == editable or installed.parent.name in {
        "site-packages",
        "dist-packages",
    }
    assert len(list(acessilia_core.__path__)) == 1


def test_the_version_matches_the_distribution() -> None:
    project = tomllib.loads((ROOT / "libs" / "core" / "pyproject.toml").read_text())["project"]

    assert project["name"] == "acessilia-core"
    assert acessilia_core.__version__ == project["version"]
