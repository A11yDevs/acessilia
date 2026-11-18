"""The service builds the core's configuration from its settings (ADR-0016, step 3).

``core_config_from_settings`` is the one place where the service's
environment becomes a :class:`~acessilia_core.config.CoreConfig`. It reads the
settings when it is called, so a run sees the settings of its start (and a
test's monkeypatch).
"""

from __future__ import annotations

from backend.config.settings import Settings, settings as default_settings
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
from acessilia_core.toolbox.toolbox_client import PROVIDER_DEFAULTS, TIMEOUT_KEYS


def core_config_from_settings(settings: Settings | None = None) -> CoreConfig:
    """The core's configuration from ``settings`` (the service's, by default)."""
    s = default_settings if settings is None else settings
    return CoreConfig(
        toolbox=ToolboxConfig(
            base_url=s.toolbox_base_url,
            base_urls=s.toolbox_base_urls,
            api_key=s.toolbox_api_key,
            timeout_seconds=s.toolbox_timeout_seconds,
            retries=s.toolbox_retries,
            retry_backoff_seconds=s.toolbox_retry_backoff_seconds,
            extraction_timeout_seconds=s.toolbox_extraction_timeout_seconds,
            providers={key: getattr(s, key) for key in sorted(PROVIDER_DEFAULTS)},
            timeouts={key: getattr(s, key) for key in sorted(TIMEOUT_KEYS)},
            use_remote_cache=s.toolbox_use_remote_cache,
            use_artifact_store=s.toolbox_use_artifact_store,
            availability_gate=s.toolbox_availability_gate,
            catalog_refresh_seconds=s.toolbox_catalog_refresh_seconds,
            catalog_stale_seconds=s.toolbox_catalog_stale_seconds,
            media_inspect_enabled=s.toolbox_media_inspect_enabled,
            pdf_validate_enabled=s.toolbox_pdf_validate_enabled,
        ),
        models=ModelConfig(
            ai_client=s.ai_client,
            ollama_base_url=s.ollama_base_url,
            ollama_model=s.ollama_model,
            ollama_api_key=s.ollama_api_key,
            openrouter_base_url=s.openrouter_base_url,
            openrouter_model=s.openrouter_model,
            openrouter_api_key=s.openrouter_api_key,
            openrouter_site_url=s.openrouter_site_url,
            openrouter_app_name=s.openrouter_app_name,
            openrouter_max_tokens=s.openrouter_max_tokens,
            toolbox_vlm_provider=s.toolbox_vlm_provider,
            model_call_timeout_seconds=s.model_call_timeout_seconds,
            vision_region_max_tokens=s.vision_region_max_tokens,
            data_agent_max_tokens=s.data_agent_max_tokens,
            data_agent_timeout_seconds=s.data_agent_timeout_seconds,
        ),
        vision=VisionConfig(
            concurrency=s.vision_concurrency,
            breaker_threshold=s.vision_breaker_threshold,
            region_cache_enabled=s.vision_region_cache_enabled,
            retry_pass_delay_seconds=s.vision_retry_pass_delay_seconds,
            table_visual_review=s.table_visual_review,
            pdf_split_dpi=s.pdf_split_dpi,
        ),
        fusion=FusionConfig(
            mode=s.fusion_mode,
            secondary_provider=s.fusion_secondary_provider,
            apply_page_routes=s.fusion_apply_page_routes,
            judge_max_pages=s.fusion_judge_max_pages,
        ),
        document=DocumentConfig(
            max_pages=s.max_pages,
            legacy_unicode_repair=s.legacy_unicode_repair,
            inline_math_detection=s.inline_math_detection,
            formula_text_agreement_min=s.formula_text_agreement_min,
            slide_visual_coverage=s.slide_visual_coverage,
            slide_fold_figure_labels=s.slide_fold_figure_labels,
        ),
        export=ExportConfig(
            tts_voice=s.tts_voice,
            object_markers_enabled=s.object_markers_enabled,
            toolbox_docx_enabled=s.toolbox_docx_enabled,
            toolbox_pdf_ua_enabled=s.toolbox_pdf_ua_enabled,
        ),
        paths=PathsConfig(data_dir=s.data_dir),
    )


__all__ = ["core_config_from_settings"]
