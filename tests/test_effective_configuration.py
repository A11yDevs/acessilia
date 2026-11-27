"""The effective configuration recorded with a job (#380, Etapa 0).

The record starts from the processing cache configuration, adds the
operational and environment groups, and never carries a credential. A
completeness test keeps every ``Settings`` field classified, so a new setting
cannot be left out by omission.
"""

from __future__ import annotations

import copy
import json
import sqlite3
from dataclasses import fields
from pathlib import Path

from acessilia_core.run_identity import (
    NOT_PROCESSING_FIELDS,
    PROCESSING_FIELDS,
    config_fields,
)
from backend.config.effective import (
    ENVIRONMENT_CORE_FIELDS,
    SCHEMA,
    SECRET_CORE_FIELDS,
    SECRET_SETTINGS,
    effective_configuration,
    recorded_setting_names,
)
from backend.config.settings import Settings, settings
from backend.services.cache import processing_cache_configuration
from tests.core_config_support import core_config


def _record(config=None):
    return effective_configuration(config or core_config(), settings=settings)


def test_every_core_field_is_classified_once() -> None:
    config = core_config()
    record = _record(config)

    processing = set(record["processing"]["core"])
    operational = set(record["operational"]["core"])
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
    config = core_config()
    record = _record(config)
    cache = processing_cache_configuration(config, settings=settings)

    for key, value in cache.items():
        assert record["processing"][key] == value
    # The cache key omits this setting at its default (#832); the record keeps
    # it, so the effective configuration is complete.
    assert "pddl_max_discovery_replans" in record["processing"]


def test_the_record_carries_the_job_options_under_processing() -> None:
    record = effective_configuration(
        core_config(),
        run={"mode": "detailed", "custom_prompt": "Describe charts", "thinking_mode": True},
        settings=settings,
    )

    assert record["processing"]["run"] == {
        "mode": "detailed",
        "custom_prompt": "Describe charts",
        "thinking_mode": True,
    }


def test_the_record_never_carries_a_credential() -> None:
    service = copy.copy(settings)
    for name in SECRET_SETTINGS:
        setattr(service, name, f"service-secret-{name}")
    config = core_config(
        models={"openrouter_api_key": "core-secret-openrouter"},
        toolbox={"api_key": "core-secret-toolbox"},
    )

    encoded = json.dumps(effective_configuration(config, settings=service))

    assert "core-secret" not in encoded
    assert "service-secret" not in encoded


def test_every_settings_field_is_classified() -> None:
    known = {field.name for field in fields(Settings)}

    assert recorded_setting_names() <= known
    assert known - recorded_setting_names() == set()


def test_record_is_json_ready() -> None:
    record = _record()

    assert record["schema"] == SCHEMA
    assert record["environment"]["service"]["data_dir"] == str(settings.data_dir)
    json.dumps(record)


def test_job_store_round_trips_the_configuration(tmp_path, monkeypatch) -> None:
    from backend.services import job_store

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    configuration = {"schema": SCHEMA, "processing": {"run": {"mode": "normal"}}}

    job_store.save_request("task-1", "token", {"file": "a.pdf"}, {"status": "queued"})
    job_store.save_configuration("task-1", configuration)

    record = job_store.load_record("task-1")
    assert record is not None
    assert record["configuration"] == configuration

    # The status column stays small: the configuration has its own column.
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

    job_store.save_request("task-2", "token", {}, {"status": "queued"})
    job_store.save_configuration("task-2", {"schema": SCHEMA})

    assert job_store.load_record("task-2")["configuration"] == {"schema": SCHEMA}
    with sqlite3.connect(database) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(api_jobs)")}
    assert "configuration" in columns


def test_a_resumed_status_keeps_the_recorded_configuration() -> None:
    """``restaurar`` re-applies what the durable record holds, config included."""
    from backend.agents.state_manager import StateManager

    manager = StateManager()
    manager.criar_tarefa(Path("a.pdf"), task_id="task-3")

    manager.restaurar("task-3", {"status": "processing", "configuracao_efetiva": _record()})

    assert manager.obter("task-3")["configuracao_efetiva"]["schema"] == SCHEMA

