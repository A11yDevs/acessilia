"""Bearer authentication for the read-only audit API (#946)."""

from secrets import compare_digest

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from acessilia_core.i18n import t
from acessilia_core.i18n.log_messages import API_AUDIT_NOT_CONFIGURED, API_TOKEN_INVALID
from backend.config.settings import settings

_bearer = HTTPBearer(auto_error=False, scheme_name="AuditToken")


def require_audit_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Require the read-only audit token configured in ``AUDIT_API_TOKEN``.

    An unset token disables the audit routes (503). Missing or invalid
    credentials return 401 without disclosing whether the token exists. The
    operations token is deliberately not accepted: it can clear the cache,
    which an auditor must not be able to do.
    """
    if not settings.audit_api_token:
        raise HTTPException(
            status_code=503,
            detail=t(API_AUDIT_NOT_CONFIGURED),
        )

    if credentials is None or not compare_digest(
        credentials.credentials.encode("utf-8"),
        settings.audit_api_token.encode("utf-8"),
    ):
        raise HTTPException(
            status_code=401,
            detail=t(API_TOKEN_INVALID),
            headers={"WWW-Authenticate": "Bearer"},
        )


__all__ = ["require_audit_token"]
