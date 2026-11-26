"""Offline tests for dual-provider structure extraction and fusion (acessilia_sdk.operations.fusion)."""

from __future__ import annotations

import pickle
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from acessilia_sdk.operations.formula import Step
from acessilia_sdk.operations.fusion import (
    DualFusionResult,
    DualFusionUnavailable,
    extract_dual_fused,
)
from acessilia_sdk.toolbox import (
    ToolboxArtifactNotFound,
    ToolboxContractViolation,
    ToolboxError,
    ToolboxProviderUnavailable,
)
from acessilia_sdk.toolbox.clients.structure import ToolboxStructureClient
from docstruct.policy import FusionPolicy

BASE = "http://toolbox.test"
SOURCE_ID = "sha256:" + "a" * 64


def _provider_of(request: httpx.Request) -> str:
    body = request.content
    if b"Content-Disposition" in body:
        part = body.split(b'name="provider"', 1)[1].split(b"\r\n\r\n", 1)[1]
        return part.split(b"\r\n", 1)[0].decode()
    return parse_qs(body.decode())["provider"][0]


def _has_artifact_id(request: httpx.Request) -> bool:
    body = request.content
    if b"Content-Disposition" in body:
        return b'name="artifact_id"' in body
    return "artifact_id" in parse_qs(body.decode())


def _no_cache(request: httpx.Request) -> bool:
    body = request.content
    if b"Content-Disposition" in body:
        return b'name="no_cache"' in body
    return "no_cache" in parse_qs(body.decode())


def _language(request: httpx.Request) -> str:
    body = request.content
    if b"Content-Disposition" in body:
        part = body.split(b'name="language"', 1)[1].split(b"\r\n\r\n", 1)[1]
        return part.split(b"\r\n", 1)[0].decode()
    return parse_qs(body.decode())["language"][0]


def _structure_response(provider: str, elements: list[dict]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "status": "succeeded",
            "capability": "document.structure.extract@1",
            "provider": provider,
            "document": {"elements": elements},
        },
    )


def _clients() -> tuple[ToolboxStructureClient, ToolboxStructureClient]:
    primary = ToolboxStructureClient(base_url=BASE, provider="docling", timeout_seconds=5)
    secondary = ToolboxStructureClient(base_url=BASE, provider="mineru", timeout_seconds=5)
    return primary, secondary


def _envelope(elements: list[dict]) -> dict:
    return {"status": "succeeded", "document": {"elements": elements}}


class _FakeStructureClient:
    """A structure client that answers with each of ``answers`` in turn (or raises it)."""

    def __init__(self, provider: str, *answers: Any) -> None:
        self.provider = provider
        self.calls: list[dict[str, Any]] = []
        self._answers = list(answers)

    async def extract_structure(self, file_path: object = None, **kwargs: Any) -> Any:
        self.calls.append({"file_path": file_path, **kwargs})
        answer = self._answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    async def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_fuses_both_providers_and_reports_steps(respx_mock, tmp_path) -> None:
    doc = tmp_path / "sample.pdf"
    doc.write_bytes(b"%PDF-1.4")

    def responder(request: httpx.Request) -> httpx.Response:
        provider = _provider_of(request)
        if provider == "docling":
            return _structure_response(
                "docling",
                [
                    {
                        "type": "paragraph",
                        "text": "Shared paragraph across both providers.",
                        "reading_order": 1,
                        "page_number": 1,
                        "bbox": [10, 10, 90, 30],
                        "page_size": [100, 100],
                    },
                    {
                        "type": "paragraph",
                        "text": "Docling only sentence preserved by fusion.",
                        "reading_order": 2,
                        "page_number": 1,
                        "bbox": [10, 60, 90, 80],
                        "page_size": [100, 100],
                    },
                ],
            )
        return _structure_response(
            "mineru",
            [
                {
                    "type": "paragraph",
                    "text": "Shared paragraph across both providers.",
                    "reading_order": 1,
                    "page_number": 1,
                    "bbox": [10, 10, 90, 30],
                    "page_size": [100, 100],
                }
            ],
        )

    route = respx_mock.post(f"{BASE}/v1/capabilities/document.structure.extract:execute").mock(
        side_effect=responder
    )

    primary, secondary = _clients()
    try:
        result = await extract_dual_fused(
            primary,
            secondary,
            doc,
            language="en-US",
            use_remote_cache=False,
            policy=FusionPolicy(),
        )
    finally:
        await primary.close()
        await secondary.close()

    assert isinstance(result, DualFusionResult)
    assert result.fused is True
    assert result.primary_provider == "docling"
    assert result.secondary_provider == "mineru"
    assert result.failures == {}
    assert result.artifact_fallbacks == ()
    assert result.payload["provider"] == "docling+mineru"
    texts = [el["text"] for el in result.payload["document"]["elements"]]
    assert "Shared paragraph across both providers." in texts
    assert "Docling only sentence preserved by fusion." in texts
    assert result.steps == (
        Step("document.structure.extract", "docling", {"language": "en-US", "source": "file"}),
        Step("document.structure.extract", "mineru", {"language": "en-US", "source": "file"}),
    )
    assert len(route.calls) == 2
    assert all(_no_cache(call.request) and _language(call.request) == "en-US" for call in route.calls)


