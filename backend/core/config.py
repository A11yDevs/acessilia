"""The core's configuration, passed explicitly (ADR-0016, step 3).

The core receives a :class:`CoreConfig` built by its caller instead of reading
the service's ``settings``. The service builds it from its environment
(``backend/config/core_config.py``), as it builds the SDK's
``ToolboxClientConfig``. The groups follow the core's responsibilities, and a
stage receives only the group it reads.

No field has a default: a value the core uses comes from the caller, so the
service's settings stay the one place where defaults live. Tests build a
config from those settings and replace the fields they exercise.

Step 3 moves the stages one at a time. Until the last one, the orchestrator
builds a config from ``settings`` at the start of each run when none is given,
and the stages not yet moved keep reading ``settings``. The logger's and the
catalogs' settings (``LOG_LEVEL``, ``LOGS_DIR``, ``I18N_LOCALES_ACTIVE``) are
process setup, not part of a run; the last step-3 pull request decides how
they reach the core.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ToolboxConfig:
    """How the core reaches the Toolbox, and which of its capabilities it uses.

    ``providers`` and ``timeouts`` are keyed by the SDK clients'
    ``provider_key`` and ``timeout_key`` (for example ``toolbox_pdf_provider``,
    ``toolbox_docx_timeout_seconds``).
    """

    base_url: str
    base_urls: str
    api_key: str
    timeout_seconds: int
    retries: int
    retry_backoff_seconds: float
    extraction_timeout_seconds: int
    providers: Mapping[str, str]
    timeouts: Mapping[str, int]
    use_remote_cache: bool
    use_artifact_store: bool
    availability_gate: str
    catalog_refresh_seconds: int
    catalog_stale_seconds: int
    media_inspect_enabled: bool
    pdf_validate_enabled: bool


@dataclass(frozen=True)
class ModelConfig:
    """The model the agents chat with, and the limits of each call."""

    ai_client: str
    ollama_base_url: str
    ollama_model: str
    ollama_api_key: str
    openrouter_base_url: str
    openrouter_model: str
    openrouter_api_key: str
    openrouter_site_url: str
    openrouter_app_name: str
    openrouter_max_tokens: int
    toolbox_vlm_provider: str
    model_call_timeout_seconds: int
    vision_region_max_tokens: int
    data_agent_max_tokens: int
    data_agent_timeout_seconds: int


@dataclass(frozen=True)
class VisionConfig:
    """How the enrichment stages call the vision model."""

    concurrency: int
    breaker_threshold: int
    region_cache_enabled: bool
    retry_pass_delay_seconds: int
    table_visual_review: bool
    pdf_split_dpi: int


@dataclass(frozen=True)
class FusionConfig:
    """Whether a second extraction provider runs, and how its result is used."""

    mode: str
    secondary_provider: str
    apply_page_routes: bool
    judge_max_pages: int


@dataclass(frozen=True)
class DocumentConfig:
    """Limits and choices about the document itself."""

    max_pages: int
    legacy_unicode_repair: str
    inline_math_detection: str
    formula_text_agreement_min: float
    slide_visual_coverage: float
    slide_fold_figure_labels: bool


@dataclass(frozen=True)
class ExportConfig:
    """The exporters' choices."""

    tts_voice: str
    object_markers_enabled: bool
    toolbox_docx_enabled: bool
    toolbox_pdf_ua_enabled: bool


@dataclass(frozen=True)
class PathsConfig:
    """Where the core keeps the files of a run."""

    data_dir: Path


@dataclass(frozen=True)
class CoreConfig:
    """Everything the core reads from its caller, by responsibility."""

    toolbox: ToolboxConfig
    models: ModelConfig
    vision: VisionConfig
    fusion: FusionConfig
    document: DocumentConfig
    export: ExportConfig
    paths: PathsConfig


__all__ = [
    "CoreConfig",
    "DocumentConfig",
    "ExportConfig",
    "FusionConfig",
    "ModelConfig",
    "PathsConfig",
    "ToolboxConfig",
    "VisionConfig",
]
