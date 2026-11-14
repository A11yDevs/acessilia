"""Operation headers and the bounded cancel client (ADR-0019)."""

from __future__ import annotations

import httpx
import pytest
import respx
from acessilia_sdk.toolbox import (
    ToolboxCapabilityClient,
    ToolboxOperationClient,
    operation_context,
)
from acessilia_sdk.toolbox.clients import ToolboxArtifactClient
from acessilia_sdk.toolbox.operation import (
    ATTEMPT_ID_HEADER,
    OPERATION_ID_HEADER,
    TASK_ID_HEADER,
)

BASE_URL = "http://toolbox.test"
EXECUTE = f"{BASE_URL}/v1/capabilities/document.ocr:execute"
CANCEL = f"{BASE_URL}/v1/operations/op-1:cancel"
SUCCEEDED = {"status": "succeeded", "document": {}}


class _OcrClient(ToolboxCapabilityClient):
    provider_key = "toolbox_ocr_provider"


@pytest.mark.asyncio
async def test_execute_sends_the_operation_headers() -> None:
    with respx.mock() as router:
        route = router.post(EXECUTE).mock(
            return_value=httpx.Response(200, json=SUCCEEDED)
        )
        client = _OcrClient(base_url=BASE_URL)
        try:
            with operation_context("task-1", "op-1"):
                await client._execute(
                    "document.ocr", provider="docling-ocr", upload=("x.txt", b"x", "text/plain")
                )
        finally:
            await client.close()

    headers = route.calls.last.request.headers
    assert headers[TASK_ID_HEADER] == "task-1"
    assert headers[OPERATION_ID_HEADER] == "op-1"
    assert headers[ATTEMPT_ID_HEADER]


@pytest.mark.asyncio
async def test_artifact_upload_sends_the_operation_headers(tmp_path) -> None:
    source = tmp_path / "page.pdf"
    source.write_bytes(b"%PDF")
    with respx.mock() as router:
        route = router.post(f"{BASE_URL}/v1/artifacts").mock(
            return_value=httpx.Response(
                201,
                json={
                    "artifact_id": "sha256:abc",
                    "digest": "sha256:abc",
                    "size": 4,
                    "media_type": "application/pdf",
                },
            )
        )
        client = ToolboxArtifactClient(base_url=BASE_URL)
        try:
            with operation_context("task-1", "op-upload"):
                await client.upload(source)
        finally:
            await client.close()

    headers = route.calls.last.request.headers
    assert headers[TASK_ID_HEADER] == "task-1"
    assert headers[OPERATION_ID_HEADER] == "op-upload"
    assert headers[ATTEMPT_ID_HEADER]


@pytest.mark.asyncio
async def test_retry_keeps_the_operation_and_changes_the_attempt(monkeypatch) -> None:
    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr("acessilia_sdk.toolbox.client._sleep", no_sleep)
    attempts: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        attempts.append(request.headers[ATTEMPT_ID_HEADER])
        if len(attempts) == 1:
            raise httpx.ReadTimeout("first attempt timed out", request=request)
        return httpx.Response(200, json=SUCCEEDED)

    with respx.mock() as router:
        router.post(EXECUTE).mock(side_effect=answer)
        client = _OcrClient(base_url=BASE_URL, retries=1)
        try:
            with operation_context("task-1", "op-1"):
                await client._execute(
                    "document.ocr", provider="docling-ocr", upload=("x.txt", b"x", "text/plain")
                )
        finally:
            await client.close()

    assert len(attempts) == 2
    assert attempts[0] != attempts[1]


@pytest.mark.asyncio
async def test_cancel_reports_requested_and_keeps_the_task_scope() -> None:
    with respx.mock() as router:
        route = router.post(CANCEL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "operation_id": "op-1",
                    "state": "cancel_requested",
                    "cancel_requested": True,
                },
            )
        )
        client = ToolboxOperationClient(base_url=BASE_URL)
        try:
            result = await client.cancel("op-1", task_id="task-1")
        finally:
            await client.close()

    assert result.state == "cancel_requested"
    assert result.cancel_requested is True
    assert route.calls.last.request.headers[TASK_ID_HEADER] == "task-1"


@pytest.mark.asyncio
async def test_cancel_treats_404_as_not_found() -> None:
    with respx.mock() as router:
        router.post(CANCEL).mock(
            return_value=httpx.Response(404, json={"code": "operation_not_found"})
        )
        client = ToolboxOperationClient(base_url=BASE_URL)
        try:
            result = await client.cancel("op-1", task_id="task-1")
        finally:
            await client.close()
    assert result.state == "not_found"
    assert result.cancel_requested is False
    assert result.error is None


@pytest.mark.asyncio
async def test_cancel_returns_failures_instead_of_raising() -> None:
    with respx.mock() as router:
        router.post(CANCEL).mock(return_value=httpx.Response(500, json={"message": "boom"}))
        client = ToolboxOperationClient(base_url=BASE_URL)
        try:
            result = await client.cancel("op-1", task_id="task-1")
        finally:
            await client.close()
    assert result.state == "failed"
    assert result.error