@pytest.mark.asyncio
async def test_reuses_artifact_id_and_falls_back_to_upload_when_missing(respx_mock, tmp_path) -> None:
    doc = tmp_path / "sample.pdf"
    doc.write_bytes(b"%PDF-1.4")

    def responder(request: httpx.Request) -> httpx.Response:
        provider = _provider_of(request)
        if _has_artifact_id(request):
            if provider == "mineru":
                return httpx.Response(
                    404,
                    json={"status": "failed", "error": {"code": "artifact_not_found", "message": "gone"}},
                )
            return _structure_response(
                "docling",
                [{"type": "paragraph", "text": "From artifact", "page_number": 1, "reading_order": 1}],
            )
        return _structure_response(
            provider,
            [{"type": "paragraph", "text": "From upload", "page_number": 1, "reading_order": 1}],
        )

    respx_mock.post(f"{BASE}/v1/capabilities/document.structure.extract:execute").mock(
        side_effect=responder
    )

    primary, secondary = _clients()
    try:
        result = await extract_dual_fused(primary, secondary, doc, artifact_id=SOURCE_ID)
    finally:
        await primary.close()
        await secondary.close()

    assert result.fused is True
    assert result.artifact_fallbacks == ("mineru",)
    assert result.steps == (
        Step("document.structure.extract", "docling", {"language": "pt-BR", "source": "artifact"}),
        Step("document.structure.extract", "mineru", {"language": "pt-BR", "source": "file"}),
    )


@pytest.mark.asyncio
async def test_primary_failure_returns_secondary_payload_and_records_failure(respx_mock, tmp_path) -> None:
    doc = tmp_path / "sample.pdf"
    doc.write_bytes(b"%PDF-1.4")

    def responder(request: httpx.Request) -> httpx.Response:
        if _provider_of(request) == "docling":
            return httpx.Response(
                503,
                json={"status": "failed", "error": {"code": "provider_unavailable", "message": "busy"}},
            )
        return _structure_response(
            "mineru",
            [{"type": "paragraph", "text": "Secondary survives", "page_number": 1, "reading_order": 1}],
        )

    respx_mock.post(f"{BASE}/v1/capabilities/document.structure.extract:execute").mock(
        side_effect=responder
    )

    primary, secondary = _clients()
    try:
        result = await extract_dual_fused(primary, secondary, doc)
    finally:
        await primary.close()
        await secondary.close()

    assert result.fused is False
    assert result.payload["document"]["elements"][0]["text"] == "Secondary survives"
    assert set(result.failures) == {"docling"}
    assert isinstance(result.failures["docling"], ToolboxProviderUnavailable)
    assert result.steps == (
        Step("document.structure.extract", "mineru", {"language": "pt-BR", "source": "file"}),
    )


