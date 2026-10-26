"""Failover between Toolbox endpoints and verified artifact downloads."""

from __future__ import annotations

import hashlib
import pickle
from pathlib import Path

import httpx
import pytest
import respx

from acessilia_sdk.toolbox import (
    ArtifactRef,
    ToolboxArtifactNotFound,
    ToolboxCapabilityClient,
    ToolboxContractViolation,
    ToolboxEndpoint,
    ToolboxIncompatibleEndpoint,
    ToolboxProviderUnavailable,
    ToolboxTimeout,
    ToolboxUnavailable,
    download_artifact,
    parse_endpoints,
)

from acessilia_sdk.toolbox import client as client_module

PRIMARY = "http://toolbox-a.test"
SECONDARY = "http://toolbox-b.test"
EXECUTE = "/v1/capabilities/document.ocr:execute"
SUCCEEDED = {"status": "succeeded", "document": {}}


class _OcrClient(ToolboxCapabilityClient):
    provider_key = "toolbox_ocr_provider"


def _client(**kwargs) -> _OcrClient:
    return _OcrClient(endpoints=parse_endpoints(f"{PRIMARY}, {SECONDARY}"), **kwargs)


@pytest.fixture
def sleeps(monkeypatch) -> list[float]:
    """Record backoff delays instead of waiting."""
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(client_module, "_sleep", fake_sleep)
    return delays


def _publish_catalog(
    router: respx.MockRouter,
    base_url: str,
    *,
    version: int = 1,
    provider: str = "docling-ocr",
) -> None:
    """Make ``base_url`` publish ``document.ocr`` on ``provider``."""
    router.get(f"{base_url}/v1/capabilities").mock(
        return_value=httpx.Response(
            200, json=[{"id": "document.ocr", "version": version}]
        )
    )
    router.get(f"{base_url}/v1/providers").mock(
        return_value=httpx.Response(
            200, json=[{"id": provider, "capabilities": ["document.ocr"]}]
        )
    )


def test_parse_endpoints_skips_blanks_and_normalizes() -> None:
    endpoints = parse_endpoints(f" {PRIMARY}/ ,, {SECONDARY}", api_key="k")
    assert endpoints == (
        ToolboxEndpoint(PRIMARY, "k"),
        ToolboxEndpoint(SECONDARY, "k"),
    )


@pytest.mark.parametrize("value", ["", " , ", []])
def test_parse_endpoints_requires_one_url(value) -> None:
    with pytest.raises(ValueError):
        parse_endpoints(value)


def test_empty_base_url_fails_at_construction() -> None:
    with pytest.raises(ValueError, match="non-empty base_url"):
        _OcrClient(base_url="")


@pytest.mark.parametrize(
    "url", ["localhost:8002", "htp://toolbox.test", "toolbox.test", "http://"]
)
def test_malformed_base_url_fails_at_construction(url: str) -> None:
    """A typo must not look like an outage and consume the failover."""
    with pytest.raises(ValueError, match="absolute http"):
        _OcrClient(base_url=url)


def test_endpoints_accept_urls_and_a_comma_separated_string() -> None:
    from_list = _OcrClient(endpoints=[PRIMARY, ToolboxEndpoint(SECONDARY, "k")])
    from_string = _OcrClient(endpoints=f"{PRIMARY},{SECONDARY}")
    assert from_list.endpoints == (
        ToolboxEndpoint(PRIMARY),
        ToolboxEndpoint(SECONDARY, "k"),
    )
    assert [e.base_url for e in from_string.endpoints] == [PRIMARY, SECONDARY]


@pytest.mark.parametrize("value", [[], [42]])
def test_endpoints_reject_empty_or_unknown_items(value) -> None:
    with pytest.raises((ValueError, TypeError)):
        _OcrClient(endpoints=value)


