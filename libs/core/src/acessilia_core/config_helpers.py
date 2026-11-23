"""Small helpers shared by the code that requires the run's configuration."""

from __future__ import annotations

from typing import TypeVar

T = TypeVar("T")


def _require_config(value: T | None, message: str, error: type[Exception]) -> T:
    """Return ``value`` or raise ``error`` with the caller's message."""
    if value is None:
        raise error(message)
    return value