@pytest.mark.asyncio
async def test_secondary_failure_returns_primary_payload_and_records_failure(respx_mock, tmp_path) -> None:
    doc = tmp_path / "sample.pdf"
    doc.write_bytes(b"%PDF-1.4")

    def responder(request: httpx.Request) -> httpx.Response:
        if _provider_of(request) == "mineru":
            return httpx.Response(
                500,
                json={"status": "failed", "error": {"code": "provider_error", "message": "boom"}},
            )
        return _structure_response(
            "docling",
            [{"type": "paragraph", "text": "Primary survives", "page_number": 1, "reading_order": 1}],
        )

    respx_mock.post(f"{BASE}/v1/capabilities/document.structure.extract:execute").mock(
        side_effect=responder
    )

    primary, secondary = _clients()
    try:
        result = await extract_dual_fused(primary, secondary, doc)
    finally:
        await primary.close()
        await secondary.close()

    assert result.fused is False
    assert result.payload["document"]["elements"][0]["text"] == "Primary survives"
    assert set(result.failures) == {"mineru"}
    assert isinstance(result.failures["mineru"], ToolboxError)


@pytest.mark.asyncio
async def test_missing_artifact_without_file_path_records_failure_instead_of_uploading(
    respx_mock,
) -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        if _provider_of(request) == "mineru":
            return httpx.Response(
                404,
                json={"status": "failed", "error": {"code": "artifact_not_found", "message": "gone"}},
            )
        return _structure_response(
            "docling",
            [{"type": "paragraph", "text": "Primary ok", "page_number": 1, "reading_order": 1}],
        )

    respx_mock.post(f"{BASE}/v1/capabilities/document.structure.extract:execute").mock(
        side_effect=responder
    )

    primary, secondary = _clients()
    try:
        result = await extract_dual_fused(primary, secondary, artifact_id=SOURCE_ID)
    finally:
        await primary.close()
        await secondary.close()

    assert result.fused is False
    assert result.artifact_fallbacks == ()
    assert isinstance(result.failures["mineru"], ToolboxArtifactNotFound)


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        [],
        "envelope",
        7,
        {"status": "succeeded"},
        {"status": "succeeded", "document": None},
        {"status": "succeeded", "document": "nope"},
        {"status": "failed", "document": {"elements": []}},
        {"document": {"elements": []}},
    ],
)
@pytest.mark.asyncio
async def test_a_payload_outside_the_contract_is_a_recorded_contract_violation(
    invalid: Any,
) -> None:
    primary = _FakeStructureClient("docling", invalid)
    secondary = _FakeStructureClient(
        "mineru",
        _envelope([{"type": "paragraph", "text": "Secondary survives", "page_number": 1}]),
    )

    result = await extract_dual_fused(primary, secondary, "doc.pdf")

    assert result.fused is False
    assert isinstance(result.failures["docling"], ToolboxContractViolation)
    assert set(result.failures) == {"docling"}
    assert result.payload["document"]["elements"][0]["text"] == "Secondary survives"
    # No step for the provider whose answer violated the contract.
    assert result.steps == (
        Step("document.structure.extract", "mineru", {"language": "pt-BR", "source": "file"}),
    )


@pytest.mark.asyncio
async def test_an_invalid_artifact_payload_is_not_retried_as_an_upload() -> None:
    primary = _FakeStructureClient("docling", None)
    secondary = _FakeStructureClient("mineru", _envelope([]))

    result = await extract_dual_fused(primary, secondary, "doc.pdf", artifact_id=SOURCE_ID)

    assert isinstance(result.failures["docling"], ToolboxContractViolation)
    assert result.artifact_fallbacks == ()
    assert len(primary.calls) == 1
    assert "artifact_id" in primary.calls[0]


@pytest.mark.asyncio
async def test_an_invalid_upload_after_a_missing_artifact_keeps_both_diagnostics() -> None:
    primary = _FakeStructureClient("docling", ToolboxArtifactNotFound("gone"), None)
    secondary = _FakeStructureClient("mineru", _envelope([]))

    result = await extract_dual_fused(primary, secondary, "doc.pdf", artifact_id=SOURCE_ID)

    assert isinstance(result.failures["docling"], ToolboxContractViolation)
    assert result.artifact_fallbacks == ("docling",)
    assert ["artifact_id" in call for call in primary.calls] == [True, False]