def test_base_url_and_endpoints_are_exclusive() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        _OcrClient(base_url=PRIMARY, endpoints=parse_endpoints(SECONDARY))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        httpx.Response(503, json={"detail": "down"}),
        httpx.Response(504, json={"detail": "slow"}),
        httpx.ConnectError("refused"),
        httpx.ReadTimeout("slow"),
    ],
)
async def test_fails_over_when_an_instance_cannot_serve(failure) -> None:
    seen: list[tuple[str, type]] = []
    client = _client(on_failover=lambda ep, exc: seen.append((ep.base_url, type(exc))))
    try:
        with respx.mock() as router:
            mock = (
                {"side_effect": failure}
                if isinstance(failure, Exception)
                else {"return_value": failure}
            )
            router.post(PRIMARY + EXECUTE).mock(**mock)
            _publish_catalog(router, SECONDARY)
            secondary = router.post(SECONDARY + EXECUTE).mock(
                return_value=httpx.Response(200, json=SUCCEEDED)
            )
            http, result = await client._execute_on("document.ocr", artifact_id="a1")
        assert result == SUCCEEDED
        assert secondary.called
        assert str(http.base_url).rstrip("/") == SECONDARY
        assert len(seen) == 1 and seen[0][0] == PRIMARY
        assert issubclass(seen[0][1], (ToolboxProviderUnavailable, ToolboxTimeout))
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_reports_every_cause_when_all_instances_fail() -> None:
    client = _client()
    try:
        with respx.mock() as router:
            router.post(PRIMARY + EXECUTE).mock(side_effect=httpx.ConnectError("a"))
            _publish_catalog(router, SECONDARY)
            router.post(SECONDARY + EXECUTE).mock(
                return_value=httpx.Response(503, json={"detail": "b"})
            )
            with pytest.raises(ToolboxUnavailable) as info:
                await client._execute("document.ocr", artifact_id="a1")
        assert [url for url, _ in info.value.causes] == [PRIMARY, SECONDARY]
        assert PRIMARY in str(info.value) and SECONDARY in str(info.value)
        # Callers that already catch ProviderUnavailable keep working.
        assert isinstance(info.value, ToolboxProviderUnavailable)
    finally:
        await client.close()


def test_unavailable_error_survives_pickling() -> None:
    error = ToolboxUnavailable([(PRIMARY, ToolboxTimeout("slow"))])
    restored = pickle.loads(pickle.dumps(error))
    assert type(restored) is ToolboxUnavailable
    assert str(restored) == str(error)
    assert [url for url, _ in restored.causes] == [PRIMARY]


