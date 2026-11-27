"""The Backend's processing identity, shared by the cache and the audit (#945).

``acessilia_core.run_identity`` defines what a processed document depends on
inside the Core. The service adds its own options, the manifest rules and the
identity of the PDDL domain. That complete identity is used in two places:

- the processing cache key (``backend/services/cache.py``);
- the effective-configuration record (``backend/config/effective.py``).

Both consume this module, so there is one definition and the configuration
module no longer imports the cache service. ``settings.py`` remains the only
reader of the environment: the functions here receive a ``Settings`` instance
(or fall back to the global one).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from acessilia_core.config import CoreConfig
from acessilia_core.run_identity import processing_identity

if TYPE_CHECKING:
    from backend.config.settings import Settings

#: Bump when ``document_invariant_findings`` starts rejecting manifests that
#: were accepted and cached under the previous rules. It is part of the
#: processing-cache identity, so old entries are not reopened and rejected.
MANIFEST_INVARIANT_REVISION = "2026-11-14"

#: Service options a processed document depends on, outside the core's
#: ``CoreConfig``: the engine, the planner and the model revision.
SERVICE_PROCESSING_SETTINGS = (
    "pipeline_engine", "fusion_hybrid_provider", "processing_model_revision",
    "pddl_execute_dry_run", "pddl_max_replans", "pddl_planner_backend",
    "pddl_preferred_plan", "pddl_fast_downward", "pddl_fast_downward_alias",
    "pddl_fast_downward_search",
)


def processing_cache_configuration(
    config: CoreConfig, *, settings: Settings | None = None
) -> dict[str, Any]:
    """What a processed document depends on: the run's ``config`` (#544) and
    the service's own options, with the manifest rules and the PDDL domain.

    ``settings`` is the service's ``Settings``; the global one by default. It
    is explicit so the effective-configuration record (#380) can read the same
    values a test replaces.
    """
    from acessilia_core.pipeline.orchestrator import DEFAULT_MAX_DISCOVERY_REPLANS
    from acessilia_core.planning.domain_bundle import DomainBundle
    from backend.config.settings import settings as default_settings

    service_settings = default_settings if settings is None else settings
    configuration: dict[str, Any] = {"core": processing_identity(config)}
    configuration.update({
        name: getattr(service_settings, name) for name in SERVICE_PROCESSING_SETTINGS
    })
    # Only a bound other than the default enters the key, so the documents
    # cached before the setting existed keep theirs (#832).
    if service_settings.pddl_max_discovery_replans != DEFAULT_MAX_DISCOVERY_REPLANS:
        configuration["pddl_max_discovery_replans"] = (
            service_settings.pddl_max_discovery_replans
        )
    configuration["manifest_invariant_revision"] = MANIFEST_INVARIANT_REVISION
    domain = DomainBundle.load()
    configuration["pddl_domain"] = (domain.domain_sha256, domain.description_sha256)
    return configuration


__all__ = [
    "MANIFEST_INVARIANT_REVISION",
    "SERVICE_PROCESSING_SETTINGS",
    "processing_cache_configuration",
]
