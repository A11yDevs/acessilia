"""Temporary compatibility import for the pre-ADR-0016 benchmark adapter.

New Core code should import from ``backend.core.toolbox.toolbox_client`` and
pass an explicit ``ToolboxConfig``. This module preserves the old settings-
based factory until ``acessilia-benchmark`` moves to stable public interfaces.
See ``docs/bench.md`` for the migration tracks and exit criteria.
"""

from __future__ import annotations

from typing import Any, TypeVar

from backend.config.core_config import core_config_from_settings
from backend.core.toolbox.toolbox_client import (
    ToolboxCapabilityClient,
    make_toolbox_client as _make_toolbox_client,
)

ClientT = TypeVar("ClientT", bound=ToolboxCapabilityClient)


def make_toolbox_client(client_cls: type[ClientT], **overrides: Any) -> ClientT:
    """Build a client from current settings using the legacy factory signature."""
    return _make_toolbox_client(
        client_cls,
        core_config_from_settings().toolbox,
        **overrides,
    )


__all__ = ["make_toolbox_client"]