@pytest.mark.asyncio
async def test_the_real_client_records_a_non_object_answer_without_reuploading(
    respx_mock, tmp_path
) -> None:
    doc = tmp_path / "sample.pdf"
    doc.write_bytes(b"%PDF-1.4")

    def responder(request: httpx.Request) -> httpx.Response:
        if _provider_of(request) == "docling":
            return httpx.Response(200, json=["not", "an", "object"])
        return _structure_response(
            "mineru",
            [{"type": "paragraph", "text": "Secondary survives", "page_number": 1}],
        )

    route = respx_mock.post(f"{BASE}/v1/capabilities/document.structure.extract:execute").mock(
        side_effect=responder
    )

    primary, secondary = _clients()
    try:
        result = await extract_dual_fused(primary, secondary, doc, artifact_id=SOURCE_ID)
    finally:
        await primary.close()
        await secondary.close()

    assert isinstance(result.failures["docling"], ToolboxContractViolation)
    assert result.artifact_fallbacks == ()
    assert result.steps == (
        Step(
            "document.structure.extract",
            "mineru",
            {"language": "pt-BR", "source": "artifact"},
        ),
    )
    docling_calls = [
        call for call in route.calls if _provider_of(call.request) == "docling"
    ]
    assert len(docling_calls) == 1
    assert _has_artifact_id(docling_calls[0].request)


@pytest.mark.asyncio
async def test_both_providers_answering_none_record_each_contract_violation() -> None:
    primary = _FakeStructureClient("docling", None)
    secondary = _FakeStructureClient("mineru", None)

    with pytest.raises(DualFusionUnavailable) as caught:
        await extract_dual_fused(primary, secondary, "doc.pdf")

    assert set(caught.value.failures) == {"docling", "mineru"}
    assert all(
        isinstance(exc, ToolboxContractViolation)
        for exc in caught.value.failures.values()
    )


@pytest.mark.asyncio
async def test_unavailable_message_names_each_provider_and_failure_type() -> None:
    primary = _FakeStructureClient("docling", ToolboxProviderUnavailable("down"))
    secondary = _FakeStructureClient("mineru", None)

    with pytest.raises(DualFusionUnavailable) as caught:
        await extract_dual_fused(primary, secondary, "doc.pdf")

    assert isinstance(caught.value.failures["docling"], ToolboxProviderUnavailable)
    assert isinstance(caught.value.failures["mineru"], ToolboxContractViolation)
    assert str(caught.value) == (
        "No provider available for extraction "
        "(docling: ToolboxProviderUnavailable; mineru: ToolboxContractViolation)"
    )


def test_unavailable_message_stays_overridable_and_pickles() -> None:
    failures = {
        "docling": ToolboxProviderUnavailable("down"),
        "mineru": ToolboxContractViolation("outside the envelope"),
    }

    err = DualFusionUnavailable(failures, ("docling",), message="custom message")

    assert str(err) == "custom message"
    restored = pickle.loads(pickle.dumps(err))
    assert isinstance(restored, DualFusionUnavailable)
    assert str(restored) == "custom message"
    assert restored.failures.keys() == failures.keys()
    assert {
        provider: type(exc) for provider, exc in restored.failures.items()
    } == {provider: type(exc) for provider, exc in failures.items()}
    assert restored.artifact_fallbacks == ("docling",)


@pytest.mark.asyncio
async def test_a_failed_status_secondary_keeps_the_primary_and_records_the_violation() -> None:
    primary = _FakeStructureClient(
        "docling",
        _envelope([{"type": "paragraph", "text": "Primary survives", "page_number": 1}]),
    )
    secondary = _FakeStructureClient(
        "mineru", {"status": "failed", "document": {"elements": []}}
    )

    result = await extract_dual_fused(primary, secondary, "doc.pdf")

    assert result.fused is False
    assert result.payload["document"]["elements"][0]["text"] == "Primary survives"
    assert set(result.failures) == {"mineru"}
    assert isinstance(result.failures["mineru"], ToolboxContractViolation)
    assert result.steps == (
        Step("document.structure.extract", "docling", {"language": "pt-BR", "source": "file"}),
    )


