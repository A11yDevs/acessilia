"""Catalogue snapshots, requirement checks and the last-good cache."""

from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

from acessilia_sdk.toolbox import (
    CatalogCache,
    Requirement,
    ToolboxContractViolation,
    ToolboxProviderUnavailable,
    fetch_catalog,
    ToolboxEndpoint,
    ToolboxTimeout,
    missing_requirements,
    read_catalog,
    snapshot_from_payloads,
)

BASE_URL = "http://toolbox.test"
CAPABILITIES = [
    {"id": "document.structure.extract", "version": 1, "providers": ["docling", "teleocr"]},
    {"id": "document.ocr", "version": 2, "providers": ["docling-ocr"]},
]
PROVIDERS = [
    {"id": "docling", "capabilities": ["document.structure.extract"], "endpoint": "http://a"},
    {"id": "mineru", "capabilities": ["document.structure.extract"], "endpoint": "http://b"},
    {"id": "docling-ocr", "capabilities": ["document.ocr"]},
]
EXTRACT = "document.structure.extract"


def _snapshot(capabilities=CAPABILITIES, providers=PROVIDERS, at=0.0):
    return snapshot_from_payloads(capabilities, providers, fetched_at=at)


def test_revision_ignores_order_and_endpoints() -> None:
    reordered = list(reversed(PROVIDERS))
    moved = [{**PROVIDERS[0], "endpoint": "http://elsewhere"}, *PROVIDERS[1:]]
    assert _snapshot().revision == _snapshot(providers=reordered).revision
    assert _snapshot().revision == _snapshot(providers=moved).revision


def test_revision_changes_with_bindings() -> None:
    fewer = [entry for entry in PROVIDERS if entry["id"] != "mineru"]
    assert _snapshot().revision != _snapshot(providers=fewer).revision


def test_bindings_come_from_registered_providers() -> None:
    """``teleocr`` is declared by the manifest but not registered."""
    snapshot = _snapshot()
    assert "teleocr" not in snapshot.bindings
    assert missing_requirements(snapshot, [Requirement(EXTRACT, "teleocr")]) == [
        f"{EXTRACT}: provider teleocr não registrado"
    ]


def test_satisfied_requirements_report_nothing() -> None:
    requirements = [Requirement(EXTRACT, "docling"), Requirement(EXTRACT, "mineru")]
    assert missing_requirements(_snapshot(), requirements) == []


@pytest.mark.parametrize(
    ("requirement", "reason"),
    [
        (Requirement("music.omr", "audiveris"), "fora da allowlist"),
        (Requirement("document.ocr.page", "qwen3-vl-page"), "não publicada"),
        (Requirement("document.ocr", "docling-ocr"), "publica v2, cliente espera v1"),
        (Requirement(EXTRACT, "nougat"), "provider nougat não registrado"),
        (Requirement(EXTRACT, "docling-ocr"), "não implementa a capacidade"),
    ],
)
def test_each_missing_requirement_names_its_reason(requirement, reason) -> None:
    [message] = missing_requirements(_snapshot(), [requirement])
    assert reason in message


def test_without_a_snapshot_every_requirement_fails_closed() -> None:
    requirements = [Requirement(EXTRACT, "docling")]
    assert missing_requirements(None, requirements) == [
        f"{EXTRACT}: catálogo da Toolbox indisponível"
    ]


def test_allowlist_is_checked_even_without_a_snapshot() -> None:
    [message] = missing_requirements(None, [Requirement("music.omr", "audiveris")])
    assert "fora da allowlist" in message


def test_absent_version_means_v1() -> None:
    unversioned = [{"id": EXTRACT}]
    assert _snapshot(capabilities=unversioned).capabilities == {EXTRACT: 1}


@pytest.mark.parametrize("version", ["abc", "2", 0, -1, True, 1.5])
def test_invalid_version_is_a_contract_violation(version) -> None:
    """Not a ``ValueError``: the cache only absorbs ``ToolboxError``."""
    with pytest.raises(ToolboxContractViolation, match="Versão inválida"):
        _snapshot(capabilities=[{"id": EXTRACT, "version": version}])


@pytest.mark.asyncio
async def test_fetch_returns_a_consistent_snapshot() -> None:
    with respx.mock() as router:
        router.get(f"{BASE_URL}/v1/capabilities").mock(
            return_value=httpx.Response(200, json=CAPABILITIES)
        )
        router.get(f"{BASE_URL}/v1/providers").mock(
            return_value=httpx.Response(200, json=PROVIDERS)
        )
        async with httpx.AsyncClient(base_url=BASE_URL) as http:
            snapshot = await fetch_catalog(http, clock=lambda: 5.0)
    assert snapshot.revision == _snapshot().revision
    assert snapshot.fetched_at == 5.0


