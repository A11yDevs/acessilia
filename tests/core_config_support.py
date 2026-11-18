"""Configurations for the core's tests (ADR-0016, step 3).

The core has no defaults of its own: a test starts from the service's
settings and replaces only the fields it exercises, group by group.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from acessilia_core.config import (
    CoreConfig,
    DocumentConfig,
    ExportConfig,
    FusionConfig,
    ModelConfig,
    PathsConfig,
    ToolboxConfig,
    VisionConfig,
)

from backend.config.core_config import core_config_from_settings


def core_config(**groups: dict[str, Any]) -> CoreConfig:
    """The service's configuration, with fields replaced per group.

    ``core_config(document={"max_pages": 2})`` changes only ``max_pages``.
    """
    base = core_config_from_settings()
    return replace(
        base,
        **{name: replace(getattr(base, name), **fields) for name, fields in groups.items()},
    )


def document_config(**fields: Any) -> DocumentConfig:
    """The service's ``DocumentConfig``, with ``fields`` replaced."""
    return core_config(document=fields).document


def export_config(**fields: Any) -> ExportConfig:
    """The service's ``ExportConfig``, with ``fields`` replaced."""
    return core_config(export=fields).export


def fusion_config(**fields: Any) -> FusionConfig:
    """The service's ``FusionConfig``, with ``fields`` replaced."""
    return core_config(fusion=fields).fusion


def vision_config(**fields: Any) -> VisionConfig:
    """The service's ``VisionConfig``, with ``fields`` replaced."""
    return core_config(vision=fields).vision


def toolbox_config(*, providers: dict[str, str] | None = None, **fields: Any) -> ToolboxConfig:
    """The service's ``ToolboxConfig``, with ``fields`` replaced.

    ``providers`` replaces only the provider keys it names; the others keep
    the service's.
    """
    base = core_config_from_settings().toolbox
    if providers:
        fields["providers"] = {**base.providers, **providers}
    return replace(base, **fields)


def model_config(**fields: Any) -> ModelConfig:
    """The service's ``ModelConfig``, with ``fields`` replaced."""
    return core_config(models=fields).models


def paths_config(**fields: Any) -> PathsConfig:
    """The service's ``PathsConfig``, with ``fields`` replaced."""
    return core_config(paths=fields).paths
