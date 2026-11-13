"""Bearer authentication for privileged operations on the API."""

from secrets import compare_digest

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.config.settings import settings
from backend.i18n import t
from backend.log_messages import API_OPERATIONS_NOT_CONFIGURED, API_TOKEN_INVALID


_bearer = HTTPBearer(auto_error=False, scheme_name="OperationsToken")


def require_operations_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Require the operations token configured in ``OPERATIONS_API_TOKEN``.

    An unset token disables the privileged routes (503), like the observability
    ones. Missing or invalid credentials return 401 without disclosing whether
    the token exists.
    """
    if not settings.operations_api_token:
        raise HTTPException(
            status_code=503,
            detail=t(API_OPERATIONS_NOT_CONFIGURED),
        )

    if credentials is None or not compare_digest(
        credentials.credentials.encode("utf-8"),
        settings.operations_api_token.encode("utf-8"),
    ):
        raise HTTPException(
            status_code=401,
            detail=t(API_TOKEN_INVALID),
            headers={"WWW-Authenticate": "Bearer"},
        )


__all__ = ["require_operations_token"]