@pytest.mark.asyncio
async def test_fetch_rereads_when_the_catalogue_changes_mid_read() -> None:
    fewer = [entry for entry in PROVIDERS if entry["id"] != "mineru"]
    with respx.mock() as router:
        capabilities = router.get(f"{BASE_URL}/v1/capabilities").mock(
            return_value=httpx.Response(200, json=CAPABILITIES)
        )
        router.get(f"{BASE_URL}/v1/providers").mock(
            side_effect=[
                httpx.Response(200, json=PROVIDERS),
                httpx.Response(200, json=fewer),
                httpx.Response(200, json=fewer),
            ]
        )
        async with httpx.AsyncClient(base_url=BASE_URL) as http:
            snapshot = await fetch_catalog(http)
    assert "mineru" not in snapshot.bindings
    assert capabilities.call_count == 1  # only providers are re-read


@pytest.mark.asyncio
async def test_fetch_gives_up_when_the_catalogue_keeps_changing() -> None:
    a = PROVIDERS
    b = [entry for entry in PROVIDERS if entry["id"] != "mineru"]
    with respx.mock() as router:
        router.get(f"{BASE_URL}/v1/capabilities").mock(
            return_value=httpx.Response(200, json=CAPABILITIES)
        )
        router.get(f"{BASE_URL}/v1/providers").mock(
            side_effect=[httpx.Response(200, json=p) for p in (a, b, a)]
        )
        async with httpx.AsyncClient(base_url=BASE_URL) as http:
            with pytest.raises(ToolboxContractViolation, match="mudou"):
                await fetch_catalog(http)


@pytest.mark.asyncio
async def test_fetch_rejects_a_malformed_catalogue() -> None:
    with respx.mock() as router:
        router.get(f"{BASE_URL}/v1/capabilities").mock(
            return_value=httpx.Response(200, json={"capabilities": []})
        )
        router.get(f"{BASE_URL}/v1/providers").mock(
            return_value=httpx.Response(200, json=PROVIDERS)
        )
        async with httpx.AsyncClient(base_url=BASE_URL) as http:
            with pytest.raises(ToolboxContractViolation):
                await fetch_catalog(http)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.asyncio
async def test_cache_reuses_a_fresh_snapshot_and_serves_it_while_stale() -> None:
    clock = _Clock()
    calls = {"n": 0}

    async def fetch():
        calls["n"] += 1
        if calls["n"] > 1:
            raise ToolboxProviderUnavailable("down")
        return _snapshot(at=clock.now)

    cache = CatalogCache(fetch, refresh_seconds=60, stale_seconds=300, clock=clock)
    first = await cache.get()
    clock.now = 30
    assert await cache.get() is first and calls["n"] == 1  # still fresh

    clock.now = 120  # refresh fails, last good is within the stale limit
    assert await cache.get() is first
    assert "down" in cache.last_error

    clock.now = 400  # past the stale limit: fail closed
    assert await cache.get() is None


@pytest.mark.asyncio
async def test_cache_without_any_snapshot_returns_none() -> None:
    async def fetch():
        raise ToolboxProviderUnavailable("down")

    assert await CatalogCache(fetch).get() is None


@pytest.mark.asyncio
async def test_concurrent_refreshes_share_one_fetch() -> None:
    calls = {"n": 0}
    release = asyncio.Event()

    async def fetch():
        calls["n"] += 1
        await release.wait()
        return _snapshot()

    cache = CatalogCache(fetch, clock=lambda: 0.0)
    pending = [asyncio.create_task(cache.get()) for _ in range(5)]
    await asyncio.sleep(0)
    release.set()
    results = await asyncio.gather(*pending)

    assert calls["n"] == 1
    assert all(result is results[0] is not None for result in results)


@pytest.mark.asyncio
async def test_concurrent_callers_share_a_failed_refresh() -> None:
    calls = {"n": 0}
    release = asyncio.Event()

    async def fetch():
        calls["n"] += 1
        await release.wait()
        raise ToolboxProviderUnavailable("down")

    cache = CatalogCache(fetch)
    pending = [asyncio.create_task(cache.get()) for _ in range(5)]
    await asyncio.sleep(0)
    release.set()

    assert await asyncio.gather(*pending) == [None] * 5
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_read_catalog_uses_the_endpoint_key_and_its_own_timeout() -> None:
    seen: list[httpx.Request] = []

    def serve(payload):
        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=payload)

        return handler

    with respx.mock() as router:
        router.get(f"{BASE_URL}/v1/capabilities").mock(side_effect=serve(CAPABILITIES))
        router.get(f"{BASE_URL}/v1/providers").mock(side_effect=serve(PROVIDERS))
        snapshot = await read_catalog(
            ToolboxEndpoint(f"{BASE_URL}/", "key"), timeout_seconds=7.0, clock=lambda: 3.0
        )

    assert snapshot.revision == _snapshot().revision
    assert snapshot.fetched_at == 3.0
    assert all(r.headers["Authorization"] == "Bearer key" for r in seen)
    assert {v for r in seen for v in r.extensions["timeout"].values()} == {7.0}


