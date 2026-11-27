"""The configuration a run actually used, recorded with its job (Etapa 0, #380).

The record groups the configuration the way the Etapa 0 proposal asks:

- ``processing``: what changes the processed document. It starts from
  :func:`backend.services.cache.processing_cache_configuration`, the same
  configuration the processing cache keys on, so there is one definition of
  "changes the result" (and ``run_identity`` classifies every ``CoreConfig``
  field for it);
- ``operational``: how the run is carried out (timeouts, retries, caches,
  limits), never what it produces;
- ``environment``: where the run happened (paths, interfaces, build identity).

``settings.py`` remains the only reader of the environment: this module reads
the values of a ``Settings`` instance and an explicit ``CoreConfig``. It never
records a credential; the names it leaves out are listed in the record, so the
absence is deliberate and visible.

The record is written once per job start by ``backend/api/worker.py`` and kept
with the durable job record. It is not part of the processing cache key: the
key stays exactly what :func:`processing_cache_configuration` returns, so
adding the record does not change any cache hit.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from acessilia_core.config import CoreConfig
from acessilia_core.run_identity import NOT_PROCESSING_FIELDS, config_fields

if TYPE_CHECKING:
    from backend.config.settings import Settings

#: Version of the record's shape. Bumped when a group or a value changes
#: meaning, so a stored record can still be read for what it says.
SCHEMA = "acessilia/effective-configuration@1"

#: ``CoreConfig`` fields left out of the processing identity that describe
#: where the run happened, not how it ran. They come from
#: ``run_identity.NOT_PROCESSING_FIELDS``, which already states why each one
#: is outside the identity.
ENVIRONMENT_CORE_FIELDS: frozenset[str] = frozenset({"paths.data_dir"})

#: ``CoreConfig`` fields left out of the processing identity because they hold
#: a credential. Recorded by name only.
SECRET_CORE_FIELDS: frozenset[str] = frozenset({
    "models.ollama_api_key",
    "models.openrouter_api_key",
    "toolbox.api_key",
})

#: Service settings recorded as operational: what bounds or retries the run.
OPERATIONAL_SETTINGS: tuple[str, ...] = (
    "job_resume_on_restart",
    "model_call_max_pending",
    "model_call_workers",
    "pdf_ua_audit_max_rules",
    "queue_max_concurrent",
    "queue_multi_job_experimental",
    "request_timeout",
    "toolbox_cancel_timeout_seconds",
)

#: Service settings recorded as environment: where the run happened.
ENVIRONMENT_SETTINGS: tuple[str, ...] = (
    "api_base_url",
    "api_host",
    "api_port",
    "data_dir",
    "enabled_interfaces",
    "git_commit",
    "i18n_locales_active",
    "image_digest",
    "image_tag",
    "locale",
    "logs_dir",
    "temp_dir",
    "web_base_url",
    "web_port",
)

#: Service settings never recorded because they hold a credential or a
#: personal identifier. The record names them in ``secrets_omitted``.
SECRET_SETTINGS: frozenset[str] = frozenset({
    "bot_token",
    "observability_api_token",
    "ollama_api_key",
    "openrouter_api_key",
    "operations_api_token",
    "smtp_password",
    "smtp_user",
    "telegram_admin_ids",
    "toolbox_api_key",
})

#: Service settings outside a processing run, with the reason they are left
#: out. The completeness test keeps this map and the three groups covering
#: every ``Settings`` field.
NOT_RECORDED_SETTINGS: dict[str, str] = {
    "allowed_extensions": "input validation before the run",
    "log_level": "process setup",
    "max_file_size_mb": "input validation before the run",
    "smtp_from": "notification delivery, not the run",
    "smtp_name": "notification delivery, not the run",
    "smtp_port": "notification delivery, not the run",
    "smtp_server": "notification delivery, not the run",
}

#: Processing settings the cache key omits at their default value (#832) but
#: the record keeps, so the effective configuration is complete.
RECORDED_PROCESSING_DEFAULTS: tuple[str, ...] = ("pddl_max_discovery_replans",)


def effective_configuration(
    config: CoreConfig,
    *,
    run: Mapping[str, Any] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """The configuration a run with ``config`` used, grouped for the record.

    Args:
        config: The run's ``CoreConfig``, built once at the job's start.
        run: The job's own options outside ``CoreConfig`` (mode, custom prompt,
            thinking mode). They are part of the processing cache key and are
            recorded under ``processing.run``.
        settings: The service's ``Settings``; the global one by default. It is
            passed explicitly so a test can replace values without reading the
            environment.

    Returns:
        A JSON-ready mapping with the ``processing``, ``operational`` and
        ``environment`` groups, the omitted secrets by name and the settings
        outside a run with their reasons.
    """
    from backend.config.settings import settings as default_settings
    from backend.services.cache import processing_cache_configuration

    service_settings = default_settings if settings is None else settings
    values = config_fields(config)

    processing = processing_cache_configuration(config, settings=service_settings)
    for name in RECORDED_PROCESSING_DEFAULTS:
        processing.setdefault(name, getattr(service_settings, name))
    if run:
        processing["run"] = _json_value(dict(run))

    operational_core = {
        name: _json_value(values[name])
        for name in sorted(NOT_PROCESSING_FIELDS)
        if name not in ENVIRONMENT_CORE_FIELDS and name not in SECRET_CORE_FIELDS
    }
    environment_core = {
        name: _json_value(values[name]) for name in sorted(ENVIRONMENT_CORE_FIELDS)
    }

    return {
        "schema": SCHEMA,
        "processing": processing,
        "operational": {
            "core": operational_core,
            "service": {
                name: _json_value(getattr(service_settings, name))
                for name in OPERATIONAL_SETTINGS
            },
        },
        "environment": {
            "core": environment_core,
            "service": {
                name: _json_value(getattr(service_settings, name))
                for name in ENVIRONMENT_SETTINGS
            },
        },
        "secrets_omitted": sorted(SECRET_CORE_FIELDS | SECRET_SETTINGS),
        "not_recorded": dict(NOT_RECORDED_SETTINGS),
    }


def recorded_setting_names() -> set[str]:
    """Every ``Settings`` name the record classifies.

    The completeness test compares it with ``Settings``: a new setting must be
    put in a group (or in ``NOT_RECORDED_SETTINGS``/``SECRET_SETTINGS``) before
    the suite passes.
    """
    from backend.services.cache import SERVICE_PROCESSING_SETTINGS

    recorded = _recorded_core_fields()
    core_settings = {
        setting
        for path, setting in _core_field_settings().items()
        if path in recorded or path.split("[", 1)[0] in recorded
    }
    return (
        core_settings
        | set(SERVICE_PROCESSING_SETTINGS)
        | set(RECORDED_PROCESSING_DEFAULTS)
        | set(OPERATIONAL_SETTINGS)
        | set(ENVIRONMENT_SETTINGS)
        | set(SECRET_SETTINGS)
        | set(NOT_RECORDED_SETTINGS)
    )


def _recorded_core_fields() -> set[str]:
    """``CoreConfig`` fields the record holds under any group."""
    from acessilia_core.run_identity import PROCESSING_FIELDS

    return set(PROCESSING_FIELDS) | set(NOT_PROCESSING_FIELDS)


def _core_field_settings() -> dict[str, str]:
    """Which setting fills each ``CoreConfig`` field (``core_config.FIELD_SETTINGS``)."""
    from backend.config.core_config import FIELD_SETTINGS

    return FIELD_SETTINGS


def _json_value(value: Any) -> Any:
    """``value`` as JSON can carry it: paths as strings, sets as sorted lists."""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (set, frozenset)):
        return sorted((_json_value(item) for item in value), key=str)
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


__all__ = [
    "ENVIRONMENT_CORE_FIELDS",
    "ENVIRONMENT_SETTINGS",
    "NOT_RECORDED_SETTINGS",
    "OPERATIONAL_SETTINGS",
    "RECORDED_PROCESSING_DEFAULTS",
    "SCHEMA",
    "SECRET_CORE_FIELDS",
    "SECRET_SETTINGS",
    "effective_configuration",
    "recorded_setting_names",
]
