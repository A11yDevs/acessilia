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
MOVED_GROUPS = {"document", "export", "fusion", "vision"}

#: Reads of a moved group's setting that wait for another group's pull
#: request, by file. Empty since the planning gate took the run's config.
PENDING_READS: dict[str, set[str]] = {}

#: Modules of a group still moving that already read no setting at all. The
#: toolbox group moves in three pull requests (planning gate, switches, client
#: factory); "toolbox" joins MOVED_GROUPS with the last one.
SETTINGS_FREE = {
    "backend/core/export/pandoc_exporter.py",
    "backend/core/pipeline/enrichment/formulas.py",
    "backend/core/pipeline/fusion.py",
    "backend/core/pipeline/preflight.py",
    "backend/core/planning/toolbox_gate.py",
    "backend/core/toolbox/media_inspect.py",
    "backend/core/toolbox/pdf_ua_audit.py",
    "backend/core/toolbox/text_spans.py",
}

#: Settings of the toolbox group already moved, until the whole group is in
#: MOVED_GROUPS: the switches and the extractor's options (toolbox PR 2).
MOVED_TOOLBOX_SETTINGS = {
    "toolbox_extraction_timeout_seconds",
    "toolbox_media_inspect_enabled",
    "toolbox_pdf_validate_enabled",
    "toolbox_use_artifact_store",
    "toolbox_use_remote_cache",
}


def test_the_settings_free_modules_read_no_setting() -> None:
    found = {rel: _scan(ROOT / rel) for rel in sorted(SETTINGS_FREE)}

    assert not {rel: scan for rel, scan in found.items() if scan[0] or scan[1]}


def test_the_moved_toolbox_settings_are_not_read() -> None:
    assert MOVED_TOOLBOX_SETTINGS <= set(FIELD_SETTINGS.values())
    found = {
        path.relative_to(ROOT).as_posix(): sorted(_scan(path)[0] & MOVED_TOOLBOX_SETTINGS)
        for path in sorted(CORE.rglob("*.py"))
        if _scan(path)[0] & MOVED_TOOLBOX_SETTINGS
    }

    assert not found, f"backend/core reads moved Toolbox settings again: {found}"


