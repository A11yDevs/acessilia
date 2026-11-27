"""Bearer authentication for the read-only audit API (#946)."""

from acessilia_core.i18n.log_messages import API_AUDIT_NOT_CONFIGURED
from backend.api.bearer_auth import bearer_token_dependency
from backend.config.settings import settings

require_audit_token = bearer_token_dependency(
    scheme_name="AuditToken",
    token=lambda: settings.audit_api_token,
    not_configured_message=API_AUDIT_NOT_CONFIGURED,
)

__all__ = ["require_audit_token"]
