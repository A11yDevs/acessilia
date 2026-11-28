"""Bearer authentication for privileged operations on the API."""

from acessilia_core.i18n.log_messages import API_OPERATIONS_NOT_CONFIGURED
from backend.api.bearer_auth import bearer_token_dependency
from backend.config.settings import settings

require_operations_token = bearer_token_dependency(
    scheme_name="OperationsToken",
    token=lambda: settings.operations_api_token,
    not_configured_message=API_OPERATIONS_NOT_CONFIGURED,
)

__all__ = ["require_operations_token"]
