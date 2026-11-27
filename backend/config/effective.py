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

The record describes **the configuration resolved for one attempt**, not the
provenance of every delivered result. A canonical document may come from the
processing cache or from a checkpoint written under another configuration;
``provenance.result_origin`` therefore stays ``unknown`` until a caller records
the origin explicitly. :func:`backend.api.worker.JobExecutor._record_effective_configuration`
keeps only the latest attempt, so the durable record is not a history: an
attempt whose write fails leaves the previous record in place, and the
operations route serves that record with its own ``attempt`` identity.

``settings.py`` remains the only reader of the environment: this module reads
the values of a ``Settings`` instance and an explicit ``CoreConfig``. It never
records a credential, and it minimises free text and URLs: userinfo, query
strings and fragments are removed from URLs, and a custom prompt is stored as a
fingerprint (its SHA-256 and character count), not verbatim. Names left out are
listed in ``secrets_omitted`` and ``not_recorded``, so the absence is deliberate
and visible.

The record is written once per job start by ``backend/api/worker.py`` and kept
with the durable job record. It is not part of the processing cache key: the
key stays exactly what :func:`processing_cache_configuration` returns, so
adding the record does not change any cache hit.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

from acessilia_core.config import CoreConfig
from acessilia_core.export.markers import object_markers_enabled
from acessilia_core.run_identity import (
    NOT_PROCESSING_FIELDS,
    NOT_PROCESSING_PROVIDERS,
    config_fields,
)

if TYPE_CHECKING:
    from backend.config.settings import Settings

#: Version of the record's shape. Bumped when a group or a value changes
#: meaning, so a stored record can still be read for what it says.
SCHEMA = "acessilia/effective-configuration@2"

#: Why a record is not the provenance of a cached or resumed result.
PROVENANCE_NOTE: str = (
    "The record describes the configuration resolved for this attempt. It is "
    "not the provenance of a result reused from the processing cache or a "
    "checkpoint written under another configuration."
)

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

#: The suffix of a mapping key whose value is one URL or a comma-separated URL
#: list. The audit representation sanitises both.
_URL_KEY_SUFFIXES: tuple[str, ...] = ("_url", "_urls")

#: Returned instead of a URL the sanitizer cannot parse, so a malformed value
#: never leaks verbatim.
REDACTED_URL: str = "<redacted-url>"


def effective_configuration(
    config: CoreConfig,
    *,
    run: Mapping[str, Any] | None = None,
    attempt: Mapping[str, Any] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """The configuration a run with ``config`` used, grouped for the record.

    Args:
        config: The run's ``CoreConfig``, built once at the job's start.
        run: The job's own options outside ``CoreConfig`` (mode, custom prompt,
            thinking mode, ``object_markers``). The custom prompt is stored as
            a fingerprint; ``object_markers`` keeps the requested override and
            the effective value the delivery uses.
        attempt: The attempt identity (``id``, ``captured_at``, ``resumed``).
            The record is the latest attempt only, not a history.
        settings: The service's ``Settings``; the global one by default. It is
            passed explicitly so a test can replace values without reading the
            environment.

    Returns:
        A JSON-ready mapping with the ``processing``, ``operational`` and
        ``environment`` groups, the attempt identity, the provenance caveat,
        the omitted secrets by name and the settings outside a run with their
        reasons.
    """
    from backend.config.settings import settings as default_settings
    from backend.services.cache import processing_cache_configuration

    service_settings = default_settings if settings is None else settings
    values = config_fields(config)

    processing = processing_cache_configuration(config, settings=service_settings)
    for name in RECORDED_PROCESSING_DEFAULTS:
        processing.setdefault(name, getattr(service_settings, name))
    if run:
        processing["run"] = _run_options(run, config)

    operational_core = {
        name: _json_value(values[name])
        for name in sorted(NOT_PROCESSING_FIELDS)
        if name not in ENVIRONMENT_CORE_FIELDS and name not in SECRET_CORE_FIELDS
    }
    providers = values["toolbox.providers"]
    operational_core["toolbox.non_processing_providers"] = {
        name: _json_value(providers[name])
        for name in sorted(NOT_PROCESSING_PROVIDERS)
        if name in providers
    }
    environment_core = {
        name: _json_value(values[name]) for name in sorted(ENVIRONMENT_CORE_FIELDS)
    }

    record: dict[str, Any] = {
        "schema": SCHEMA,
        "attempt": _json_value(dict(attempt)) if attempt else None,
        "provenance": {
            "result_origin": "unknown",
            "note": PROVENANCE_NOTE,
        },
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
    return _sanitise_urls(record)


def recorded_setting_names() -> set[str]:
    """Every ``Settings`` name the record classifies.

    The completeness test compares it with ``Settings``: a new setting must be
    put in a group (or in ``NOT_RECORDED_SETTINGS``/``SECRET_SETTINGS``) before
    the suite passes. This is the nominal classification; a second test checks
    that every recorded value actually appears in the representation.
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


def _run_options(run: Mapping[str, Any], config: CoreConfig) -> dict[str, Any]:
    """The job's own options, with the prompt minimised and markers resolved."""
    options = {
        name: _json_value(value)
        for name, value in run.items()
        if name not in {"custom_prompt", "object_markers_requested"}
    }
    options["custom_prompt"] = _prompt_fingerprint(run.get("custom_prompt"))
    requested = run.get("object_markers_requested")
    options["object_markers_requested"] = requested
    options["object_markers_effective"] = object_markers_enabled(
        requested, config.export
    )
    return options


def _prompt_fingerprint(prompt: Any) -> dict[str, Any] | None:
    """A custom prompt's fingerprint, never the prompt itself.

    The SHA-256 lets an operator confirm a suspected prompt without storing the
    user's text; the length distinguishes an empty prompt from an absent one.
    A fingerprint is not anonymisation: a known prompt can be confirmed.
    """
    if not isinstance(prompt, str) or not prompt:
        return None
    return {
        "sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "chars": len(prompt),
    }


def _sanitise_urls(value: Any) -> Any:
    """``value`` with every URL-like field stripped of userinfo, query and fragment."""
    if isinstance(value, Mapping):
        return {
            str(key): _sanitise_url_field(str(key), item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitise_urls(item) for item in value]
    return value


def _sanitise_url_field(key: str, value: Any) -> Any:
    if isinstance(value, str) and key.endswith(_URL_KEY_SUFFIXES):
        if key.endswith("_urls"):
            return ",".join(_sanitise_url(part.strip()) for part in value.split(","))
        return _sanitise_url(value)
    return _sanitise_urls(value)


def _sanitise_url(value: str) -> str:
    """A URL without credentials, query or fragment, or ``REDACTED_URL``.

    The record keeps the scheme, host, port and path so an operator can tell
    deployments apart; the userinfo (which may hold a credential), the query
    (which may hold a token) and the fragment are dropped. A value without a
    scheme is treated as ``//value`` so ``host:port/path`` is parsed correctly.
    """
    if not value:
        return value
    has_scheme = "://" in value
    try:
        parsed = urlsplit(value if has_scheme else f"//{value}")
    except ValueError:
        return REDACTED_URL
    netloc = parsed.netloc.rsplit("@", 1)[-1]
    if has_scheme:
        return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
    return urlunsplit(("", netloc, parsed.path, "", "")).removeprefix("//")


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
    "PROVENANCE_NOTE",
    "RECORDED_PROCESSING_DEFAULTS",
    "REDACTED_URL",
    "SCHEMA",
    "SECRET_CORE_FIELDS",
    "SECRET_SETTINGS",
    "effective_configuration",
    "recorded_setting_names",
]
