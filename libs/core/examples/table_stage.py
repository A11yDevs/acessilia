"""Run one of the core's enrichment stages from a script (ADR-0016, acceptance).

The proof of concept the ADR asks for: the table-structure stage runs with an
explicit ``CoreConfig``, built here field by field, and with a model-call
runner of the script's own. Neither FastAPI nor anything from ``backend``
(the service and its settings) is imported; the script checks that before
it exits.

Usage::

    python libs/core/examples/table_stage.py MANIFEST.json SOURCE OUTPUT.json \\
        [--toolbox-url URL]

It reads a processing manifest, enriches its tables and writes the manifest
back. A table whose extracted text already holds its rows is read from that
text; any other is rendered by the Toolbox at ``--toolbox-url`` and read by
the model the config names, like the service does.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from acessilia_core.agents.model_calls import model_call_scope
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
from acessilia_core.manifest.models import ProcessingManifest
from acessilia_core.pipeline.enrichment.tables import _enrich_table_structures
from acessilia_core.toolbox.toolbox_client import TIMEOUT_KEYS
from acessilia_sdk.toolbox import PROVIDER_DEFAULTS, provider_default

T = TypeVar("T")

#: What the core must run without: the service, its settings and FastAPI.
FORBIDDEN = ("backend", "frontend", "fastapi")


class ThreadRunner:
    """A model-call runner of the script's own: each call in a thread, with
    its deadline. The service's runner adds admission limits; a script needs
    none."""

    async def run(self, call: Callable[[], T], *, timeout: float, label: str) -> T:
        return await asyncio.wait_for(asyncio.to_thread(call), timeout)


def explicit_config(*, toolbox_url: str, data_dir: Path) -> CoreConfig:
    """Every value the core reads, given here; nothing comes from settings.

    ``data_dir`` completes the config; the table stage writes nothing there.
    """
    return CoreConfig(
        toolbox=ToolboxConfig(
            base_url=toolbox_url,
            base_urls="",
            api_key="",
            timeout_seconds=600,
            retries=1,
            retry_backoff_seconds=0.5,
            extraction_timeout_seconds=900,
            providers=dict(PROVIDER_DEFAULTS),
            timeouts={key: 300 for key in TIMEOUT_KEYS},
            use_remote_cache=True,
            use_artifact_store=True,
            availability_gate="observe",
            catalog_refresh_seconds=60,
            catalog_stale_seconds=900,
            media_inspect_enabled=True,
            pdf_validate_enabled=True,
        ),
        models=ModelConfig(
            ai_client="toolbox",
            ollama_base_url="",
            ollama_model="",
            ollama_api_key="",
            openrouter_base_url="",
            openrouter_model="",
            openrouter_api_key="",
            openrouter_site_url="",
            openrouter_app_name="acessilia-core-example",
            openrouter_max_tokens=4096,
            # The service's default too (settings.toolbox_vlm_provider).
            toolbox_vlm_provider=provider_default("toolbox_vlm_provider"),
            model_call_timeout_seconds=600,
            vision_region_max_tokens=2000,
            data_agent_max_tokens=8192,
            data_agent_timeout_seconds=600,
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
            secondary_provider="",
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
            tts_voice="en-US-AriaNeural",
            object_markers_enabled=False,
            toolbox_docx_enabled=True,
            toolbox_pdf_ua_enabled=True,
            toolbox_pdf_ua_math_bisect_budget=8,
        ),
        paths=PathsConfig(data_dir=data_dir),
    )


def enrich_tables(manifest: ProcessingManifest, source: Path, config: CoreConfig) -> None:
    """The table-structure stage, as the orchestrator runs it, with ``config``."""
    with model_call_scope(ThreadRunner()):
        asyncio.run(
            _enrich_table_structures(
                manifest, source,
                vision=config.vision, toolbox=config.toolbox, models=config.models,
            )
        )


def forbidden_modules() -> list[str]:
    return sorted(name for name in sys.modules if name.split(".")[0] in FORBIDDEN)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("manifest", type=Path)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--toolbox-url", default="http://127.0.0.1:8002")
    args = parser.parse_args(argv)

    manifest = ProcessingManifest.model_validate_json(args.manifest.read_text(encoding="utf-8"))
    # The stage writes nothing under data_dir; the config only needs one.
    config = explicit_config(toolbox_url=args.toolbox_url, data_dir=args.output.parent)
    enrich_tables(manifest, args.source, config)
    args.output.write_text(
        json.dumps(manifest.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    loaded = forbidden_modules()
    if loaded:
        print(f"the core imported the service: {loaded}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
