"""``docstruct.__version__`` matches the version in ``pyproject.toml``.

The release workflow checks the tag against ``pyproject.toml`` only, so a bump
that forgets ``__init__.py`` would publish a wheel reporting the previous
version (0.3.0 was bumped that way).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import docstruct

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_version_matches_pyproject() -> None:
    with PYPROJECT.open("rb") as fh:
        expected = tomllib.load(fh)["project"]["version"]
    assert docstruct.__version__ == expected
