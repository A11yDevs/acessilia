"""The core's explicit configuration and the service's builder (ADR-0016, step 3).

``CoreConfig`` holds every value the core reads from its caller, grouped by
responsibility; ``core_config_from_settings`` builds it from the service's
settings. A run requires its config, its model-call runner and its ports
(``execute(..., config=, model_calls=, ports=)``; ``tests/test_run_ports.py``
covers the ports), and an Agno tool without a run
requires the config its agent was built with: nothing falls back to
``settings``.
"""

from __future__ import annotations

from backend.core.agents.model_calls import current_model_calls

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
from backend.core.ports import RunPorts
from backend.core.toolbox.toolbox_client import PROVIDER_DEFAULTS, TIMEOUT_KEYS
from tests.core_config_support import core_config
from tests.pddl_support import build_orchestrator

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "backend" / "core"
BUILDER = ROOT / "backend" / "config" / "core_config.py"


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

    Reads are ``settings.<key>`` and ``getattr(settings, "<key>")``. Any other
    ``getattr(settings, ...)``, or a binding of the settings under another
    name, is unnamed: the scan could not tell which key it reads. (The client
    binding read the provider and timeout tables that way until the toolbox
    group moved, ADR-0016 step 3.)
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


def test_the_core_reads_no_settings() -> None:
    """ADR-0016 step 3 is complete: a run takes its CoreConfig, and the process
    setup (logger, catalogs) is passed at startup. No core module reads a
    setting, by name or otherwise."""
    keys, unnamed = _core_reads()

    assert not unnamed, "settings reads the scan cannot name:\n" + "\n".join(unnamed)
    assert not keys, f"settings read by backend/core: {sorted(keys)}"


