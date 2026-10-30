"""Access to the Acessilia Toolbox through its published HTTP contract."""

from acessilia_sdk.toolbox.artifacts import ArtifactRef, download_artifact, read_artifact
from acessilia_sdk.toolbox.capabilities import (
    PROVIDER_DEFAULTS,
    ROUTE_PROVIDER_DEFAULTS,
    TOOLBOX_CAPABILITIES,
    ToolboxCapability,
    provider_default,
)
from acessilia_sdk.toolbox.catalog import (
    CatalogCache,
    CatalogSnapshot,
    Requirement,
    fetch_catalog,
    missing_requirements,
    snapshot_from_payloads,
)
from acessilia_sdk.toolbox.client import FailoverHook, ToolboxCapabilityClient
from acessilia_sdk.toolbox.endpoints import (
    FAILOVER_ERRORS,
    ToolboxEndpoint,
    parse_endpoints,
)
from acessilia_sdk.toolbox.errors import (
    ToolboxArtifactNotFound,
    ToolboxAuthenticationError,
    ToolboxCapabilityError,
    ToolboxContractViolation,
    ToolboxError,
    ToolboxIncompatibleEndpoint,
    ToolboxInvalidInput,
    ToolboxProviderUnavailable,
    ToolboxTimeout,
    ToolboxUnavailable,
    ToolboxUnsupportedMediaType,
)
from acessilia_sdk.toolbox.transport import (
    auth_headers,
    execute_capability,
    media_type_for,
    raise_for_error,
    require_capability,
)
from acessilia_sdk.toolbox.vlm import (
    VLM_GATEWAY_PATH,
    vlm_gateway_base_url,
    vlm_provider_healthy,
)

__all__ = [
    "ArtifactRef",
    "CatalogCache",
    "CatalogSnapshot",
    "FAILOVER_ERRORS",
    "FailoverHook",
    "PROVIDER_DEFAULTS",
    "ROUTE_PROVIDER_DEFAULTS",
    "Requirement",
    "TOOLBOX_CAPABILITIES",
    "ToolboxArtifactNotFound",
    "ToolboxAuthenticationError",
    "ToolboxCapability",
    "ToolboxCapabilityClient",
    "ToolboxCapabilityError",
    "ToolboxContractViolation",
    "ToolboxEndpoint",
    "ToolboxError",
    "ToolboxIncompatibleEndpoint",
    "ToolboxInvalidInput",
    "ToolboxProviderUnavailable",
    "ToolboxTimeout",
    "ToolboxUnavailable",
    "ToolboxUnsupportedMediaType",
    "VLM_GATEWAY_PATH",
    "auth_headers",
    "download_artifact",
    "execute_capability",
    "fetch_catalog",
    "missing_requirements",
    "media_type_for",
    "parse_endpoints",
    "provider_default",
    "raise_for_error",
    "read_artifact",
    "require_capability",
    "snapshot_from_payloads",
    "vlm_gateway_base_url",
    "vlm_provider_healthy",
]