@pytest.mark.asyncio
async def test_single_endpoint_raises_its_own_error() -> None:
    client = _OcrClient(base_url=PRIMARY)
    try:
        with respx.mock() as router:
            router.post(PRIMARY + EXECUTE).mock(side_effect=httpx.ReadTimeout("slow"))
            with pytest.raises(ToolboxTimeout):
                await client._execute("document.ocr", artifact_id="a1")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_contract_errors_do_not_fail_over() -> None:
    client = _client()
    try:
        with respx.mock(assert_all_called=False) as router:
            router.post(PRIMARY + EXECUTE).mock(
                return_value=httpx.Response(422, json={"detail": "bad"})
            )
            secondary = router.post(SECONDARY + EXECUTE)
            with pytest.raises(ToolboxContractViolation):
                await client._execute("document.ocr", artifact_id="a1")
        assert not secondary.called
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_unknown_artifact_is_resent_as_file_when_enabled() -> None:
    client = _client(resend_file_on_missing_artifact=True)
    try:
        with respx.mock() as router:
            route = router.post(PRIMARY + EXECUTE).mock(
                side_effect=[
                    httpx.Response(404, json={"detail": "no such artifact"}),
                    httpx.Response(200, json=SUCCEEDED),
                ]
            )
            await client._execute(
                "document.ocr",
                artifact_id="a1",
                upload=("page.png", b"\x89PNG", "image/png"),
            )
        first, second = (call.request.content for call in route.calls)
        assert b"artifact_id=a1" in first
        assert b"artifact_id" not in second and b'filename="page.png"' in second
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_unknown_artifact_is_not_resent_by_default() -> None:
    client = _client()
    try:
        with respx.mock() as router:
            route = router.post(PRIMARY + EXECUTE).mock(
                return_value=httpx.Response(404, json={"detail": "x"})
            )
            with pytest.raises(ToolboxArtifactNotFound):
                await client._execute(
                    "document.ocr",
                    artifact_id="a1",
                    upload=("page.png", b"\x89PNG", "image/png"),
                )
        assert route.call_count == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_unknown_artifact_without_file_is_raised() -> None:
    client = _client(resend_file_on_missing_artifact=True)
    try:
        with respx.mock(assert_all_called=False) as router:
            router.post(PRIMARY + EXECUTE).mock(
                return_value=httpx.Response(404, json={"detail": "x"})
            )
            with pytest.raises(ToolboxArtifactNotFound):
                await client._execute("document.ocr", artifact_id="a1")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_endpoint_key_overrides_the_client_key() -> None:
    client = _OcrClient(
        endpoints=(ToolboxEndpoint(PRIMARY, "own"), ToolboxEndpoint(SECONDARY)),
        api_key="shared",
    )
    try:
        with respx.mock() as router:
            _publish_catalog(router, SECONDARY)
            primary = router.post(PRIMARY + EXECUTE).mock(
                return_value=httpx.Response(503, json={"detail": "x"})
            )
            secondary = router.post(SECONDARY + EXECUTE).mock(
                return_value=httpx.Response(200, json=SUCCEEDED)
            )
            await client._execute("document.ocr", artifact_id="a1")
        assert primary.calls.last.request.headers["Authorization"] == "Bearer own"
        assert secondary.calls.last.request.headers["Authorization"] == "Bearer shared"
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("catalog", "reason"),
    [
        ({"version": 2}, "cliente espera v1"),
        ({"provider": "mineru-ocr"}, "não registrado"),
        (None, "catálogo da Toolbox indisponível"),
    ],
)
async def test_incompatible_secondary_is_skipped(catalog, reason) -> None:
    client = _client()
    try:
        with respx.mock(assert_all_called=False) as router:
            router.post(PRIMARY + EXECUTE).mock(side_effect=httpx.ConnectError("a"))
            if catalog is None:
                router.get(f"{SECONDARY}/v1/capabilities").mock(
                    side_effect=httpx.ConnectError("b")
                )
            else:
                _publish_catalog(router, SECONDARY, **catalog)
            secondary = router.post(SECONDARY + EXECUTE)
            with pytest.raises(ToolboxUnavailable, match=reason) as info:
                await client._execute("document.ocr", artifact_id="a1")
        assert not secondary.called
        assert isinstance(info.value.causes[1][1], ToolboxIncompatibleEndpoint)
        assert "_Incompatible" not in str(info.value)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_primary_is_used_without_reading_any_catalogue() -> None:
    """Only the POST is mocked: a catalogue read would fail as unmocked."""
    client = _client()
    try:
        with respx.mock() as router:
            router.post(PRIMARY + EXECUTE).mock(
                return_value=httpx.Response(200, json=SUCCEEDED)
            )
            assert await client._execute("document.ocr", artifact_id="a1") == SUCCEEDED
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_retries_the_same_endpoint_a_bounded_number_of_times(sleeps) -> None:
    client = _OcrClient(base_url=PRIMARY, retries=2, retry_backoff_seconds=1.0)
    try:
        with respx.mock() as router:
            route = router.post(PRIMARY + EXECUTE).mock(
                side_effect=[
                    httpx.ConnectError("a"),
                    httpx.Response(503, json={"detail": "b"}),
                    httpx.Response(200, json=SUCCEEDED),
                ]
            )
            assert await client._execute("document.ocr", artifact_id="a1") == SUCCEEDED
        assert route.call_count == 3
        # Exponential with equal jitter: [0.5, 1.0] then [1.0, 2.0].
        assert len(sleeps) == 2
        assert 0.5 <= sleeps[0] <= 1.0 and 1.0 <= sleeps[1] <= 2.0
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_gives_up_after_the_last_retry(sleeps) -> None:
    client = _OcrClient(base_url=PRIMARY, retries=1)
    try:
        with respx.mock() as router:
            route = router.post(PRIMARY + EXECUTE).mock(
                side_effect=httpx.ReadTimeout("slow")
            )
            with pytest.raises(ToolboxTimeout):
                await client._execute("document.ocr", artifact_id="a1")
        assert route.call_count == 2
        assert len(sleeps) == 1  # no wait after the last attempt
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_contract_errors_are_not_retried(sleeps) -> None:
    client = _OcrClient(base_url=PRIMARY, retries=3)
    try:
        with respx.mock() as router:
            route = router.post(PRIMARY + EXECUTE).mock(
                return_value=httpx.Response(422, json={"detail": "bad"})
            )
            with pytest.raises(ToolboxContractViolation):
                await client._execute("document.ocr", artifact_id="a1")
        assert route.call_count == 1
    finally:
        await client.close()


def test_negative_retries_are_refused() -> None:
    with pytest.raises(ValueError, match="retries"):
        _OcrClient(base_url=PRIMARY, retries=-1)
    with pytest.raises(ValueError, match="retry_backoff_seconds"):
        _OcrClient(base_url=PRIMARY, retry_backoff_seconds=-1)


