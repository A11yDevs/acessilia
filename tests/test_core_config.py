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


def _settings_reads(path: Path, name: str) -> set[str]:
    """The attributes of ``name`` that ``path`` reads, imports inside functions included."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == name
    }


def _core_reads() -> set[str]:
    keys: set[str] = set()
    for path in CORE.rglob("*.py"):
        keys |= _settings_reads(path, "settings")
        if "getattr(settings, key)" in path.read_text(encoding="utf-8"):
            keys |= DYNAMIC_KEYS
    return keys


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
    built = _settings_reads(BUILDER, "s") | DYNAMIC_KEYS
    missing = sorted(_core_reads() - built - PROCESS_SETUP_KEYS)

    assert not missing, f"settings read by backend/core with no CoreConfig field: {missing}"


def test_each_field_takes_its_own_setting() -> None:
    """Every field holds the value of a distinct setting, none left behind."""
    keys = sorted(_settings_reads(BUILDER, "s") | DYNAMIC_KEYS)
    distinct = copy.copy(settings_module.settings)
    for index, key in enumerate(keys):
        object.__setattr__(distinct, key, f"value-{index}")

    leaves = _leaves(core_config_from_settings(distinct))

    assert sorted(leaves.values()) == sorted(f"value-{index}" for index in range(len(keys)))


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

    assert imported <= {"__future__", "collections", "dataclasses", "pathlib"}


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
