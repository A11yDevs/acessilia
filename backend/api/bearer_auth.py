"""Shared bearer-token dependency for the privileged API routes.

Operations and audit use different tokens and different OpenAPI schemes, but
the checks are the same: an unset token disables the route (503), and a
missing or wrong credential returns 401 without disclosing whether the token
exists. The factory keeps one implementation and lets each route name its own
scheme and token (#946).
"""

from __future__ import annotations

from collections.abc import Callable
from secrets import compare_digest
from typing import Any

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from acessilia_core.i18n import t
from acessilia_core.i18n.log_messages import API_TOKEN_INVALID


def bearer_token_dependency(
    *,
    scheme_name: str,
    token: Callable[[], str],
    not_configured_message: str,
) -> Any:
    """A FastAPI dependency that requires ``token()`` as a bearer credential.

    ``token`` is read per request, so a test can replace the setting without
    rebuilding the dependency. ``not_configured_message`` is the i18n id used
    when the token is empty.
    """
    bearer = HTTPBearer(auto_error=False, scheme_name=scheme_name)

    def require(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> None:
        configured = token()
        if not configured:
            raise HTTPException(
                status_code=503,
                detail=t(not_configured_message),
            )
        if credentials is None or not compare_digest(
            credentials.credentials.encode("utf-8"),
            configured.encode("utf-8"),
        ):
            raise HTTPException(
                status_code=401,
                detail=t(API_TOKEN_INVALID),
                headers={"WWW-Authenticate": "Bearer"},
            )

    return require


__all__ = ["bearer_token_dependency"]
