"""The processing cache key and the fusion reuse follow the run's CoreConfig (#544)."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from acessilia_core.run_identity import (
    FUSION_REUSE_VERSION,
    NOT_PROCESSING_FIELDS,
    NOT_PROCESSING_PROVIDERS,
    PROCESSING_FIELDS,
    PROCESSING_PROVIDERS,
    config_fields,
    fusion_reuse_identity,
    processing_identity,
)
from tests.core_config_support import core_config

ALL_FIELDS = sorted(config_fields(core_config()))


def _changed(value):
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if isinstance(value, float):
        return value + 0.125
    if isinstance(value, Path):
        return value / "elsewhere"
    if isinstance(value, Mapping):
        return {**value, "toolbox_provider": f"{value.get('toolbox_provider')}-changed"}
    return f"{value}-changed"


def _with(config, name: str):
    group, field = name.split(".")
    value = getattr(getattr(config, group), field)
    return replace(config, **{group: replace(getattr(config, group), **{field: _changed(value)})})


def test_every_config_field_is_classified_once() -> None:
    """A new CoreConfig field must say whether the processed document depends on it."""
    classified = set(PROCESSING_FIELDS) | set(NOT_PROCESSING_FIELDS)

    assert not set(PROCESSING_FIELDS) & set(NOT_PROCESSING_FIELDS)
    assert set(ALL_FIELDS) == classified, sorted(set(ALL_FIELDS) ^ classified)
    assert all(reason.strip() for reason in NOT_PROCESSING_FIELDS.values())


def test_every_provider_key_is_classified_once() -> None:
    """A new Toolbox provider must say whether the processed document depends on it."""
    from acessilia_sdk.toolbox import PROVIDER_DEFAULTS

    classified = set(PROCESSING_PROVIDERS) | set(NOT_PROCESSING_PROVIDERS)

    assert not set(PROCESSING_PROVIDERS) & set(NOT_PROCESSING_PROVIDERS)
    assert set(PROVIDER_DEFAULTS) == classified, sorted(set(PROVIDER_DEFAULTS) ^ classified)


def _with_provider(config, key: str):
    providers = {**config.toolbox.providers, key: f"{config.toolbox.providers[key]}-changed"}
    return replace(config, toolbox=replace(config.toolbox, providers=providers))


@pytest.mark.parametrize("key", sorted(PROCESSING_PROVIDERS))
def test_a_processing_provider_changes_the_identity(key) -> None:
    config = core_config()

    assert processing_identity(_with_provider(config, key)) != processing_identity(config)


@pytest.mark.parametrize("key", sorted(NOT_PROCESSING_PROVIDERS))
def test_an_export_or_unused_provider_changes_neither_identity(key) -> None:
    """Review of #561: a DOCX/PDF/UA/validation or table provider does not
    reprocess the document nor re-extract the fusion."""
    config = core_config()
    changed = _with_provider(config, key)

    assert processing_identity(changed) == processing_identity(config)
    assert fusion_reuse_identity(changed.fusion, changed.toolbox) == fusion_reuse_identity(
        config.fusion, config.toolbox
    )


@pytest.mark.parametrize("name", sorted(PROCESSING_FIELDS))
def test_a_processing_field_changes_the_identity(name) -> None:
    config = core_config()

    assert processing_identity(_with(config, name)) != processing_identity(config)


@pytest.mark.parametrize("name", sorted(NOT_PROCESSING_FIELDS))
def test_a_field_left_out_does_not_change_the_identity(name) -> None:
    config = core_config()

    assert processing_identity(_with(config, name)) == processing_identity(config)


def test_the_service_cache_key_is_built_from_the_job_config() -> None:
    from backend import service

    config = core_config()

    assert service._cache_version(_with(config, "fusion.secondary_provider")) != (
        service._cache_version(config)
    )
    assert service._cache_version(_with(config, "toolbox.api_key")) == (
        service._cache_version(config)
    )


@pytest.mark.parametrize(
    "name",
    ["fusion.mode", "fusion.secondary_provider", "fusion.apply_page_routes",
     "fusion.judge_max_pages", "toolbox.base_url", "toolbox.base_urls", "toolbox.providers"],
)
def test_the_fusion_reuse_identity_follows_each_option(name) -> None:
    config = core_config()
    changed = _with(config, name)

    assert fusion_reuse_identity(changed.fusion, changed.toolbox) != fusion_reuse_identity(
        config.fusion, config.toolbox
    )


def test_the_fusion_reuse_identity_leaves_out_what_does_not_change_the_payload() -> None:
    config = core_config()
    changed = _with(_with(_with(config, "toolbox.api_key"), "toolbox.retries"), "paths.data_dir")

    assert fusion_reuse_identity(changed.fusion, changed.toolbox) == fusion_reuse_identity(
        config.fusion, config.toolbox
    )


def _stored_fusion(tmp_path, config):
    from acessilia_core.manifest.toolbox_extractor import _persist_fusion_reuse
    from tests.test_dual_provider_fusion import _dual_payload, _make_manifest

    manifest = _make_manifest(tmp_path)
    source = Path(manifest.source.path)
    source.write_bytes(b"%PDF-run-identity")
    manifest.source.sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    payload = _dual_payload()
    manifest.extractor.configuration["fusion_reuse"] = _persist_fusion_reuse(
        source, payload, None, data_dir=tmp_path / "data",
        identity=fusion_reuse_identity(config.fusion, config.toolbox),
    )
    return manifest, payload


def test_the_reuse_record_keeps_its_provenance(tmp_path) -> None:
    import json

    config = core_config(fusion={"secondary_provider": "provenance-provider"})
    manifest, _ = _stored_fusion(tmp_path, config)

    record = json.loads(Path(manifest.extractor.configuration["fusion_reuse"]["path"]).read_bytes())

    assert record["identity"]["version"] == FUSION_REUSE_VERSION
    assert record["identity"]["fusion"]["secondary_provider"] == "provenance-provider"


def test_a_run_with_the_stored_options_reuses_the_fusion(tmp_path) -> None:
    from acessilia_core.pipeline.handlers import fusion as fusion_handlers

    config = core_config()
    manifest, payload = _stored_fusion(tmp_path, config)

    assert fusion_handlers._reusable_fusion_payload(manifest, core_config()) == payload


@pytest.mark.parametrize(
    "name",
    ["fusion.mode", "fusion.secondary_provider", "fusion.apply_page_routes",
     "fusion.judge_max_pages", "toolbox.providers"],
)
def test_a_run_with_other_options_does_not_reuse_the_fusion(tmp_path, name) -> None:
    from acessilia_core.pipeline.handlers import fusion as fusion_handlers

    config = core_config()
    manifest, _ = _stored_fusion(tmp_path, config)

    assert fusion_handlers._reusable_fusion_payload(manifest, _with(config, name)) is None


def test_a_record_of_another_strategy_version_is_not_reused(tmp_path, monkeypatch) -> None:
    from acessilia_core import run_identity
    from acessilia_core.pipeline.handlers import fusion as fusion_handlers

    config = core_config()
    manifest, _ = _stored_fusion(tmp_path, config)
    monkeypatch.setattr(run_identity, "FUSION_REUSE_VERSION", "a-later-strategy")

    assert fusion_handlers._reusable_fusion_payload(manifest, config) is None


def test_the_extractor_stores_the_run_fusion_identity(tmp_path, monkeypatch) -> None:
    """The structure step writes the run's identity, not the settings'."""
    import json
    from copy import deepcopy
    from unittest.mock import AsyncMock

    from acessilia_sdk.toolbox.clients import ToolboxStructureClient

    from acessilia_core.manifest.toolbox_extractor import ToolboxManifestExtractor
    from tests.core_config_support import fusion_config, paths_config, toolbox_config
    from tests.test_toolbox_manifest_extractor import FIXTURE_PDF, SAMPLE_TOOLBOX_RESPONSE

    primary = AsyncMock(spec=ToolboxStructureClient)
    primary.provider, primary.base_url = "docling", "http://toolbox.test"
    primary.extract_structure = AsyncMock(return_value=SAMPLE_TOOLBOX_RESPONSE)
    secondary = AsyncMock(spec=ToolboxStructureClient)
    secondary.provider = "run-secondary"
    secondary.extract_structure.return_value = deepcopy(SAMPLE_TOOLBOX_RESPONSE)
    monkeypatch.setattr(
        "acessilia_core.manifest.toolbox_extractor.make_toolbox_client",
        lambda *_a, **_k: secondary,
    )
    fusion = fusion_config(mode="dual", secondary_provider="run-secondary", judge_max_pages=4)
    toolbox = toolbox_config(use_artifact_store=False)

    result = ToolboxManifestExtractor(client=primary).extract(
        FIXTURE_PDF, fusion=fusion, toolbox=toolbox, paths=paths_config(data_dir=tmp_path), operations=None
    )

    record = json.loads(Path(result.document["fusion_reuse"]["path"]).read_bytes())
    assert record["identity"] == fusion_reuse_identity(fusion, toolbox)
