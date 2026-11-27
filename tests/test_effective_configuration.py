"""The effective configuration recorded with a job (#380, Etapa 0).

The record starts from the processing cache configuration, adds the
operational and environment groups, records the attempt identity and never
carries a credential or free text verbatim. A completeness test keeps every
``Settings`` field classified, and a value-level test checks that a declared
value actually appears in the record.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from dataclasses import fields
from pathlib import Path

import pytest

from acessilia_core.run_identity import (
    NOT_PROCESSING_FIELDS,
    NOT_PROCESSING_PROVIDERS,
    PROCESSING_FIELDS,
    config_fields,
)
from backend.config.core_config import core_config_from_settings
from backend.config.effective import (
    ENVIRONMENT_CORE_FIELDS,
    NOT_RECORDED_SETTINGS,
    PROVENANCE_NOTE,
    REDACTED_URL,
    SCHEMA,
    SECRET_CORE_FIELDS,
    SECRET_SETTINGS,
    effective_configuration,
    recorded_setting_names,
)
from backend.config.settings import Settings, settings
from backend.services.cache import processing_cache_configuration
from tests.core_config_support import core_config


def _service(**overrides):
    service = copy.copy(settings)
    for name, value in overrides.items():
        setattr(service, name, value)
    return service


def _record(config=None, *, run=None, attempt=None, service=None):
    return effective_configuration(
        config or core_config(),
        run=run,
        attempt=attempt,
        settings=service or settings,
    )


def test_every_core_field_is_classified_once() -> None:
    config = core_config()
    record = _record(config)

    processing = set(record["processing"]["core"])
    operational = set(record["operational"]["core"]) - {
        "toolbox.non_processing_providers"
    }
    environment = set(record["environment"]["core"])

    assert processing == set(PROCESSING_FIELDS)
    assert not processing & operational
    assert not processing & environment
    assert not operational & environment
    assert operational | environment == set(NOT_PROCESSING_FIELDS) - set(
        SECRET_CORE_FIELDS
    )
    assert environment == set(ENVIRONMENT_CORE_FIELDS)
    assert SECRET_CORE_FIELDS <= set(record["secrets_omitted"])

    classified = processing | operational | environment | set(record["secrets_omitted"])
    assert set(config_fields(config)) <= classified


def test_processing_group_is_the_cache_configuration() -> None:
    service = _service(
        toolbox_base_url="http://toolbox.test:8002",
        toolbox_base_urls="",
        ollama_base_url="http://ollama.test:11434/api/chat",
        openrouter_base_url="https://openrouter.test/api/v1/chat/completions",
    )
    config = core_config_from_settings(service)
    record = effective_configuration(config, settings=service)
    cache = processing_cache_configuration(config, settings=service)

    for key, value in cache.items():
        assert record["processing"][key] == value
    # The cache key omits this setting at its default (#832); the record keeps
    # it, so the effective configuration is complete.
    assert "pddl_max_discovery_replans" in record["processing"]


def test_the_record_carries_the_job_options_under_processing() -> None:
    prompt = "Describe charts"
    record = effective_configuration(
        core_config(),
        run={
            "mode": "detailed",
            "custom_prompt": prompt,
            "thinking_mode": True,
            "object_markers_requested": True,
        },
        settings=settings,
    )
    run = record["processing"]["run"]

    assert run["mode"] == "detailed"
    assert run["thinking_mode"] is True
    assert run["custom_prompt"] == {
        "sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "chars": len(prompt),
    }
    assert run["object_markers_requested"] is True
    assert run["object_markers_effective"] is True
    assert prompt not in json.dumps(record)


def test_empty_and_absent_prompts_are_both_none() -> None:
    """The cache normalizes both to "", so the record does too."""
    absent = _record(run={"custom_prompt": None})
    empty = _record(run={"custom_prompt": ""})

    assert absent["processing"]["run"]["custom_prompt"] is None
    assert empty["processing"]["run"]["custom_prompt"] is None


def test_object_markers_distinguishes_absent_override_from_false() -> None:
    default = core_config().export.object_markers_enabled

    absent = _record(run={"object_markers_requested": None})
    forced_off = _record(run={"object_markers_requested": False})
    forced_on = _record(run={"object_markers_requested": True})

    assert absent["processing"]["run"]["object_markers_effective"] is default
    assert forced_off["processing"]["run"]["object_markers_effective"] is False
    assert forced_on["processing"]["run"]["object_markers_effective"] is True


def test_non_processing_providers_are_recorded_by_value() -> None:
    record = _record()
    providers = record["operational"]["core"]["toolbox.non_processing_providers"]

    assert set(providers) == set(NOT_PROCESSING_PROVIDERS)
    for name in NOT_PROCESSING_PROVIDERS:
        assert providers[name] == getattr(settings, name)


def test_attempt_and_provenance_are_explicit() -> None:
    record = _record(
        attempt={"id": "attempt-1", "captured_at": "2026-11-27T00:00:00+00:00", "resumed": True},
        run={"mode": "normal"},
    )

    assert record["schema"] == SCHEMA
    assert record["attempt"] == {
        "id": "attempt-1",
        "captured_at": "2026-11-27T00:00:00+00:00",
        "resumed": True,
    }
    assert record["provenance"] == {
        "result_origin": "unknown",
        "note": PROVENANCE_NOTE,
    }


def test_the_record_never_carries_a_credential_or_a_verbatim_prompt() -> None:
    service = _service(
        bot_token="service-secret-bot",
        observability_api_token="service-secret-observability",
        operations_api_token="service-secret-operations",
        ollama_api_key="service-secret-ollama",
        openrouter_api_key="service-secret-openrouter",
        toolbox_api_key="service-secret-toolbox",
        smtp_user="service-secret-smtp-user",
        smtp_password="service-secret-smtp-password",
        toolbox_base_url="http://user:pass@toolbox.test:8002/path?token=secret-query#frag",
        toolbox_base_urls="http://u:p@a.test:8001, http://b.test:8002?token=x",
        ollama_base_url="http://user:pass@ollama.test:11434/api/chat?key=secret",
        openrouter_base_url="https://user:pass@openrouter.test/api?key=secret",
        openrouter_site_url="https://user:pass@site.test/?token=secret",
        api_base_url="http://user:pass@api.test:8000?token=secret",
        web_base_url="https://user:pass@web.test:8001?token=secret",
    )
    config = core_config_from_settings(service)
    prompt = "a prompt with personal data"
    record = effective_configuration(
        config, run={"custom_prompt": prompt}, settings=service
    )
    encoded = json.dumps(record)

    for secret in (
        "service-secret",
        "user:pass",
        "u:p@",
        "secret-query",
        "key=secret",
        "token=secret",
        prompt,
    ):
        assert secret not in encoded
    for host in ("toolbox.test", "a.test", "b.test", "ollama.test", "openrouter.test"):
        assert host in encoded


def test_url_sanitisation_keeps_scheme_host_port_and_path_only() -> None:
    service = _service(
        toolbox_base_url="http://user:pass@toolbox.test:8002/api?token=secret#frag",
        api_base_url="https://user:pass@api.test:8443/v1?token=secret",
        web_base_url="web.test:8001/path?token=secret",
    )
    record = effective_configuration(
        core_config_from_settings(service), settings=service
    )

    assert record["processing"]["core"]["toolbox.base_url"] == (
        "http://toolbox.test:8002/api"
    )
    assert record["environment"]["service"]["api_base_url"] == (
        "https://api.test:8443/v1"
    )
    assert record["environment"]["service"]["web_base_url"] == "web.test:8001/path"


def test_url_paths_are_kept_and_must_not_hold_credentials() -> None:
    """The documented limitation: the path is kept, so it must not be secret."""
    service = _service(toolbox_base_url="https://toolbox.test/token/SEGREDO")

    record = effective_configuration(core_config_from_settings(service), settings=service)

    assert record["processing"]["core"]["toolbox.base_url"] == (
        "https://toolbox.test/token/SEGREDO"
    )


def test_a_malformed_url_is_redacted_instead_of_copied() -> None:
    service = _service(toolbox_base_url="http://[::1")

    record = effective_configuration(core_config_from_settings(service), settings=service)

    assert record["processing"]["core"]["toolbox.base_url"] == REDACTED_URL


def test_every_settings_field_is_classified() -> None:
    known = {field.name for field in fields(Settings)}

    assert recorded_setting_names() <= known
    assert known - recorded_setting_names() == set()


def test_every_declared_value_appears_in_the_record() -> None:
    """A nominal classification is not enough: a recorded setting must appear.

    Strings, numbers and paths get unique sentinels. Booleans are covered by
    the targeted tests above and by ``test_boolean_settings_reach_a_group``.
    """
    omitted = SECRET_SETTINGS | set(NOT_RECORDED_SETTINGS)
    names = recorded_setting_names() - omitted
    checked = 0
    for index, name in enumerate(sorted(names)):
        original = getattr(settings, name)
        if isinstance(original, bool):
            continue
        sentinel = _sentinel(name, index, original)
        service = _service(**{name: sentinel})
        config = core_config_from_settings(service)
        record = effective_configuration(config, settings=service)
        encoded = json.dumps(record, ensure_ascii=False)
        if name.endswith(("_url", "_urls")):
            fragment = f"sentinel-{index}.test"
        elif isinstance(sentinel, Path):
            fragment = sentinel.name
        elif isinstance(sentinel, (set, frozenset, tuple)):
            fragment = f"sentinel-{index}"
        else:
            fragment = str(sentinel)
        assert fragment in encoded, name
        checked += 1
    assert checked > 80


#: Every boolean ``Settings`` field, the record path it reaches and the
#: ``CoreConfig`` field it fills (or ``None`` for a service-level setting).
BOOLEAN_CASES: dict[str, tuple[str, str, str | None, str]] = {
    "job_resume_on_restart": (
        "job_resume_on_restart", "operational", "service", "job_resume_on_restart",
    ),
    "queue_multi_job_experimental": (
        "queue_multi_job_experimental", "operational", "service",
        "queue_multi_job_experimental",
    ),
    "pddl_execute_dry_run": (
        "pddl_execute_dry_run", "processing", None, "pddl_execute_dry_run",
    ),
    "toolbox_use_remote_cache": (
        "toolbox.use_remote_cache", "operational", "core", "toolbox.use_remote_cache",
    ),
    "toolbox_use_artifact_store": (
        "toolbox.use_artifact_store", "operational", "core", "toolbox.use_artifact_store",
    ),
    "toolbox_media_inspect_enabled": (
        "toolbox.media_inspect_enabled", "processing", "core",
        "toolbox.media_inspect_enabled",
    ),
    "toolbox_pdf_validate_enabled": (
        "toolbox.pdf_validate_enabled", "operational", "core",
        "toolbox.pdf_validate_enabled",
    ),
    "vision_region_cache_enabled": (
        "vision.region_cache_enabled", "operational", "core", "vision.region_cache_enabled",
    ),
    "object_markers_enabled": (
        "export.object_markers_enabled", "operational", "core",
        "export.object_markers_enabled",
    ),
    "toolbox_docx_enabled": (
        "export.toolbox_docx_enabled", "operational", "core", "export.toolbox_docx_enabled",
    ),
    "toolbox_pdf_ua_enabled": (
        "export.toolbox_pdf_ua_enabled", "operational", "core", "export.toolbox_pdf_ua_enabled",
    ),
    "fusion_apply_page_routes": (
        "fusion.apply_page_routes", "processing", "core", "fusion.apply_page_routes",
    ),
    "slide_fold_figure_labels": (
        "document.slide_fold_figure_labels", "processing", "core",
        "document.slide_fold_figure_labels",
    ),
    "table_visual_review": (
        "vision.table_visual_review", "processing", "core", "vision.table_visual_review",
    ),
}


def test_every_boolean_setting_is_classified() -> None:
    booleans = {
        field.name for field in fields(Settings) if isinstance(getattr(settings, field.name), bool)
    }

    assert booleans == set(BOOLEAN_CASES)


def test_boolean_settings_reach_a_group() -> None:
    """Every boolean has a path in the record; flipping it is visible there."""
    base = core_config()
    for name, (case, section, kind, key) in BOOLEAN_CASES.items():
        if "." in case:
            group, field = case.split(".", 1)
            flipped = not getattr(getattr(base, group), field)
            record = effective_configuration(
                core_config(**{group: {field: flipped}}), settings=settings
            )
        else:
            flipped = not getattr(settings, name)
            service = _service(**{name: flipped})
            record = effective_configuration(
                core_config_from_settings(service), settings=service
            )
        value = record[section][key] if kind is None else record[section][kind][key]
        assert value is flipped, name


def _sentinel(name: str, index: int, original) -> object:
    if isinstance(original, bool):
        return not original
    if isinstance(original, int):
        return 900_000 + index
    if isinstance(original, float):
        return 0.100000 + index / 1_000_000
    if isinstance(original, Path):
        return Path(f"/tmp/sentinel-{name}-{index}")
    if isinstance(original, str):
        if name.endswith(("_url", "_urls")):
            return f"http://sentinel-{index}.test:9999/path"
        return f"sentinel-{name}-{index}"
    if isinstance(original, frozenset):
        return frozenset({f"sentinel-{index}"})
    if isinstance(original, set):
        return {f"sentinel-{index}"}
    if isinstance(original, tuple):
        return (f"sentinel-{index}",)
    return original


def test_record_is_json_ready() -> None:
    record = _record()

    assert record["schema"] == SCHEMA
    assert record["environment"]["service"]["data_dir"] == str(settings.data_dir)
    json.dumps(record)


@pytest.mark.asyncio
async def test_worker_persists_the_effective_configuration(tmp_path, monkeypatch) -> None:
    from backend.api.worker import ApiJob, JobExecutor
    from backend.services import job_store

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    job_store.save_request("task-int", "token", {"file": "a.pdf"}, {"status": "processing"})
    job = ApiJob(
        task_id="task-int",
        file_path=tmp_path / "a.pdf",
        filename="a.pdf",
        object_markers=True,
    )
    service = copy.copy(settings)
    config = core_config_from_settings(service)

    await JobExecutor()._record_effective_configuration(
        "task-int", job, config, service, resumed=False
    )

    record = job_store.load_record("task-int")
    assert record is not None
    configuration = record["configuration"]
    assert configuration["schema"] == SCHEMA
    assert configuration["attempt"]["resumed"] is False
    assert configuration["processing"]["run"]["object_markers_requested"] is True
    assert configuration["operational"]["core"]["toolbox.non_processing_providers"]


@pytest.mark.asyncio
async def test_worker_survives_a_record_that_cannot_be_built(
    tmp_path, monkeypatch
) -> None:
    from backend.api import worker
    from backend.api.worker import ApiJob, JobExecutor
    from backend.services import job_store

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    job_store.save_request("task-build", "token", {}, {"status": "processing"})

    def broken(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(worker, "effective_configuration", broken)
    job = ApiJob("task-build", tmp_path / "a.pdf", "a.pdf")
    service = copy.copy(settings)

    await JobExecutor()._record_effective_configuration(
        "task-build", job, core_config_from_settings(service), service, resumed=False
    )

    assert job_store.load_record("task-build")["configuration"] is None


@pytest.mark.asyncio
async def test_worker_survives_a_record_that_cannot_be_saved(
    tmp_path, monkeypatch
) -> None:
    from backend.api import worker
    from backend.api.worker import ApiJob, JobExecutor
    from backend.services import job_store

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    job_store.save_request("task-save", "token", {}, {"status": "processing"})

    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("disk is full")

    monkeypatch.setattr(worker, "save_configuration", broken)
    job = ApiJob("task-save", tmp_path / "a.pdf", "a.pdf")
    service = copy.copy(settings)

    await JobExecutor()._record_effective_configuration(
        "task-save", job, core_config_from_settings(service), service, resumed=False
    )

    assert job_store.load_record("task-save")["configuration"] is None


def test_saving_a_configuration_for_an_unknown_job_fails(tmp_path, monkeypatch) -> None:
    from backend.services import job_store

    monkeypatch.setattr(settings, "data_dir", tmp_path)

    with pytest.raises(LookupError):
        job_store.save_configuration("missing", {"schema": SCHEMA})


def test_a_new_attempt_replaces_the_previous_record(tmp_path, monkeypatch) -> None:
    from backend.services import job_store

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    job_store.save_request("task-attempts", "token", {}, {"status": "processing"})
    job_store.save_configuration(
        "task-attempts", {"schema": SCHEMA, "attempt": {"id": "attempt-a"}}
    )
    job_store.save_configuration(
        "task-attempts", {"schema": SCHEMA, "attempt": {"id": "attempt-b"}}
    )

    assert job_store.load_record("task-attempts")["configuration"]["attempt"] == {
        "id": "attempt-b"
    }


def test_job_store_round_trips_the_configuration(tmp_path, monkeypatch) -> None:
    from backend.services import job_store

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    configuration = {"schema": SCHEMA, "processing": {"run": {"mode": "normal"}}}

    job_store.save_request("task-1", "token", {"file": "a.pdf"}, {"status": "queued"})
    job_store.save_configuration("task-1", configuration)

    record = job_store.load_record("task-1")
    assert record is not None
    assert record["configuration"] == configuration

    job_store.save_status(
        "task-1",
        {"task_id": "task-1", "status": "processing", "configuracao_efetiva": configuration},
    )
    status = job_store.load_record("task-1")["status"]
    assert "configuracao_efetiva" not in status


def test_job_store_adds_the_configuration_column_to_an_old_database(
    tmp_path, monkeypatch
) -> None:
    from backend.services import job_store

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    database = tmp_path / "history.db"
    with sqlite3.connect(database) as conn:
        conn.execute(
            "CREATE TABLE api_jobs (task_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, "
            "request TEXT NOT NULL, status TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO api_jobs VALUES ('legacy', 'hash', '{}', '{\"status\": \"done\"}')"
        )

    job_store.save_request("task-2", "token", {}, {"status": "queued"})
    job_store.save_configuration("task-2", {"schema": SCHEMA})

    assert job_store.load_record("legacy")["status"] == {"status": "done"}
    assert job_store.load_record("legacy")["configuration"] is None
    assert job_store.load_record("task-2")["configuration"] == {"schema": SCHEMA}
    with sqlite3.connect(database) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(api_jobs)")}
    assert "configuration" in columns
