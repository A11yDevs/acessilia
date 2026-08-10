from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

API_VERSION_PREFIX = "/api/v1"


class ApiError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class ApiClient:
    """Cliente HTTP para a API Acessilia.

    Usado pelos frontends (web, telegram, cli) e pronto para novos clientes.
    """

    def __init__(
        self,
        base_url: str,
        timeout: float = 60.0,
        api_key: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._headers: dict[str, str] = {}
        if api_key:
            self._headers["X-API-Key"] = api_key

    def _url(self, path: str) -> str:
        return f"{self.base_url}{API_VERSION_PREFIX}{path}"

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise ApiError(response.status_code, str(detail))

    async def submit_job(
        self,
        file_path: Path,
        filename: str,
        mode: str = "normal",
        custom_prompt: str | None = None,
        thinking_mode: bool = False,
        email: str | None = None,
        source: str = "api",
    ) -> dict[str, Any]:
        data = {
            "mode": mode,
            "thinking_mode": str(thinking_mode).lower(),
            "source": source,
        }
        if custom_prompt:
            data["custom_prompt"] = custom_prompt
        if email:
            data["email"] = email
        files = {
            "document_file": (
                filename,
                file_path.open("rb"),
                "application/octet-stream",
            )
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            with file_path.open("rb") as file_handle:
                files["document_file"] = (filename, file_handle, "application/octet-stream")
                response = await client.post(
                    self._url("/jobs"),
                    files=files,
                    data=data,
                    headers=self._headers,
                )
        self._raise_for_status(response)
        return response.json()

    async def get_job_status(self, task_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                self._url(f"/jobs/{task_id}"), headers=self._headers
            )
        self._raise_for_status(response)
        return response.json()

    async def cancel_job(self, task_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                self._url(f"/jobs/{task_id}/cancel"), headers=self._headers
            )
        self._raise_for_status(response)
        return response.json()

    async def get_download_info(self, token: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                self._url(f"/download/{token}"), headers=self._headers
            )
        self._raise_for_status(response)
        return response.json()

    async def download_file(
        self, token: str, format: str, destination: Path
    ) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "GET",
                self._url(f"/download/{token}/{format}"),
                headers=self._headers,
            ) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    await response.aclose()
                    raise ApiError(response.status_code, body.decode(errors="replace"))
                with destination.open("wb") as buffer:
                    async for chunk in response.aiter_bytes():
                        buffer.write(chunk)
        return destination

    async def health(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                self._url("/health"), headers=self._headers
            )
        self._raise_for_status(response)
        return response.json()

    async def history(self, limit: int = 20) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                self._url(f"/history?limit={limit}"), headers=self._headers
            )
        self._raise_for_status(response)
        return response.json()

    async def stats(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(self._url("/stats"), headers=self._headers)
        self._raise_for_status(response)
        return response.json()


def get_default_client() -> ApiClient:
    from backend.config.settings import settings

    return ApiClient(base_url=settings.api_base_url)


default_client = get_default_client()
