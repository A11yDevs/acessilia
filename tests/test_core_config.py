"""The core's explicit configuration and the service's builder (ADR-0016, step 3).

``CoreConfig`` holds every value the core reads from its caller, grouped by
responsibility; ``core_config_from_settings`` builds it from the service's
settings. Until step 3 ends, the orchestrator builds one per run when it is
given none, and the stages not yet moved keep reading ``settings``.
"""

from __future__ import annotations

import ast
import copy
import dataclasses
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.config import settings as settings_module
from backend.config.core_config import core_config_from_settings
from backend.core.config import CoreConfig
from backend.core.pipeline import preflight as pipeline_preflight
from backend.core.toolbox.toolbox_client import PROVIDER_DEFAULTS, TIMEOUT_KEYS
from tests.core_config_support import core_config
from tests.pddl_support import build_orchestrator

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "backend" / "core"
BUILDER = ROOT / "backend" / "config" / "core_config.py"

#: Process setup, not part of a run: the logger and the catalogs read them at
#: start-up. The last step-3 pull request decides how they reach the core.
PROCESS_SETUP_KEYS = {"log_level", "logs_dir", "i18n_locales_active"}

#: Keys the core reads through ``getattr(settings, key)`` over these tables.
DYNAMIC_KEYS = set(PROVIDER_DEFAULTS) | set(TIMEOUT_KEYS)

#: The one module allowed a non-literal ``getattr(settings, ...)``: the SDK
#: client configuration, over the provider and timeout tables.
DYNAMIC_READERS = {"backend/core/toolbox/toolbox_client.py"}

#: Which setting fills each field, written out so that a swapped pair fails.
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
    "paths.data_dir": "data_dir",
    **{f"toolbox.providers[{key}]": key for key in PROVIDER_DEFAULTS},
    **{f"toolbox.timeouts[{key}]": key for key in TIMEOUT_KEYS},
}

SETTINGS_MODULE = "backend.config.settings"


def _scan(path: Path, rel: str | None = None) -> tuple[set[str], list[str]]:
    """The settings ``path`` reads, and the reads the scan cannot name.

    Reads are ``settings.<key>``, ``getattr(settings, "<key>")`` and, in
    ``DYNAMIC_READERS`` only, ``getattr(settings, key)`` over the tables. Any
    other ``getattr(settings, ...)``, or a binding of the settings under
    another name, is unnamed: the scan could not tell which key it reads.
    """
    rel = rel or path.relative_to(ROOT).as_posix()
    keys: set[str] = set()
    unnamed: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "settings":
                keys.add(node.attr)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "settings"
        ):
            name = node.args[1] if len(node.args) > 1 else None
            if isinstance(name, ast.Constant) and isinstance(name.value, str):
                keys.add(name.value)
            elif rel in DYNAMIC_READERS:
                keys |= DYNAMIC_KEYS
            else:
                unnamed.append(f"{rel}:{node.lineno} {ast.unparse(node)}")
        elif isinstance(node, ast.ImportFrom) and node.module == SETTINGS_MODULE:
            unnamed += [
                f"{rel}:{node.lineno} settings bound as {alias.asname}"
                for alias in node.names
                if alias.name == "settings" and alias.asname not in (None, "settings")
            ]
        elif isinstance(node, ast.ImportFrom) and node.module == "backend.config":
            unnamed += [
                f"{rel}:{node.lineno} imports the settings module"
                for alias in node.names
                if alias.name == "settings"
            ]
        elif isinstance(node, ast.Import):
            unnamed += [
                f"{rel}:{node.lineno} imports the settings module"
                for alias in node.names
                if alias.name == SETTINGS_MODULE
            ]
    return keys, unnamed


def _core_reads() -> tuple[set[str], list[str]]:
    keys: set[str] = set()
    unnamed: list[str] = []
    for path in sorted(CORE.rglob("*.py")):
        found, hidden = _scan(path)
        keys |= found
        unnamed += hidden
    return keys, unnamed


def _leaves(config: CoreConfig) -> dict[str, object]:
    """Every value of ``config`` by its path, the providers and timeouts one by one."""
    leaves: dict[str, object] = {}
    for group in dataclasses.fields(config):
        value = getattr(config, group.name)
        for field in dataclasses.fields(value):
            item = getattr(value, field.name)
            if field.name in {"providers", "timeouts"}:
                for key, entry in item.items():
                    leaves[f"{group.name}.{field.name}[{key}]"] = entry
            else:
                leaves[f"{group.name}.{field.name}"] = item
    return leaves


def test_the_builder_covers_every_setting_the_core_reads() -> None:
    """A stage that starts reading a new key must get a field for it."""
    keys, unnamed = _core_reads()
    missing = sorted(keys - set(FIELD_SETTINGS.values()) - PROCESS_SETUP_KEYS)

    assert not unnamed, "settings reads the scan cannot name:\n" + "\n".join(unnamed)
    assert not missing, f"settings read by backend/core with no CoreConfig field: {missing}"


