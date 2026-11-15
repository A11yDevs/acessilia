"""The image installs its runtime dependencies from the committed lock (#405)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "infra" / "Dockerfile"


def _text() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


def test_the_image_installs_runtime_dependencies_from_the_lock() -> None:
    text = _text()
    # --locked fails on a stale lock; --no-dev leaves the test tools out of the
    # image; --no-editable installs the application and both libraries as wheels.
    assert "uv sync --locked --no-dev --no-editable" in text
    # The only pip use refreshes the base image's build tools, which Trivy also
    # scans; the application and its dependencies never come from pip.
    assert "pip install --no-cache-dir --upgrade pip setuptools wheel" in text
    for forbidden in ("pip install .", "pip install ./libs", "pip install -e"):
        assert forbidden not in text


def test_uv_is_pinned_by_release_and_digest() -> None:
    assert re.search(
        r"ghcr\.io/astral-sh/uv:0\.11\.17@sha256:[0-9a-f]{64}", _text()
    )


def test_the_base_image_is_pinned_by_digest() -> None:
    assert _text().count("python:3.11-slim@sha256:") == 2


def test_the_runtime_runs_from_the_locked_environment() -> None:
    text = _text()
    assert "COPY --from=builder /app/.venv /app/.venv" in text
    assert 'PATH="/app/.venv/bin:$PATH"' in text


def test_the_build_proves_the_libraries_come_from_wheels() -> None:
    text = _text()
    assert "site-packages" in text
    assert "docstruct" in text and "acessilia_sdk" in text
