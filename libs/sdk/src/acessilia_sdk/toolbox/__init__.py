"""Access to the Acessilia Toolbox through its published HTTP contract."""

from acessilia_sdk.toolbox.capabilities import (
    PROVIDER_DEFAULTS,
    TOOLBOX_CAPABILITIES,
    ToolboxCapability,
    provider_default,
)
from acessilia_sdk.toolbox.client import ToolboxCapabilityClient
from acessilia_sdk.toolbox.errors import (
    ToolboxArtifactNotFound,
    ToolboxAuthenticationError,
    ToolboxCapabilityError,
    ToolboxContractViolation,
    ToolboxError,
    ToolboxProviderUnavailable,
    ToolboxTimeout,
    ToolboxUnsupportedMediaType,
)
from acessilia_sdk.toolbox.transport import (
    auth_headers,
    execute_capability,
    media_type_for,
    raise_for_error,
    require_capability,
)

__all__ = [
    "PROVIDER_DEFAULTS",
    "TOOLBOX_CAPABILITIES",
    "ToolboxArtifactNotFound",
    "ToolboxAuthenticationError",
    "ToolboxCapability",
    "ToolboxCapabilityClient",
    "ToolboxCapabilityError",
    "ToolboxContractViolation",
    "ToolboxError",
    "ToolboxProviderUnavailable",
    "ToolboxTimeout",
    "ToolboxUnsupportedMediaType",
    "auth_headers",
    "execute_capability",
    "media_type_for",
    "provider_default",
    "raise_for_error",
    "require_capability",
]