#: The groups the core now receives from its caller: none of their settings
#: may be read again. Each step-3 pull request adds the group it moves.
MOVED_GROUPS = {"document", "export"}


def test_the_moved_groups_are_not_read_from_settings() -> None:
    keys, _ = _core_reads()
    moved = {
        setting
        for path, setting in FIELD_SETTINGS.items()
        if path.split(".", 1)[0] in MOVED_GROUPS
    }

    assert not sorted(keys & moved), "backend/core reads moved settings again"


@pytest.mark.parametrize(
    "source",
    [
        "from backend.config.settings import settings\nx = settings.bot_token\n",
        "from backend.config.settings import settings\nx = getattr(settings, 'bot_token')\n",
    ],
)
def test_the_scan_names_the_key_of_a_read(tmp_path, source) -> None:
    probe = tmp_path / "probe.py"
    probe.write_text(source, encoding="utf-8")

    assert _scan(probe, "backend/core/probe.py") == ({"bot_token"}, [])


@pytest.mark.parametrize(
    "source",
    [
        "from backend.config.settings import settings as app\nx = app.bot_token\n",
        "from backend.config import settings\nx = settings.settings.bot_token\n",
        "import backend.config.settings\n",
        "from backend.config.settings import settings\nname = 'bot_token'\nx = getattr(settings, name)\n",
    ],
)
def test_the_scan_reports_a_read_it_cannot_name(tmp_path, source) -> None:
    probe = tmp_path / "probe.py"
    probe.write_text(source, encoding="utf-8")

    assert _scan(probe, "backend/core/probe.py")[1]


def test_each_field_takes_its_setting() -> None:
    """Every field holds the value of the setting the table names for it."""
    distinct = copy.copy(settings_module.settings)
    for key in set(FIELD_SETTINGS.values()):
        object.__setattr__(distinct, key, f"value-of-{key}")

    leaves = _leaves(core_config_from_settings(distinct))

    assert leaves == {path: f"value-of-{key}" for path, key in FIELD_SETTINGS.items()}


def test_a_caller_mapping_is_copied_read_only() -> None:
    providers = {"toolbox_provider": "docling"}
    base = core_config_from_settings().toolbox
    toolbox = dataclasses.replace(base, providers=providers)
    providers["toolbox_provider"] = "other"

    assert toolbox.providers["toolbox_provider"] == "docling"
    with pytest.raises(TypeError):
        toolbox.providers["toolbox_provider"] = "other"  # type: ignore[index]


def test_the_configuration_is_frozen() -> None:
    config = core_config_from_settings()

    with pytest.raises(dataclasses.FrozenInstanceError):
        config.document.max_pages = 1  # type: ignore[misc]
    with pytest.raises(TypeError):
        config.toolbox.providers["toolbox_provider"] = "other"  # type: ignore[index]


def test_the_test_helper_replaces_only_the_named_fields() -> None:
    base = core_config_from_settings()
    config = core_config(document={"max_pages": 3})

    assert config.document.max_pages == 3
    assert dataclasses.replace(config.document, max_pages=base.document.max_pages) == base.document
    assert config.toolbox == base.toolbox


def test_the_config_module_imports_only_the_standard_library() -> None:
    """The core's side of the boundary that step 5 will check."""
    tree = ast.parse((CORE / "config.py").read_text(encoding="utf-8"))
    imported = {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    } | {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert imported <= {"__future__", "collections", "dataclasses", "pathlib", "types"}


def _over_the_limit(monkeypatch, pages: int) -> object:
    async def no_inspection(*_args, **_kwargs):
        return None

    monkeypatch.setattr(pipeline_preflight, "inspect_source_media", no_inspection)
    orchestrator = build_orchestrator()
    manifest = SimpleNamespace(pages=[object()] * pages)
    orchestrator.information_structural = SimpleNamespace(process=lambda *a, **k: manifest)
    return orchestrator


@pytest.mark.asyncio
async def test_a_run_without_a_config_reads_the_settings_of_its_start(monkeypatch, tmp_path) -> None:
    """The bridge: built per run, so a setting changed after construction applies."""
    orchestrator = _over_the_limit(monkeypatch, pages=3)
    monkeypatch.setattr(settings_module.settings, "max_pages", 2)

    with pytest.raises(pipeline_preflight.DocumentTooLargeError):
        await orchestrator.execute(tmp_path / "doc.pdf", tmp_path)


@pytest.mark.asyncio
async def test_a_given_config_wins_over_the_settings(monkeypatch, tmp_path) -> None:
    orchestrator = _over_the_limit(monkeypatch, pages=3)
    orchestrator.config = core_config(document={"max_pages": 2})
    monkeypatch.setattr(settings_module.settings, "max_pages", 50)

    with pytest.raises(pipeline_preflight.DocumentTooLargeError):
        await orchestrator.execute(tmp_path / "doc.pdf", tmp_path)