@pytest.mark.asyncio
async def test_read_catalog_without_a_key_sends_no_authorization() -> None:
    with respx.mock() as router:
        route = router.get(f"{BASE_URL}/v1/capabilities").mock(
            return_value=httpx.Response(200, json=CAPABILITIES)
        )
        router.get(f"{BASE_URL}/v1/providers").mock(
            return_value=httpx.Response(200, json=PROVIDERS)
        )
        await read_catalog(ToolboxEndpoint(BASE_URL), timeout_seconds=1.0)

    assert "Authorization" not in route.calls.last.request.headers


@pytest.mark.asyncio
async def test_read_catalog_does_not_retry_a_timeout() -> None:
    with respx.mock() as router:
        route = router.get(f"{BASE_URL}/v1/capabilities").mock(
            side_effect=httpx.ReadTimeout("slow")
        )
        with pytest.raises(ToolboxTimeout):
            await read_catalog(ToolboxEndpoint(BASE_URL), timeout_seconds=1.0)

    assert route.call_count == 1


def _opened_clients(monkeypatch) -> list[httpx.AsyncClient]:
    """Record every HTTP client read_catalog opens."""
    from acessilia_sdk.toolbox import catalog

    opened: list[httpx.AsyncClient] = []

    class Recording(httpx.AsyncClient):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            opened.append(self)

    monkeypatch.setattr(catalog.httpx, "AsyncClient", Recording)
    return opened


def _never_answers(sent: asyncio.Event):
    async def wait(request: httpx.Request) -> httpx.Response:
        sent.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    return wait


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("capabilities", "expected"),
    [
        (httpx.Response(200, json=CAPABILITIES), None),
        (httpx.ReadTimeout("slow"), ToolboxTimeout),
        (httpx.Response(200, text="not json"), ToolboxContractViolation),
    ],
    ids=["success", "timeout", "invalid-json"],
)
async def test_read_catalog_closes_its_client(monkeypatch, capabilities, expected) -> None:
    opened = _opened_clients(monkeypatch)
    with respx.mock(assert_all_called=False) as router:
        route = router.get(f"{BASE_URL}/v1/capabilities")
        if isinstance(capabilities, Exception):
            route.mock(side_effect=capabilities)
        else:
            route.mock(return_value=capabilities)
        router.get(f"{BASE_URL}/v1/providers").mock(
            return_value=httpx.Response(200, json=PROVIDERS)
        )
        if expected is None:
            await read_catalog(ToolboxEndpoint(BASE_URL), timeout_seconds=1.0)
        else:
            with pytest.raises(expected):
                await read_catalog(ToolboxEndpoint(BASE_URL), timeout_seconds=1.0)

    assert len(opened) == 1
    assert opened[0].is_closed


@pytest.mark.asyncio
async def test_read_catalog_closes_its_client_when_cancelled(monkeypatch) -> None:
    opened = _opened_clients(monkeypatch)
    sent = asyncio.Event()
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{BASE_URL}/v1/capabilities").mock(side_effect=_never_answers(sent))
        task = asyncio.create_task(
            read_catalog(ToolboxEndpoint(BASE_URL), timeout_seconds=30.0)
        )
        async with asyncio.timeout(5):
            await sent.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert len(opened) == 1
    assert opened[0].is_closed


@pytest.mark.asyncio
async def test_read_catalog_falls_back_to_the_callers_key() -> None:
    with respx.mock() as router:
        router.get(f"{BASE_URL}/v1/providers").mock(
            return_value=httpx.Response(200, json=PROVIDERS)
        )
        route = router.get(f"{BASE_URL}/v1/capabilities").mock(
            return_value=httpx.Response(200, json=CAPABILITIES)
        )
        await read_catalog(ToolboxEndpoint(BASE_URL), timeout_seconds=1.0, api_key="shared")
    assert route.calls.last.request.headers["Authorization"] == "Bearer shared"


@pytest.mark.asyncio
async def test_read_catalog_prefers_the_endpoint_key() -> None:
    with respx.mock() as router:
        router.get(f"{BASE_URL}/v1/providers").mock(
            return_value=httpx.Response(200, json=PROVIDERS)
        )
        route = router.get(f"{BASE_URL}/v1/capabilities").mock(
            return_value=httpx.Response(200, json=CAPABILITIES)
        )
        await read_catalog(
            ToolboxEndpoint(BASE_URL, "own"), timeout_seconds=1.0, api_key="shared"
        )
    assert route.calls.last.request.headers["Authorization"] == "Bearer own"
