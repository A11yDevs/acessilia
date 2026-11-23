"""A deterministic pytest environment for the test-infrastructure tools.

The mutation harness, the timing collector and the test-failed rerunner spawn
pytest from a developer shell. Ambient pytest variables can change test
selection, plugins, temporary roots or the reported identity, so these tools
strip them before starting the child process.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

#: Variables that must not leak into an instrumented pytest run.
PYTEST_ENV_VARS = (
    "PYTEST_ADDOPTS",
    "PYTEST_PLUGINS",
    "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
    "PYTEST_CURRENT_TEST",
    "PYTEST_DEBUG",
    "PYTEST_DEBUG_TEMPROOT",
)


def sanitized_environ(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """A copy of ``environ`` without the ambient pytest variables."""
    env = dict(os.environ if environ is None else environ)
    for name in PYTEST_ENV_VARS:
        env.pop(name, None)
    return env
