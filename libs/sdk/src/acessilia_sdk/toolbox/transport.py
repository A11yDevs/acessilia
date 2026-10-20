"""HTTP transport shared by every Toolbox client.

``execute_capability`` is the only way to reach
``POST /v1/capabilities/{id}:execute``: it checks the capability against the
registry, builds the form, maps transport and HTTP failures to
:mod:`acessilia_sdk.toolbox.errors` and validates the response envelope.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from acessilia_sdk.toolbox.capabilities import (
    TOOLBOX_CAPABILITIES,
    ToolboxCapability,
)
from acessilia_sdk.toolbox.errors import (
    ToolboxArtifactNotFound,
    ToolboxAuthenticationError,
    ToolboxCapabilityError,
    ToolboxContractViolation,
    ToolboxError,
    ToolboxInvalidInput,
    ToolboxProviderUnavailable,
    ToolboxTimeout,
    ToolboxUnsupportedMediaType,
)

_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".html": "text/html",
    ".txt": "text/plain",
}


def auth_headers(api_key: str | None) -> dict[str, str]:
    """Bearer header for the Toolbox, or nothing when no key is configured."""
    if api_key:
        return {"Authorization": f"Bearer {api_key}"}
    return {}


def media_type_for(path: Path) -> str:
    """Media type sent with an uploaded file, from its extension."""
    return _MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")


def raise_for_error(response: httpx.Response, context: str) -> None:
    """Converte códigos HTTP em exceções Toolbox específicas."""
    if response.is_success:
        return

    status = response.status_code
    code = ""
    try:
        body = response.json()
        detail = body.get("detail", body.get("message", ""))
        code = str(body.get("code", ""))
    except Exception:
        detail = response.text[:500]

    if status == 503:
        raise ToolboxProviderUnavailable(
            f"Provedor indisponível ({context}): {detail}"
        )
    if status == 504:
        raise ToolboxTimeout(f"Timeout do provedor ({context}): {detail}")
    if status == 415:
        raise ToolboxUnsupportedMediaType(
            f"Tipo de mídia não suportado ({context}): {detail}"
        )
    if status == 404:
        raise ToolboxArtifactNotFound(
            f"Artefato não encontrado ({context}): {detail}"
        )
    if status == 422:
        raise ToolboxContractViolation(
            f"Requisição inválida ({context}): {detail}"
        )
    if status == 400 and code == "invalid_input":
        raise ToolboxInvalidInput(f"Entrada inválida ({context}): {detail}")
    if status == 400:
        raise ToolboxCapabilityError(
            f"Capacidade inválida ({context}): {detail}"
        )
    if status == 401:
        raise ToolboxAuthenticationError(
            f"Autenticação falhou ({context}): {detail}"
        )

    raise ToolboxError(f"Erro HTTP {status} na Toolbox ({context}): {detail}")


def require_capability(capability_id: str) -> ToolboxCapability:
    """Return the registry entry for an executable capability.

    ``TOOLBOX_CAPABILITIES`` is the allowlist of contracts a client may call;
    anything else is refused before it reaches the wire.
    """
    spec = TOOLBOX_CAPABILITIES.get(capability_id)
    if spec is None:
        raise ToolboxCapabilityError(
            f"Capacidade não registrada no SDK: {capability_id}"
        )
    if spec.transport != "execute":
        raise ToolboxCapabilityError(
            f"Capacidade {capability_id} não é executada via :execute"
        )
    return spec


async def execute_capability(
    http: httpx.AsyncClient,
    capability_id: str,
    *,
    provider: str,
    file_path: Path | None = None,
    artifact_id: str | None = None,
    upload: tuple[str, bytes, str] | None = None,
    language: str | None = None,
    parameters: dict[str, Any] | None = None,
    no_cache: bool = False,
) -> dict[str, Any]:
    """POST /v1/capabilities/{capability_id}:execute and validate the envelope.

    The input is exactly one of ``artifact_id`` (already stored in the Toolbox),
    ``file_path`` or ``upload`` (``(filename, content, media_type)``); when an
    ``artifact_id`` is given it wins. ``http`` must carry the Toolbox base URL
    and auth headers. Returns the full response envelope.
    """
    spec = require_capability(capability_id)
    if file_path is None and artifact_id is None and upload is None:
        raise ValueError("Forneça file_path ou artifact_id")

    form: dict[str, Any] = {}
    if artifact_id:
        form["artifact_id"] = artifact_id
    if language is not None:
        form["language"] = language
    form["provider"] = provider
    # Ask for the exact contract this client was written against; a Toolbox
    # that publishes several versions would otherwise serve the latest.
    form["version"] = spec.contract_version
    if parameters is not None:
        form["parameters"] = json.dumps(parameters)
    if no_cache:
        form["no_cache"] = True

    path = f"/v1/capabilities/{capability_id}:execute"
    try:
        if artifact_id:
            response = await http.post(path, data=form)
        elif upload is not None:
            response = await http.post(path, files={"file": upload}, data=form)
        else:
            with open(file_path, "rb") as f:
                files = {"file": (file_path.name, f, media_type_for(file_path))}
                response = await http.post(path, files=files, data=form)
    except httpx.TimeoutException as e:
        raise ToolboxTimeout(
            f"Timeout ao executar {capability_id} via Toolbox: {e}"
        ) from e
    except httpx.RequestError as e:
        raise ToolboxProviderUnavailable(
            f"Toolbox indisponível em {http.base_url}: {e}"
        ) from e

    raise_for_error(response, capability_id)
    try:
        result = response.json()
    except ValueError as e:
        raise ToolboxContractViolation(
            f"Resposta de {capability_id} não contém JSON válido"
        ) from e
    if not isinstance(result, dict):
        raise ToolboxContractViolation(
            f"Resposta de {capability_id} deve ser um objeto JSON"
        )
    if result.get("status") != "succeeded":
        raise ToolboxContractViolation(
            f"{spec.label} falhou na Toolbox: status={result.get('status')}"
        )
    return result


__all__ = [
    "auth_headers",
    "execute_capability",
    "media_type_for",
    "raise_for_error",
    "require_capability",
]