@pytest.mark.asyncio
async def test_on_failover_is_not_called_with_a_single_endpoint() -> None:
    seen: list = []
    client = _OcrClient(base_url=PRIMARY, on_failover=lambda ep, exc: seen.append(ep))
    try:
        with respx.mock() as router:
            router.post(PRIMARY + EXECUTE).mock(side_effect=httpx.ConnectError("a"))
            with pytest.raises(ToolboxProviderUnavailable):
                await client._execute("document.ocr", artifact_id="a1")
        assert seen == []
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_health_fails_over_and_reports_it() -> None:
    seen: list[str] = []
    client = _client(on_failover=lambda ep, exc: seen.append(ep.base_url))
    try:
        with respx.mock() as router:
            router.get(f"{PRIMARY}/v1/health").mock(side_effect=httpx.ConnectError("a"))
            router.get(f"{SECONDARY}/v1/health").mock(
                return_value=httpx.Response(200, json={"status": "ok"})
            )
            assert await client.health() == {"status": "ok"}
        assert seen == [PRIMARY]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_health_on_a_single_endpoint_raises_its_own_error() -> None:
    client = _OcrClient(base_url=PRIMARY, retries=3)
    try:
        with respx.mock() as router:
            route = router.get(f"{PRIMARY}/v1/health").mock(
                side_effect=httpx.ReadTimeout("slow")
            )
            with pytest.raises(ToolboxTimeout):
                await client.health()
        assert route.call_count == 1  # probes are never retried
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_health_reports_every_cause_when_all_fail() -> None:
    client = _client()
    try:
        with respx.mock() as router:
            router.get(f"{PRIMARY}/v1/health").mock(side_effect=httpx.ConnectError("a"))
            router.get(f"{SECONDARY}/v1/health").mock(
                return_value=httpx.Response(503, json={"detail": "b"})
            )
            with pytest.raises(ToolboxUnavailable) as info:
                await client.health()
        assert [url for url, _ in info.value.causes] == [PRIMARY, SECONDARY]
    finally:
        await client.close()


def test_auth_headers_follow_the_primary_endpoint_key() -> None:
    client = _OcrClient(
        endpoints=(ToolboxEndpoint(PRIMARY, "own"), ToolboxEndpoint(SECONDARY)),
        api_key="shared",
    )
    assert client._auth_headers == {"Authorization": "Bearer own"}


PDF = b"%PDF-1.7 test"
PDF_ID = "sha256:" + hashlib.sha256(PDF).hexdigest()


def test_artifact_ref_rejects_malformed_ids() -> None:
    assert ArtifactRef.parse(PDF_ID).digest == PDF_ID.removeprefix("sha256:")
    with pytest.raises(ToolboxContractViolation, match="Malformed"):
        ArtifactRef.parse("not-a-digest")


@pytest.mark.asyncio
async def test_download_verifies_and_writes_atomically(tmp_path: Path) -> None:
    destination = tmp_path / "out.pdf"
    with respx.mock() as router:
        router.get(f"{PRIMARY}/v1/artifacts/{PDF_ID}").mock(
            return_value=httpx.Response(200, content=PDF)
        )
        async with httpx.AsyncClient(base_url=PRIMARY) as http:
            await download_artifact(
                http, ArtifactRef.parse(PDF_ID), destination, magic=b"%PDF-"
            )
    assert destination.read_bytes() == PDF
    assert list(tmp_path.iterdir()) == [destination]


async def _download(tmp_path: Path, ref: ArtifactRef, content: bytes, magic):
    with respx.mock() as router:
        router.get(f"{PRIMARY}/v1/artifacts/{ref.artifact_id}").mock(
            return_value=httpx.Response(200, content=content)
        )
        async with httpx.AsyncClient(base_url=PRIMARY) as http:
            await download_artifact(http, ref, tmp_path / "out.pdf", magic=magic)


