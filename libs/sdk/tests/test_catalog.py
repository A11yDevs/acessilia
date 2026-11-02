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
    missing_requirements,
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
