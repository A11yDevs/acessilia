from secrets import compare_digest

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.config.settings import settings
from backend.i18n import t
from backend.log_messages import (
    API_OBSERVABILITY_NOT_CONFIGURED,
    API_TOKEN_INVALID,
    API_TOKEN_READ_ONLY,
)


_bearer = HTTPBearer(auto_error=False, scheme_name="ObservabilityToken")


def require_observability_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    if not settings.observability_api_token:
        raise HTTPException(
            status_code=503,
            detail=t(API_OBSERVABILITY_NOT_CONFIGURED),
        )

    if credentials is None or not compare_digest(
        credentials.credentials, settings.observability_api_token
    ):
        raise HTTPException(
            status_code=401,
            detail=t(API_TOKEN_INVALID),
            headers={"WWW-Authenticate": "Bearer"},
        )

    if request.method not in {"GET", "HEAD"}:
        raise HTTPException(status_code=403, detail=t(API_TOKEN_READ_ONLY))