def test_the_moved_groups_are_not_read_from_settings() -> None:
    moved = {
        setting
        for path, setting in FIELD_SETTINGS.items()
        if path.split(".", 1)[0] in MOVED_GROUPS
    }
    found = {}
    for path in sorted(CORE.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        reads = (_scan(path)[0] & moved) - PENDING_READS.get(rel, set())
        if reads:
            found[rel] = sorted(reads)

    assert not found, f"backend/core reads moved settings again: {found}"


def test_the_pending_reads_are_still_pending() -> None:
    """An entry goes once its file stops reading the setting."""
    stale = {
        rel: sorted(keys - _scan(ROOT / rel)[0])
        for rel, keys in PENDING_READS.items()
        if keys - _scan(ROOT / rel)[0]
    }

    assert not stale, f"remove these PENDING_READS entries: {stale}"


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


def test_bind_config_gives_the_run_config_to_the_handlers_that_take_it() -> None:
    from backend.core.execution.executor import MethodRegistry
    from backend.core.pipeline.handlers.registry import bind_config

    received = []

    def with_config(manifest, obligation_id, *, config):
        received.append(config)

    def without_config(manifest, obligation_id):
        received.append("plain")

    registry = MethodRegistry()
    registry.register("with", with_config)
    registry.register("without", without_config)
    first, second = core_config(), core_config(fusion={"secondary_provider": "x"})

    bound = bind_config(registry, first)
    bound.get("with")(None, "o")
    bound.get("without")(None, "o")
    bind_config(bound, second).get("with")(None, "o")

    assert received == [first, "plain", second]
    assert registry.get("with") is with_config, "the given registry is left unchanged"
    assert [method for method, _ in bound.items()] == ["with", "without"]


def test_bind_config_keeps_the_registration_order() -> None:
    from backend.core.execution.executor import MethodRegistry
    from backend.core.pipeline.handlers.registry import bind_config

    registry = MethodRegistry()
    for method in ("zeta", "alpha", "mu"):
        registry.register(method, lambda manifest, obligation_id: None)

    bound = bind_config(registry, core_config())

    assert [method for method, _ in bound.items()] == ["zeta", "alpha", "mu"]


@pytest.mark.asyncio
async def test_a_run_executes_its_plan_with_handlers_bound_to_its_config(
    monkeypatch, tmp_path
) -> None:
    """Through ``execute``: the plan runs on the run's executor, not the unbound one."""
    from backend.core.pipeline import orchestrator as pddl
    from tests.pddl_support import build_element, build_manifest

    class Stop(Exception):
        pass

    async def no_media(*_args, **_kwargs):
        return None, {}

    async def no_enrichment(*_args, **_kwargs):
        return None

    monkeypatch.setattr(pddl, "_inspect_media", no_media)
    for name in (
        "_classify_formula_regions",
        "_enrich_picture_descriptions",
        "_mark_inline_math",
        "_enrich_formula_latex",
        "_enrich_table_structures",
        "_mark_table_inline_math",
    ):
        monkeypatch.setattr(pddl, name, no_enrichment)
    manifest = build_manifest([build_element("p-1", "paragraph", text="Text.")], [])
    received = []

    async def run_plan(*_args, executor, **_kwargs):
        received.append(executor)
        raise Stop

    orchestrator = build_orchestrator()
    orchestrator.information_structural = SimpleNamespace(process=lambda *a, **k: manifest)
    orchestrator.config = core_config(fusion={"secondary_provider": "from-the-run"})
    monkeypatch.setattr(orchestrator, "_run_plan", run_plan)

    with pytest.raises(Stop):
        await orchestrator.execute(tmp_path / "doc.pdf", tmp_path)

    [executor] = received
    handler = executor.registry.get("dual-provider-fusion")
    assert executor is not orchestrator.executor
    assert handler.keywords == {"config": orchestrator.config}


def _stub_the_run_before_planning(monkeypatch, orchestrator) -> None:
    from backend.core.pipeline import orchestrator as pddl
    from tests.pddl_support import build_element, build_manifest

    async def no_media(*_args, **_kwargs):
        return None, {}

    async def no_enrichment(*_args, **_kwargs):
        return None

    monkeypatch.setattr(pddl, "_inspect_media", no_media)
    for name in (
        "_classify_formula_regions",
        "_enrich_picture_descriptions",
        "_mark_inline_math",
        "_enrich_formula_latex",
        "_enrich_table_structures",
        "_mark_table_inline_math",
    ):
        monkeypatch.setattr(pddl, name, no_enrichment)
    manifest = build_manifest([build_element("p-1", "paragraph", text="Text.")], [])
    orchestrator.information_structural = SimpleNamespace(process=lambda *a, **k: manifest)


@pytest.mark.asyncio
async def test_concurrent_runs_each_get_their_own_config(monkeypatch, tmp_path) -> None:
    """Two runs at once over one shared registry: each handler sees its own run's config."""
    import asyncio

    from backend.core.execution.models import MethodResult

    def handler(manifest, obligation_id, *, config):
        return MethodResult(success=True, validated=True, message=config.fusion.secondary_provider)

    shared = build_orchestrator()
    shared.executor.registry.register("dual-provider-fusion", handler)
    seen: dict[str, list[str]] = {"a": [], "b": []}

    class Stop(Exception):
        pass

    def orchestrator_for(name: str):
        orchestrator = build_orchestrator()
        orchestrator.executor = shared.executor  # one registry for both runs
        orchestrator.config = core_config(fusion={"secondary_provider": f"provider-{name}"})
        _stub_the_run_before_planning(monkeypatch, orchestrator)

        async def run_plan(*_args, executor, **_kwargs):
            for _ in range(3):
                await asyncio.sleep(0)  # let the other run interleave
                result = await asyncio.to_thread(
                    executor.registry.get("dual-provider-fusion"), None, "o-fuse"
                )
                seen[name].append(result.message)
            raise Stop

        monkeypatch.setattr(orchestrator, "_run_plan", run_plan)
        return orchestrator

    runs = [orchestrator_for(name).execute(tmp_path / "doc.pdf", tmp_path) for name in ("a", "b")]
    results = await asyncio.gather(*runs, return_exceptions=True)

    assert all(isinstance(result, Stop) for result in results)
    assert seen == {"a": ["provider-a"] * 3, "b": ["provider-b"] * 3}
    assert shared.executor.registry.get("dual-provider-fusion") is handler


@pytest.mark.asyncio
async def test_a_replan_runs_on_the_executor_of_its_run(monkeypatch) -> None:
    """The new plan of a replan executes on the same bound executor as the first."""
    import asyncio

    from tests.pddl_support import build_element, build_manifest, build_obligation

    orchestrator = build_orchestrator(max_replans=1)
    obligation = build_obligation("describe-image", ["p-1"], ["human-review"])
    obligation.selected = True  # open and selected: a new plan can still satisfy it
    manifest = build_manifest([build_element("p-1", "paragraph", text="Text.")], [obligation])
    run_executor = orchestrator._run_executor(core_config())
    received = []

    async def run_plan(*_args, executor, **_kwargs):
        received.append(executor)
        return manifest, SimpleNamespace(replan_required=False, status="completed")

    async def no_save(*_args, **_kwargs):
        return None

    monkeypatch.setattr(orchestrator, "_run_plan", run_plan)
    monkeypatch.setattr(orchestrator, "_build_plan", lambda *a, **k: ("plan", None))
    monkeypatch.setattr("backend.core.pipeline.orchestrator._save_plan", no_save)

    await orchestrator._replan_until_done(
        manifest,
        SimpleNamespace(replan_required=True, status="replan-required"),
        "first-plan",
        None,
        [],
        None,
        asyncio.get_running_loop(),
        task_id=None,
        planning_manifest=manifest,
        availability=None,
        replans=0,
        executor=run_executor,
    )

    assert received == [run_executor]


@pytest.mark.parametrize(
    ("function", "parameter"),
    [
        ("backend.core.manifest.toolbox_extractor:ToolboxManifestExtractor.extract", "fusion"),
        (
            "backend.core.agents.informational_structural:InformationalStructuralAgent.process",
            "document",
        ),
        (
            "backend.core.agents.informational_structural:InformationalStructuralAgent.process",
            "fusion",
        ),
        ("backend.core.pipeline.fusion:extract_fused", "secondary_provider"),
        ("backend.core.planning.toolbox_gate:evaluate", "config"),
        ("backend.core.manifest.toolbox_extractor:ToolboxManifestExtractor.extract", "toolbox"),
        (
            "backend.core.agents.informational_structural:InformationalStructuralAgent.process",
            "toolbox",
        ),
        ("backend.core.pipeline.fusion:extract_fused", "toolbox"),
        ("backend.core.pipeline.enrichment.formulas:_enrich_formula_latex", "toolbox"),
        ("backend.core.toolbox.media_inspect:inspect_source_media", "toolbox"),
        ("backend.core.toolbox.pdf_ua_audit:audit_pdf_ua", "toolbox"),
        ("backend.core.toolbox.text_spans:fetch_text_spans", "toolbox"),
        ("backend.core.export.exporters.docx_exporter:export_docx", "toolbox"),
        ("backend.core.export.exporters.pdf_exporter:export_pdf_ua", "toolbox"),
        ("backend.core.export.pandoc_exporter:toolbox_export_docx", "toolbox"),
        ("backend.core.export.pandoc_exporter:toolbox_export_pdf_ua", "toolbox"),
        (
            "backend.core.pipeline.handlers.fusion:_handle_single_provider_method",
            "config",
        ),
        ("backend.core.agents.vision_agent:VisionAgent.__init__", "region_cache"),
        ("backend.core.pipeline.enrichment.common:_retry_failed", "delay_seconds"),
        ("backend.core.pipeline.enrichment.pictures:_enrich_picture_descriptions", "vision"),
        ("backend.core.pipeline.enrichment.formulas:_classify_formula_regions", "vision"),
        ("backend.core.pipeline.enrichment.formulas:_enrich_formula_latex", "vision"),
        ("backend.core.pipeline.enrichment.tables:_enrich_table_structures", "vision"),
        ("backend.core.pipeline.enrichment.tables:_tables_to_read", "visual_review"),
        ("backend.core.pipeline.handlers.inspection:_render_source_page", "dpi"),
        ("backend.core.pipeline.handlers.inspection:_inspect_region", "region_cache"),
        ("backend.core.pipeline.handlers.inspection:_inspect_page", "region_cache"),
        (
            "backend.core.pipeline.handlers.inspection:_handle_pymupdf_region_method",
            "config",
        ),
        (
            "backend.core.pipeline.handlers.inspection:_handle_vision_page_inspection_method",
            "config",
        ),
    ],
)
def test_the_run_config_parameters_are_required(function, parameter) -> None:
    """Required keywords, with no default a caller could fall back on.

    Checked on the signature, so a missing argument is a ``TypeError`` at the
    call without calling with too few arguments here.
    """
    import importlib
    import inspect

    module_name, qualname = function.split(":")
    target = importlib.import_module(module_name)
    for part in qualname.split("."):
        target = getattr(target, part)
    signature = inspect.signature(target).parameters[parameter]

    assert signature.default is inspect.Parameter.empty
    assert signature.kind is inspect.Parameter.KEYWORD_ONLY
