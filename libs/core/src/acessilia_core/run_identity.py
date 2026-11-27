"""What a run's result depends on, from its ``CoreConfig`` (ADR-0016 step 3, #544).

A stored result is reused only for a run that would produce it again. Two
identities say what "again" means, both built from the run's config and never
from ``settings``:

- :func:`processing_identity`, for the processed document: the service adds its
  own options (engine, planner, model revision) and keys its cache with it;
- :func:`fusion_reuse_identity`, for a fused extraction stored during the
  structure step and reused by the dual-provider fusion handler.

Every field of ``CoreConfig`` is classified: it either takes part in the
processing identity (``PROCESSING_FIELDS``) or is left out for a stated reason
(``NOT_PROCESSING_FIELDS``). A test keeps the two complete, so a new field
cannot be left out by omission.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import fields
from pathlib import Path
from typing import Any

from acessilia_core.config import CoreConfig, FusionConfig, ToolboxConfig

#: Fields that can change the processed document, by ``group.field``.
#: ``toolbox.providers`` takes part through ``PROCESSING_PROVIDERS`` only.
PROCESSING_FIELDS: frozenset[str] = frozenset({
    "toolbox.base_url",
    "toolbox.base_urls",
    "toolbox.providers",
    "toolbox.availability_gate",
    "toolbox.media_inspect_enabled",
    "models.ai_client",
    "models.ollama_base_url",
    "models.ollama_model",
    "models.openrouter_base_url",
    "models.openrouter_model",
    "models.openrouter_max_tokens",
    "models.toolbox_vlm_provider",
    "models.vision_region_max_tokens",
    "models.data_agent_max_tokens",
    "vision.table_visual_review",
    "vision.pdf_split_dpi",
    "fusion.mode",
    "fusion.secondary_provider",
    "fusion.apply_page_routes",
    "fusion.judge_max_pages",
    "document.max_pages",
    "document.legacy_unicode_repair",
    "document.inline_math_detection",
    "document.formula_text_agreement_min",
    "document.slide_visual_coverage",
    "document.slide_fold_figure_labels",
})

#: Fields left out of the processing identity, each with its reason.
NOT_PROCESSING_FIELDS: dict[str, str] = {
    "toolbox.api_key": "a credential: it reaches the same deployment",
    "toolbox.timeout_seconds": "transport: a slower answer is the same answer",
    "toolbox.retries": "transport",
    "toolbox.retry_backoff_seconds": "transport",
    "toolbox.extraction_timeout_seconds": "transport: a run that times out is not stored",
    "toolbox.timeouts": "transport (the exports' and the structure call's budgets)",
    "toolbox.use_remote_cache": "the Toolbox's own cache returns the same answer",
    "toolbox.use_artifact_store": "transport: the source is referenced instead of uploaded",
    "toolbox.catalog_refresh_seconds": "how often the catalogue is read",
    "toolbox.catalog_stale_seconds": "how long a catalogue snapshot is used",
    "toolbox.pdf_validate_enabled": "the PDF/UA audit runs on the exports, after the cache",
    "models.ollama_api_key": "a credential",
    "models.openrouter_api_key": "a credential",
    "models.openrouter_site_url": "an attribution header for the provider",
    "models.openrouter_app_name": "an attribution header for the provider",
    "models.model_call_timeout_seconds": "transport: a call that times out degrades the run, which is not stored",
    "models.data_agent_timeout_seconds": "transport, as above",
    "vision.concurrency": "how many calls run at once, not what they answer",
    "vision.breaker_threshold": "an open breaker degrades the run, which is not stored",
    "vision.region_cache_enabled": "the region cache returns the same answer",
    "vision.retry_pass_delay_seconds": "when the retry pass runs, not what it answers",
    "export.tts_voice": "the exports run after the cache",
    "export.object_markers_enabled": "the exports run after the cache",
    "export.toolbox_docx_enabled": "the exports run after the cache",
    "export.toolbox_pdf_ua_enabled": "the exports run after the cache",
    "export.toolbox_pdf_ua_math_bisect_budget": "the exports run after the cache",
    "paths.data_dir": "where files are written, not what they hold",
}

#: Toolbox providers the processing calls, by ``ToolboxConfig.providers`` key.
PROCESSING_PROVIDERS: frozenset[str] = frozenset({
    "toolbox_provider",
    "toolbox_layout_provider",
    "toolbox_pdf_provider",
    "toolbox_math_recognize_provider",
    "toolbox_math_provider",
    "toolbox_ocr_provider",
    "toolbox_page_ocr_provider",
    "toolbox_adjudicate_provider",
    "toolbox_orientation_provider",
    "toolbox_media_inspect_provider",
    "toolbox_text_normalize_provider",
})

#: Toolbox providers the processed document does not depend on, with reasons
#: (review of #561): changing one must not reprocess a document.
NOT_PROCESSING_PROVIDERS: dict[str, str] = {
    "toolbox_docx_provider": "the DOCX export runs after the cache",
    "toolbox_pdf_ua_provider": "the PDF/UA export runs after the cache",
    "toolbox_pdf_validate_provider": "the PDF/UA audit runs after the cache",
    "toolbox_table_provider": "configured, but the core calls no table capability",
}

#: Bumped when the fused extraction a reuse record holds is built differently,
#: so records written under the old strategy are not reused.
FUSION_REUSE_VERSION = "2026-11-16"


def config_fields(config: CoreConfig) -> dict[str, Any]:
    """Every field of ``config`` by ``group.field``."""
    values: dict[str, Any] = {}
    for group in fields(config):
        value = getattr(config, group.name)
        for field in fields(value):
            values[f"{group.name}.{field.name}"] = getattr(value, field.name)
    return values


def _json_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "items"):
        return {key: value[key] for key in sorted(value)}
    return value


def processing_identity(config: CoreConfig) -> dict[str, Any]:
    """The fields of ``config`` the processed document depends on, JSON-ready."""
    values = config_fields(config)
    identity = {name: _json_value(values[name]) for name in sorted(PROCESSING_FIELDS)}
    identity["toolbox.providers"] = _processing_providers(config.toolbox)
    return identity


#: The deployment and providers every stage that calls the Toolbox depends on.
_TOOLBOX = frozenset({"toolbox.base_url", "toolbox.base_urls", "toolbox.providers"})

#: What each stage of a run depends on, by ``PROCESSING_FIELDS`` name (#549).
#: A job's checkpoint records the identity of the stages its phase holds, so
#: a resumed run redoes the first phase whose stages changed and every phase
#: after it. Execution runs the handlers, which may read any of them.
STAGE_FIELDS: dict[str, frozenset[str]] = {
    "media": _TOOLBOX | {"toolbox.media_inspect_enabled"},
    "extraction": _TOOLBOX | {
        "fusion.mode",
        "fusion.secondary_provider",
        "fusion.apply_page_routes",
        "fusion.judge_max_pages",
        "document.max_pages",
        "document.legacy_unicode_repair",
        "document.slide_visual_coverage",
        "document.slide_fold_figure_labels",
    },
    "enrichment": _TOOLBOX | {
        field for field in PROCESSING_FIELDS if field.startswith("models.")
    } | {
        "vision.table_visual_review",
        "document.inline_math_detection",
        "document.formula_text_agreement_min",
    },
    # The gate reads the secondary provider of a dual fusion too.
    "planning": _TOOLBOX | {"toolbox.availability_gate", "fusion.secondary_provider"},
    "execution": PROCESSING_FIELDS,
}


def stage_identity(
    config: CoreConfig, stage: str, options: Mapping[str, Any] | None = None
) -> str:
    """A digest of what ``stage`` depends on in ``config``, plus the run's
    ``options`` outside it (the orchestrator's planner and dry run, the
    service's model revision; review of #578). No credentials: neither
    ``processing_identity`` nor those options hold any."""
    identity = processing_identity(config)
    subset: dict[str, Any] = {name: identity[name] for name in sorted(STAGE_FIELDS[stage])}
    if options:
        subset["options"] = {key: options[key] for key in sorted(options)}
    encoded = json.dumps(subset, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _processing_providers(toolbox: ToolboxConfig) -> dict[str, str]:
    return {
        key: toolbox.providers[key]
        for key in sorted(PROCESSING_PROVIDERS)
        if key in toolbox.providers
    }


def fusion_reuse_identity(fusion: FusionConfig, toolbox: ToolboxConfig) -> dict[str, Any]:
    """What a stored fused extraction depends on: the fusion options, the
    deployment and providers that extracted it, and the strategy version."""
    return {
        "version": FUSION_REUSE_VERSION,
        "fusion": {
            "mode": fusion.mode,
            "secondary_provider": fusion.secondary_provider,
            "apply_page_routes": fusion.apply_page_routes,
            "judge_max_pages": fusion.judge_max_pages,
        },
        "toolbox": {
            "base_url": toolbox.base_url,
            "base_urls": toolbox.base_urls,
            # The fused payload is the structure provider's and the secondary's.
            "structure_provider": toolbox.providers.get("toolbox_provider", ""),
        },
    }


__all__ = [
    "FUSION_REUSE_VERSION",
    "NOT_PROCESSING_FIELDS",
    "NOT_PROCESSING_PROVIDERS",
    "PROCESSING_FIELDS",
    "PROCESSING_PROVIDERS",
    "STAGE_FIELDS",
    "config_fields",
    "fusion_reuse_identity",
    "processing_identity",
    "stage_identity",
]
