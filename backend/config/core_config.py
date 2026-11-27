"""The service builds the core's configuration from its settings (ADR-0016, step 3).

``core_config_from_settings`` is the one place where the service's
environment becomes a :class:`~acessilia_core.config.CoreConfig`. It reads the
settings when it is called, so a run sees the settings of its start (and a
test's monkeypatch).
"""

from __future__ import annotations

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
from acessilia_core.toolbox.toolbox_client import TIMEOUT_KEYS
from acessilia_sdk.toolbox import PROVIDER_DEFAULTS
from backend.config.settings import Settings, settings as default_settings

#: Which setting fills each ``CoreConfig`` field, by ``group.field``. The
#: provider and timeout tables are flattened to ``group.table[key]``. Written
#: out so that a swapped pair fails, and read by the effective-configuration
#: record to prove every setting is classified (#380).
FIELD_SETTINGS: dict[str, str] = {
    "toolbox.base_url": "toolbox_base_url",
    "toolbox.base_urls": "toolbox_base_urls",
    "toolbox.api_key": "toolbox_api_key",
    "toolbox.timeout_seconds": "toolbox_timeout_seconds",
    "toolbox.retries": "toolbox_retries",
    "toolbox.retry_backoff_seconds": "toolbox_retry_backoff_seconds",
    "toolbox.extraction_timeout_seconds": "toolbox_extraction_timeout_seconds",
    "toolbox.use_remote_cache": "toolbox_use_remote_cache",
    "toolbox.use_artifact_store": "toolbox_use_artifact_store",
    "toolbox.availability_gate": "toolbox_availability_gate",
    "toolbox.catalog_refresh_seconds": "toolbox_catalog_refresh_seconds",
    "toolbox.catalog_stale_seconds": "toolbox_catalog_stale_seconds",
    "toolbox.media_inspect_enabled": "toolbox_media_inspect_enabled",
    "toolbox.pdf_validate_enabled": "toolbox_pdf_validate_enabled",
    "models.ai_client": "ai_client",
    "models.ollama_base_url": "ollama_base_url",
    "models.ollama_model": "ollama_model",
    "models.ollama_api_key": "ollama_api_key",
    "models.openrouter_base_url": "openrouter_base_url",
    "models.openrouter_model": "openrouter_model",
    "models.openrouter_api_key": "openrouter_api_key",
    "models.openrouter_site_url": "openrouter_site_url",
    "models.openrouter_app_name": "openrouter_app_name",
    "models.openrouter_max_tokens": "openrouter_max_tokens",
    "models.toolbox_vlm_provider": "toolbox_vlm_provider",
    "models.model_call_timeout_seconds": "model_call_timeout_seconds",
    "models.vision_region_max_tokens": "vision_region_max_tokens",
    "models.data_agent_max_tokens": "data_agent_max_tokens",
    "models.data_agent_timeout_seconds": "data_agent_timeout_seconds",
    "vision.concurrency": "vision_concurrency",
    "vision.breaker_threshold": "vision_breaker_threshold",
    "vision.region_cache_enabled": "vision_region_cache_enabled",
    "vision.retry_pass_delay_seconds": "vision_retry_pass_delay_seconds",
    "vision.table_visual_review": "table_visual_review",
    "vision.pdf_split_dpi": "pdf_split_dpi",
    "fusion.mode": "fusion_mode",
    "fusion.secondary_provider": "fusion_secondary_provider",
    "fusion.apply_page_routes": "fusion_apply_page_routes",
    "fusion.judge_max_pages": "fusion_judge_max_pages",
    "document.max_pages": "max_pages",
    "document.legacy_unicode_repair": "legacy_unicode_repair",
    "document.inline_math_detection": "inline_math_detection",
    "document.formula_text_agreement_min": "formula_text_agreement_min",
    "document.slide_visual_coverage": "slide_visual_coverage",
    "document.slide_fold_figure_labels": "slide_fold_figure_labels",
    "export.tts_voice": "tts_voice",
    "export.object_markers_enabled": "object_markers_enabled",
    "export.toolbox_docx_enabled": "toolbox_docx_enabled",
    "export.toolbox_pdf_ua_enabled": "toolbox_pdf_ua_enabled",
    "export.toolbox_pdf_ua_math_bisect_budget": "toolbox_pdf_ua_math_bisect_budget",
    "paths.data_dir": "data_dir",
    **{f"toolbox.providers[{key}]": key for key in PROVIDER_DEFAULTS},
    **{f"toolbox.timeouts[{key}]": key for key in TIMEOUT_KEYS},
}


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
            toolbox_pdf_ua_math_bisect_budget=s.toolbox_pdf_ua_math_bisect_budget,
        ),
        paths=PathsConfig(data_dir=s.data_dir),
    )


__all__ = ["FIELD_SETTINGS", "core_config_from_settings"]
