"""Configurations for the core's tests (ADR-0016, step 3).

Deterministic values, built without the service's settings or environment, so
the core suite runs alone. A test replaces only the fields it exercises.
"""

from __future__ import annotations

import tempfile
from dataclasses import replace
from pathlib import Path
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
from acessilia_sdk.toolbox import PROVIDER_DEFAULTS

#: A process-local scratch directory, so tests that forget ``tmp_path`` do not
#: share a fixed path with another process or user.
_TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="acessilia-core-tests-"))

_TOOLBOX_PROVIDERS = dict(PROVIDER_DEFAULTS)

_TOOLBOX_TIMEOUTS = {
    "toolbox_docx_timeout_seconds": 300,
    "toolbox_pdf_ua_timeout_seconds": 300,
    "toolbox_pdf_validate_timeout_seconds": 330,
    "toolbox_structure_timeout_seconds": 600,
}


def default_core_config() -> CoreConfig:
    """The deterministic base every core test starts from."""
    return CoreConfig(
        toolbox=ToolboxConfig(
            base_url="http://toolbox-render.test",
            base_urls="",
            api_key="test-api-key",
            timeout_seconds=30,
            retries=0,
            retry_backoff_seconds=0.0,
            extraction_timeout_seconds=60,
            providers=dict(_TOOLBOX_PROVIDERS),
            timeouts=dict(_TOOLBOX_TIMEOUTS),
            use_remote_cache=False,
            use_artifact_store=False,
            availability_gate="observe",
            catalog_refresh_seconds=60,
            catalog_stale_seconds=900,
            media_inspect_enabled=True,
            pdf_validate_enabled=True,
        ),
        models=ModelConfig(
            ai_client="ollama",
            ollama_base_url="http://localhost:11434/api/chat",
            ollama_model="llama3",
            ollama_api_key="",
            openrouter_base_url="https://openrouter.ai/api/v1/chat/completions",
            openrouter_model="qwen/qwen3-vl-8b-instruct",
            openrouter_api_key="",
            openrouter_site_url="",
            openrouter_app_name="acessilia-tests",
            openrouter_max_tokens=2000,
            toolbox_vlm_provider="qwen3-vl-8b",
            model_call_timeout_seconds=30,
            vision_region_max_tokens=2000,
            data_agent_max_tokens=8192,
            data_agent_timeout_seconds=60,
        ),
        vision=VisionConfig(
            concurrency=2,
            breaker_threshold=3,
            region_cache_enabled=False,
            retry_pass_delay_seconds=0,
            table_visual_review=True,
            pdf_split_dpi=150,
        ),
        fusion=FusionConfig(
            mode="single",
            secondary_provider="mineru",
            apply_page_routes=True,
            judge_max_pages=5,
        ),
        document=DocumentConfig(
            max_pages=50,
            legacy_unicode_repair="off",
            inline_math_detection="fonts",
            formula_text_agreement_min=0.75,
            slide_visual_coverage=0.5,
            slide_fold_figure_labels=True,
        ),
        export=ExportConfig(
            tts_voice="pt-BR-FranciscaNeural",
            object_markers_enabled=False,
            toolbox_docx_enabled=True,
            toolbox_pdf_ua_enabled=True,
            toolbox_pdf_ua_math_bisect_budget=8,
        ),
        paths=PathsConfig(data_dir=_TEST_DATA_DIR),
    )


def core_config(**groups: dict[str, Any]) -> CoreConfig:
    """The test CoreConfig with fields replaced per group."""
    base = default_core_config()
    return replace(
        base,
        **{name: replace(getattr(base, name), **fields) for name, fields in groups.items()},
    )


def document_config(**fields: Any) -> DocumentConfig:
    return core_config(document=fields).document


def export_config(**fields: Any) -> ExportConfig:
    return core_config(export=fields).export


def fusion_config(**fields: Any) -> FusionConfig:
    return core_config(fusion=fields).fusion


def vision_config(**fields: Any) -> VisionConfig:
    return core_config(vision=fields).vision


def toolbox_config(*, providers: dict[str, str] | None = None, **fields: Any) -> ToolboxConfig:
    base = core_config().toolbox
    if providers:
        fields["providers"] = {**base.providers, **providers}
    return replace(base, **fields)


def model_config(**fields: Any) -> ModelConfig:
    return core_config(models=fields).models


def paths_config(**fields: Any) -> PathsConfig:
    return core_config(paths=fields).paths