@pytest.mark.asyncio
async def test_both_providers_answering_a_failed_status_record_each_contract_violation() -> None:
    failed = {"status": "failed", "document": {"elements": []}}
    primary = _FakeStructureClient("docling", failed)
    secondary = _FakeStructureClient("mineru", failed)

    with pytest.raises(DualFusionUnavailable) as caught:
        await extract_dual_fused(primary, secondary, "doc.pdf")

    assert set(caught.value.failures) == {"docling", "mineru"}
    assert all(
        isinstance(exc, ToolboxContractViolation)
        for exc in caught.value.failures.values()
    )


@pytest.mark.asyncio
async def test_both_providers_failing_raises_provider_unavailable(respx_mock, tmp_path) -> None:
    doc = tmp_path / "sample.pdf"
    doc.write_bytes(b"%PDF-1.4")

    respx_mock.post(f"{BASE}/v1/capabilities/document.structure.extract:execute").mock(
        return_value=httpx.Response(
            503,
            json={"status": "failed", "error": {"code": "provider_unavailable", "message": "down"}},
        )
    )

    primary, secondary = _clients()
    try:
        with pytest.raises(ToolboxProviderUnavailable, match="No provider available") as caught:
            await extract_dual_fused(primary, secondary, doc)
    finally:
        await primary.close()
        await secondary.close()

    assert isinstance(caught.value, DualFusionUnavailable)
    assert set(caught.value.failures) == {"docling", "mineru"}
    assert all(isinstance(exc, ToolboxProviderUnavailable) for exc in caught.value.failures.values())
    assert caught.value.artifact_fallbacks == ()


@pytest.mark.asyncio
async def test_both_providers_failing_after_artifact_fallback_preserves_diagnostics_and_pickles(
    respx_mock, tmp_path
) -> None:
    doc = tmp_path / "sample.pdf"
    doc.write_bytes(b"%PDF-1.4")

    def responder(request: httpx.Request) -> httpx.Response:
        if _has_artifact_id(request):
            return httpx.Response(
                404,
                json={"status": "failed", "error": {"code": "artifact_not_found", "message": "gone"}},
            )
        status = 503 if _provider_of(request) == "docling" else 500
        code = "provider_unavailable" if status == 503 else "provider_error"
        return httpx.Response(
            status,
            json={"status": "failed", "error": {"code": code, "message": "failed"}},
        )

    respx_mock.post(f"{BASE}/v1/capabilities/document.structure.extract:execute").mock(
        side_effect=responder
    )

    primary, secondary = _clients()
    try:
        with pytest.raises(DualFusionUnavailable) as caught:
            await extract_dual_fused(primary, secondary, doc, artifact_id=SOURCE_ID)
    finally:
        await primary.close()
        await secondary.close()

    err = caught.value
    assert err.artifact_fallbacks == ("docling", "mineru")
    assert set(err.failures) == {"docling", "mineru"}
    assert isinstance(err.failures["docling"], ToolboxProviderUnavailable)
    assert isinstance(err.failures["mineru"], ToolboxError)

    restored = pickle.loads(pickle.dumps(err))
    assert isinstance(restored, DualFusionUnavailable)
    assert str(restored) == str(err)
    assert set(restored.failures) == {"docling", "mineru"}
    assert restored.artifact_fallbacks == ("docling", "mineru")


@pytest.mark.asyncio
async def test_unexpected_exception_propagates_unchanged(tmp_path) -> None:
    missing_file = tmp_path / "does-not-exist.pdf"
    primary, secondary = _clients()
    try:
        with pytest.raises(FileNotFoundError):
            await extract_dual_fused(primary, secondary, missing_file)
    finally:
        await primary.close()
        await secondary.close()


@pytest.mark.asyncio
async def test_requires_file_path_or_artifact_id() -> None:
    primary, secondary = _clients()
    try:
        with pytest.raises(ValueError, match="file_path or artifact_id"):
            await extract_dual_fused(primary, secondary)
    finally:
        await primary.close()
        await secondary.close()