def test_the_core_imports_nothing_from_the_service_config() -> None:
    """No module of ``backend/core`` imports ``backend.config``, inside a
    function included: the service builds the configuration and passes it."""
    found = []
    for path in sorted(CORE.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            modules = (
                [node.module or ""] if isinstance(node, ast.ImportFrom)
                else [alias.name for alias in node.names] if isinstance(node, ast.Import)
                else []
            )
            if any(m == "backend.config" or m.startswith("backend.config.") for m in modules):
                found.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")

    assert not found, "backend/core imports backend.config:\n" + "\n".join(found)


#: The groups the core now receives from its caller: none of their settings
#: may be read again. Each step-3 pull request adds the group it moves.
MOVED_GROUPS = {"document", "export", "fusion", "models", "paths", "toolbox", "vision"}

#: Reads of a moved group's setting that wait for another group's pull
#: request, by file. Empty since the model client took the run's
#: ``ModelConfig`` and ``ToolboxConfig`` (models group).
PENDING_READS: dict[str, set[str]] = {}

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
async def test_a_run_needs_its_config_and_model_call_runner(monkeypatch, tmp_path) -> None:
    """No bridge: a run without either is a ``TypeError``, not the settings'."""
    orchestrator = _over_the_limit(monkeypatch, pages=3)

    with pytest.raises(TypeError, match="config"):
        await orchestrator.execute(tmp_path / "doc.pdf", tmp_path, model_calls=current_model_calls(), ports=RunPorts.none())
    with pytest.raises(TypeError, match="model_calls"):
        await orchestrator.execute(tmp_path / "doc.pdf", tmp_path, config=core_config())


@pytest.mark.asyncio
async def test_a_given_config_wins_over_the_settings(monkeypatch, tmp_path) -> None:
    orchestrator = _over_the_limit(monkeypatch, pages=3)
    run_config = core_config(document={"max_pages": 2})
    monkeypatch.setattr(settings_module.settings, "max_pages", 50)

    with pytest.raises(pipeline_preflight.DocumentTooLargeError):
        await orchestrator.execute(tmp_path / "doc.pdf", tmp_path, config=run_config, model_calls=current_model_calls(), ports=RunPorts.none())


def test_bind_run_gives_the_run_config_to_the_handlers_that_take_it() -> None:
    from backend.core.execution.executor import MethodRegistry
    from backend.core.pipeline.handlers.registry import bind_run

    received = []

    def with_config(manifest, obligation_id, *, config):
        received.append(config)

    def without_config(manifest, obligation_id):
        received.append("plain")

    registry = MethodRegistry()
    registry.register("with", with_config)
    registry.register("without", without_config)
    first, second = core_config(), core_config(fusion={"secondary_provider": "x"})

    bound = bind_run(registry, first, RunPorts.none())
    bound.get("with")(None, "o")
    bound.get("without")(None, "o")
    bind_run(bound, second, RunPorts.none()).get("with")(None, "o")

    assert received == [first, "plain", second]
    assert registry.get("with") is with_config, "the given registry is left unchanged"
    assert [method for method, _ in bound.items()] == ["with", "without"]


def test_bind_run_keeps_the_registration_order() -> None:
    from backend.core.execution.executor import MethodRegistry
    from backend.core.pipeline.handlers.registry import bind_run

    registry = MethodRegistry()
    for method in ("zeta", "alpha", "mu"):
        registry.register(method, lambda manifest, obligation_id: None)

    bound = bind_run(registry, core_config(), RunPorts.none())

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
    run_config = core_config(fusion={"secondary_provider": "from-the-run"})
    monkeypatch.setattr(orchestrator, "_run_plan", run_plan)

    with pytest.raises(Stop):
        await orchestrator.execute(tmp_path / "doc.pdf", tmp_path, config=run_config, model_calls=current_model_calls(), ports=RunPorts.none())

    [executor] = received
    handler = executor.registry.get("dual-provider-fusion")
    assert executor is not orchestrator.executor
    assert handler.keywords == {"config": run_config}


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

    runs = [
        orchestrator_for(name).execute(
            tmp_path / "doc.pdf", tmp_path,
            config=core_config(fusion={"secondary_provider": f"provider-{name}"}),
            model_calls=current_model_calls(), ports=RunPorts.none()
        )
        for name in ("a", "b")
    ]
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
    run_executor = orchestrator._run_executor(core_config(), RunPorts.none())
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
        ("backend.core.pipeline.orchestrator:PddlAccessibilityOrchestrator.execute", "config"),
        ("backend.core.pipeline.orchestrator:PddlAccessibilityOrchestrator.execute", "model_calls"),
        ("backend.core.pipeline.orchestrator:PddlAccessibilityOrchestrator.execute", "ports"),
        ("backend.core.pipeline.enrichment.pictures:_enrich_picture_descriptions", "region_cache"),
        ("backend.core.pipeline.enrichment.formulas:_classify_formula_regions", "region_cache"),
        ("backend.core.pipeline.enrichment.formulas:_enrich_formula_latex", "region_cache"),
        ("backend.core.pipeline.handlers.inspection:_handle_pymupdf_region_method", "ports"),
        (
            "backend.core.pipeline.handlers.inspection:_handle_vision_page_inspection_method",
            "ports",
        ),
        ("backend.core.manifest.toolbox_extractor:ToolboxManifestExtractor.extract", "paths"),
        (
            "backend.core.agents.informational_structural:InformationalStructuralAgent.process",
            "paths",
        ),
        ("backend.core.manifest.toolbox_extractor:_persist_fusion_reuse", "data_dir"),
        ("backend.core.manifest.toolbox_extractor:_persist_secondary_extraction", "data_dir"),
        ("backend.core.pipeline.handlers.fusion:_persist_fusion_payload", "data_dir"),
        ("backend.core.pipeline.handlers.inspection:_save_region_artifact", "data_dir"),
        ("backend.core.agents.vision_agent:VisionAgent.__init__", "models"),
        ("backend.core.agents.data_agent:DataAgent.__init__", "models"),
        ("backend.core.agents.data_agent:DataAgent.__init__", "toolbox"),
        ("backend.core.pipeline.enrichment.formulas:_classify_formula_regions", "models"),
        ("backend.core.pipeline.enrichment.formulas:_enrich_formula_latex", "models"),
        ("backend.core.pipeline.enrichment.pictures:_enrich_picture_descriptions", "models"),
        ("backend.core.pipeline.enrichment.tables:_enrich_table_structures", "models"),
        ("backend.core.pipeline.handlers.inspection:_inspect_region", "models"),
        ("backend.core.pipeline.handlers.inspection:_inspect_page", "models"),
        ("backend.core.pipeline.toolbox:_toolbox_render", "toolbox"),
        ("backend.core.pipeline.toolbox:_toolbox_formula_crop", "toolbox"),
        ("backend.core.pipeline.enrichment.common:_extract_picture_bytes", "toolbox"),
        ("backend.core.pipeline.enrichment.formulas:_formula_recognition_crop", "toolbox"),
        ("backend.core.pipeline.enrichment.formulas:_classify_formula_regions", "toolbox"),
        ("backend.core.pipeline.enrichment.pictures:_enrich_picture_descriptions", "toolbox"),
        ("backend.core.pipeline.enrichment.tables:_enrich_table_structures", "toolbox"),
        ("backend.core.pipeline.judge:_render_page_png", "toolbox"),
        ("backend.core.pipeline.judge:_judge_page", "toolbox"),
        ("backend.core.pipeline.judge:_judge_one_page", "toolbox"),
        ("backend.core.pipeline.handlers.inspection:_render_inspection_region", "toolbox"),
        ("backend.core.pipeline.handlers.inspection:_render_source_page", "toolbox"),
        ("backend.core.pipeline.handlers.inspection:_inspect_region", "toolbox"),
        ("backend.core.pipeline.handlers.inspection:_inspect_page", "toolbox"),
        ("backend.core.agents.vision_agent:VisionAgent.__init__", "toolbox"),
        ("backend.core.toolbox.vision_payload:downscale_image", "toolbox"),
        ("backend.core.toolbox.toolbox_math_tools:toolbox_recognize_formula", "toolbox"),
        ("backend.core.toolbox.toolbox_math_tools:toolbox_convert_latex", "toolbox"),
        ("backend.core.toolbox.toolbox_math_tools:toolbox_verbalize_latex", "toolbox"),
        ("backend.core.pipeline.handlers.formula:_handle_mathml_method", "config"),
        ("backend.core.pipeline.handlers.formula:_handle_latex_verbalizer_method", "config"),
        ("backend.core.pipeline.handlers.judge:_handle_vlm_pairwise_judge_method", "config"),
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


@pytest.mark.parametrize(
    ("function", "parameter"),
    [
        ("backend.core.pipeline.preflight:_inspect_media", "toolbox"),
        ("backend.core.agents.ai_client:get_agno_model", "models"),
        ("backend.core.agents.ai_client:get_agno_model", "toolbox"),
        ("backend.core.agents.ai_client:active_model_name", "models"),
        ("backend.core.toolbox.toolbox_client:make_toolbox_client", "toolbox"),
        ("backend.core.toolbox.toolbox_client:toolbox_client_config", "toolbox"),
        ("backend.core.toolbox.toolbox_client:toolbox_endpoints", "toolbox"),
        ("backend.core.toolbox.toolbox_client:toolbox_vlm_endpoint", "toolbox"),
        ("backend.core.pipeline.toolbox:_render_client", "toolbox"),
        ("backend.core.pipeline.fusion:_structure_client", "toolbox"),
        ("backend.core.pipeline.canonical_builder:latex_to_mathml", "toolbox"),
        ("backend.core.pipeline.canonical_builder:verbalize_latex", "toolbox"),
        ("backend.core.pipeline.canonical_builder:verbalize_inline_latex", "toolbox"),
        ("backend.core.pipeline.canonical_builder:_ToolboxMathEnricher.__init__", "toolbox"),
        ("backend.core.pipeline.enrichment.inline_math:_TextSpanReader.__init__", "toolbox"),
        ("backend.core.pipeline.enrichment.inline_math:_mark_inline_math", "text_spans"),
        ("backend.core.pipeline.enrichment.inline_math:_mark_table_inline_math", "text_spans"),
    ],
)
def test_the_internal_run_parameters_have_no_default(function, parameter) -> None:
    """Positional in these helpers, but never defaulted: the run's
    ``ToolboxConfig`` (the client factory, the endpoints, the render and
    fusion clients, the math enricher), its ``ModelConfig`` (the model
    factory, ``active_model_name``) and the inline math steps' reader, which
    they no longer build themselves.
    """
    import importlib
    import inspect

    module_name, qualname = function.split(":")
    target = importlib.import_module(module_name)
    for part in qualname.split("."):
        target = getattr(target, part)

    assert inspect.signature(target).parameters[parameter].default is inspect.Parameter.empty


#: Functions whose run configuration is required, by the name callers use.
#: Every call to them outside the tests, in the core, the service, the
#: frontends and the scripts, must bind to the signature (review of #555:
#: the AgentOS runtime in ``frontend/`` kept the old call).
CALLERS_CHECKED = {
    "get_agno_model": "backend.core.agents.ai_client:get_agno_model",
    "active_model_name": "backend.core.agents.ai_client:active_model_name",
    "make_toolbox_client": "backend.core.toolbox.toolbox_client:make_toolbox_client",
    "toolbox_client_config": "backend.core.toolbox.toolbox_client:toolbox_client_config",
    "toolbox_endpoints": "backend.core.toolbox.toolbox_client:toolbox_endpoints",
    "toolbox_vlm_endpoint": "backend.core.toolbox.toolbox_client:toolbox_vlm_endpoint",
    "VisionAgent": "backend.core.agents.vision_agent:VisionAgent",
    "DataAgent": "backend.core.agents.data_agent:DataAgent",
    "extract_fused": "backend.core.pipeline.fusion:extract_fused",
    "inspect_source_media": "backend.core.toolbox.media_inspect:inspect_source_media",
    "audit_pdf_ua": "backend.core.toolbox.pdf_ua_audit:audit_pdf_ua",
    "fetch_text_spans": "backend.core.toolbox.text_spans:fetch_text_spans",
    "export_docx": "backend.core.export.exporters.docx_exporter:export_docx",
    "export_pdf_ua": "backend.core.export.exporters.pdf_exporter:export_pdf_ua",
    "setup_logger": "backend.core.logger:setup_logger",
}

CALLER_ROOTS = ("backend", "frontend", "scripts")

#: Methods with generic names, checked only on the calls that pass a keyword
#: no other method of that name takes: ``fusion=`` for the extractor's
#: ``extract`` and the structural agent's ``process`` (review of #557), and
#: ``structured_output=`` for the orchestrator's ``execute``.
METHOD_CALLERS_CHECKED = {
    "extract": (
        "backend.core.manifest.toolbox_extractor:ToolboxManifestExtractor.extract", "fusion"
    ),
    "process": (
        "backend.core.agents.informational_structural:InformationalStructuralAgent.process",
        "fusion",
    ),
    "execute": (
        "backend.core.pipeline.orchestrator:PddlAccessibilityOrchestrator.execute",
        "structured_output",
    ),
}

#: ``service.process`` (review of #559): a call ``service.process(...)``, or a
#: bare ``process(...)`` in a module that imports it from ``backend.service``.
#: Its optional config is a temporary bridge for the external adapter; the
#: caller scan below still requires every in-repository call to pass config=.
SERVICE_PROCESS = "backend.service:process"

#: Receivers that are the orchestrator, whatever the call passes: the
#: service's ``agente`` and any name ending in ``orchestrator`` (review of #559).
def _is_orchestrator(receiver: ast.AST) -> bool:
    if isinstance(receiver, ast.Name):
        return receiver.id == "agente" or receiver.id.endswith("orchestrator")
    if isinstance(receiver, ast.Call) and isinstance(receiver.func, ast.Name):
        return receiver.func.id in {"PddlAccessibilityOrchestrator", "build_orchestrator"}
    return False


def _imports_service_process(tree: ast.AST) -> bool:
    return any(
        isinstance(node, ast.ImportFrom) and node.module == "backend.service"
        and any(alias.name == "process" and alias.asname is None for alias in node.names)
        for node in ast.walk(tree)
    )


def _resolve(target: str):
    import importlib

    module_name, qualname = target.split(":")
    value = importlib.import_module(module_name)
    for part in qualname.split("."):
        value = getattr(value, part)
    return value


def test_every_caller_passes_the_run_configuration() -> None:
    """Each call binds to the signature: no required config is left out."""
    import inspect

    signatures = {name: inspect.signature(_resolve(target)) for name, target in CALLERS_CHECKED.items()}
    methods = {
        name: (inspect.signature(_resolve(target)), marker)
        for name, (target, marker) in METHOD_CALLERS_CHECKED.items()
    }
    service_process = inspect.signature(_resolve(SERVICE_PROCESS))
    unbound = []
    for root in CALLER_ROOTS:
        for path in sorted((ROOT / root).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imports_process = _imports_service_process(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = func.id if isinstance(func, ast.Name) else (
                    func.attr if isinstance(func, ast.Attribute) else None
                )
                keywords = {keyword.arg for keyword in node.keywords}
                if name == "process" and (
                    (isinstance(func, ast.Name) and imports_process)
                    or (isinstance(func, ast.Attribute)
                        and isinstance(func.value, ast.Name) and func.value.id == "service")
                ):
                    signature, receiver = service_process, []
                    if "config" not in keywords and not any(
                        keyword.arg is None for keyword in node.keywords
                    ):
                        rel = path.relative_to(ROOT).as_posix()
                        unbound.append(
                            f"{rel}:{node.lineno} process: missing explicit config="
                        )
                elif name in methods and isinstance(func, ast.Attribute) and (
                    methods[name][1] in keywords
                    or (name == "execute" and _is_orchestrator(func.value))
                ):
                    signature, receiver = methods[name][0], [func.value]
                elif name in signatures:
                    signature, receiver = signatures[name], []
                else:
                    continue
                if any(isinstance(arg, ast.Starred) for arg in node.args) or any(
                    keyword.arg is None for keyword in node.keywords
                ):
                    continue  # a splat: the scan cannot count what it passes
                try:
                    signature.bind(
                        *receiver, *node.args,
                        **{keyword.arg: keyword.value for keyword in node.keywords},
                    )
                except TypeError as error:
                    rel = path.relative_to(ROOT).as_posix()
                    unbound.append(f"{rel}:{node.lineno} {name}: {error}")

    assert not unbound, "calls that leave out a required argument:\n" + "\n".join(unbound)


def test_the_caller_scan_sees_a_call_that_leaves_out_the_config() -> None:
    import inspect

    signature = inspect.signature(_resolve(CALLERS_CHECKED["get_agno_model"]))
    [call] = [
        node for node in ast.walk(ast.parse("get_agno_model(timeout_seconds=5)"))
        if isinstance(node, ast.Call)
    ]

    with pytest.raises(TypeError):
        signature.bind(*call.args, **{k.arg: k.value for k in call.keywords})


def test_the_caller_scan_sees_a_method_call_that_leaves_out_the_paths() -> None:
    import inspect

    signature = inspect.signature(_resolve(METHOD_CALLERS_CHECKED["process"][0]))
    [call] = [
        node for node in ast.walk(ast.parse(
            "agent.process(source, document=d, fusion=f, toolbox=t)"
        ))
        if isinstance(node, ast.Call)
    ]

    with pytest.raises(TypeError, match="paths"):
        signature.bind(call.func.value, *call.args, **{k.arg: k.value for k in call.keywords})


def test_the_agno_tools_refuse_to_run_without_their_agent_config(tmp_path) -> None:
    """No bridge: an Agno tool without a run takes the config its agent was built with."""
    from backend.core.agents.fusion_agent import FusionAgent
    from backend.core.agents.informational_structural import InformationalStructuralAgent

    with pytest.raises(RuntimeError, match="config="):
        InformationalStructuralAgent(extractor=object()).extract_processing_manifest(
            str(tmp_path / "doc.pdf")
        )
    with pytest.raises(RuntimeError, match="config="):
        FusionAgent().fuse_providers(str(tmp_path / "doc.pdf"))


def test_the_agno_tools_run_with_their_agent_config(monkeypatch, tmp_path) -> None:
    from backend.core.agents.fusion_agent import FusionAgent
    from backend.core.agents.informational_structural import InformationalStructuralAgent

    config = core_config(fusion={"secondary_provider": "from-the-agent"})
    seen = {}

    def process(self, _path, **groups):
        seen["process"] = groups
        return SimpleNamespace(model_dump=lambda **_k: {})

    def fuse(self, _path, **options):
        seen["fuse"] = options
        return {}

    monkeypatch.setattr(InformationalStructuralAgent, "process", process)
    monkeypatch.setattr(FusionAgent, "process_fuse_providers", fuse)

    InformationalStructuralAgent(extractor=object(), config=config).extract_processing_manifest(
        str(tmp_path / "doc.pdf")
    )
    FusionAgent(config=config).fuse_providers(str(tmp_path / "doc.pdf"))

    assert all(seen["process"][name] is getattr(config, name)
               for name in ("document", "fusion", "toolbox", "paths"))
    assert seen["fuse"]["secondary_provider"] == "from-the-agent"
    assert seen["fuse"]["toolbox"] is config.toolbox


def test_the_caller_scan_matches_the_orchestrator_by_its_receiver() -> None:
    """``agente.execute(path, tmp)``, without ``structured_output=``, is still seen."""
    import inspect

    signature = inspect.signature(_resolve(METHOD_CALLERS_CHECKED["execute"][0]))
    [call] = [
        node for node in ast.walk(ast.parse("agente.execute(path, tmp)"))
        if isinstance(node, ast.Call)
    ]

    assert _is_orchestrator(call.func.value)
    assert not _is_orchestrator(ast.parse("connection").body[0].value)
    with pytest.raises(TypeError, match="config"):
        signature.bind(call.func.value, *call.args)