@pytest.mark.asyncio
async def test_download_rejects_content_that_does_not_hash_to_the_id(
    tmp_path: Path,
) -> None:
    with pytest.raises(ToolboxContractViolation, match="does not match"):
        await _download(tmp_path, ArtifactRef.parse(PDF_ID), b"%PDF-cut", None)
    assert not any(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_download_rejects_unexpected_magic(tmp_path: Path) -> None:
    with pytest.raises(ToolboxContractViolation, match="does not start"):
        await _download(tmp_path, ArtifactRef.parse(PDF_ID), PDF, b"\x89PNG")
    assert not any(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_artifact_is_downloaded_from_the_endpoint_that_served_the_call(
    tmp_path: Path,
) -> None:
    client = _client()
    destination = tmp_path / "out.pdf"
    try:
        with respx.mock() as router:
            _publish_catalog(router, SECONDARY)
            router.post(PRIMARY + EXECUTE).mock(side_effect=httpx.ConnectError("a"))
            router.post(SECONDARY + EXECUTE).mock(
                return_value=httpx.Response(
                    200,
                    json={"status": "succeeded", "document": {"artifact_id": PDF_ID}},
                )
            )
            secondary_get = router.get(f"{SECONDARY}/v1/artifacts/{PDF_ID}").mock(
                return_value=httpx.Response(200, content=PDF)
            )
            http, result = await client._execute_on("document.ocr", artifact_id="a1")
            ref = ArtifactRef.parse(result["document"]["artifact_id"])
            await download_artifact(http, ref, destination, magic=b"%PDF-")
        assert secondary_get.called
        assert destination.read_bytes() == PDF
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mock", "error"),
    [
        ({"side_effect": httpx.ReadTimeout("slow")}, ToolboxTimeout),
        ({"side_effect": httpx.ConnectError("refused")}, ToolboxProviderUnavailable),
        (
            {"return_value": httpx.Response(404, json={"detail": "gone"})},
            ToolboxArtifactNotFound,
        ),
    ],
)
async def test_download_maps_toolbox_failures(tmp_path: Path, mock, error) -> None:
    with respx.mock() as router:
        router.get(f"{PRIMARY}/v1/artifacts/{PDF_ID}").mock(**mock)
        async with httpx.AsyncClient(base_url=PRIMARY) as http:
            with pytest.raises(error):
                await download_artifact(
                    http, ArtifactRef.parse(PDF_ID), tmp_path / "out.pdf"
                )
    assert not any(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_download_reports_the_digest_before_the_magic(tmp_path: Path) -> None:
    with pytest.raises(ToolboxContractViolation, match="does not match"):
        await _download(tmp_path, ArtifactRef.parse(PDF_ID), b"not a pdf", b"%PDF-")
    assert not any(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_download_into_a_missing_directory_is_a_local_error(
    tmp_path: Path,
) -> None:
    with respx.mock() as router:
        router.get(f"{PRIMARY}/v1/artifacts/{PDF_ID}").mock(
            return_value=httpx.Response(200, content=PDF)
        )
        async with httpx.AsyncClient(base_url=PRIMARY) as http:
            with pytest.raises(FileNotFoundError):
                await download_artifact(
                    http, ArtifactRef.parse(PDF_ID), tmp_path / "missing" / "out.pdf"
                )


@pytest.mark.asyncio
@pytest.mark.parametrize("secondary_status", [200, 404, 503])
async def test_artifact_download_searches_another_endpoint_after_not_found(
    tmp_path, secondary_status
):
    from acessilia_sdk.toolbox.clients import ToolboxArtifactClient

    client = ToolboxArtifactClient(endpoints=[PRIMARY, SECONDARY], retries=0)
    destination = tmp_path / "result.pdf"
    destination.write_bytes(b"previous complete file")
    try:
        with respx.mock() as router:
            router.get(SECONDARY + "/v1/capabilities").respond(
                200,
                json=[{"id": "artifact.retrieve", "version": 1}],
            )
            router.get(SECONDARY + "/v1/providers").respond(200, json=[])
            first = router.get(f"{PRIMARY}/v1/artifacts/{PDF_ID}").respond(
                404, json={"code": "artifact_not_found"}
            )
            second = router.get(f"{SECONDARY}/v1/artifacts/{PDF_ID}")
            if secondary_status == 200:
                second.respond(200, content=PDF)
                await client.download(PDF_ID, destination, magic=b"%PDF-")
                assert destination.read_bytes() == PDF
            else:
                second.respond(secondary_status, json={"code": "artifact_not_found"})
                error = (
                    ToolboxArtifactNotFound
                    if secondary_status == 404
                    else ToolboxUnavailable
                )
                with pytest.raises(error):
                    await client.download(PDF_ID, destination, magic=b"%PDF-")
                assert destination.read_bytes() == b"previous complete file"
            assert first.call_count == second.call_count == 1
            assert list(tmp_path.iterdir()) == [destination]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_successful_but_corrupt_download_is_not_retried_on_another_endpoint(
    tmp_path,
):
    from acessilia_sdk.toolbox.clients import ToolboxArtifactClient

    client = ToolboxArtifactClient(endpoints=[PRIMARY, SECONDARY], retries=0)
    destination = tmp_path / "result.pdf"
    try:
        with respx.mock(assert_all_called=False) as router:
            router.get(f"{PRIMARY}/v1/artifacts/{PDF_ID}").respond(
                200, content=b"corrupt"
            )
            second = router.get(f"{SECONDARY}/v1/artifacts/{PDF_ID}").respond(
                200, content=PDF
            )
            with pytest.raises(ToolboxContractViolation):
                await client.download(PDF_ID, destination)
            assert not second.called
            assert not destination.exists()
    finally:
        await client.close()
