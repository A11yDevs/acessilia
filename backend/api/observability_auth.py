from secrets import compare_digest

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.config.settings import settings


_bearer = HTTPBearer(auto_error=False, scheme_name="ObservabilityToken")


def require_observability_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    if not settings.observability_api_token:
        raise HTTPException(status_code=503, detail="Acesso de observabilidade não configurado")

    if credentials is None or not compare_digest(
        credentials.credentials, settings.observability_api_token
    ):
        raise HTTPException(
            status_code=401,
            detail="Token inválido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if request.method not in {"GET", "HEAD"}:
        raise HTTPException(status_code=403, detail="Token permite somente leitura")
