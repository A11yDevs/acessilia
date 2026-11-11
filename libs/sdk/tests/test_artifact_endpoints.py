"""Which Toolbox deployments a set of clients addresses (#402, step 5).

An artifact id is reusable only within one deployment (ADR-0006, ADR-0013):
the core's extractor uploads once and passes the id to extraction only when
every client involved addresses the same single URL. These cases were written
against the extractor's private helpers on develop and pass unchanged here,
apart from the import, since the helpers moved to the SDK.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytest_asyncio

from acessilia_sdk.toolbox import (
    ToolboxEndpoint,
    artifact_endpoint_urls,
    one_artifact_endpoint,
)
from acessilia_sdk.toolbox.clients import ToolboxArtifactClient, ToolboxStructureClient

A = "http://toolbox-a.test"
B = "http://toolbox-b.test"


@pytest_asyncio.fixture
async def clients():
    made = []

    def make(cls, **kwargs):
        client = cls(**kwargs)
        made.append(client)
        return client

    yield make
    for client in made:
        await client.close()


@pytest.mark.asyncio
async def test_a_client_contributes_every_endpoint_it_may_use(clients) -> None:
    client = clients(ToolboxStructureClient, endpoints=f"{A},{B}/")
    assert artifact_endpoint_urls(client) == {A, B}


@pytest.mark.asyncio
async def test_urls_are_collected_across_clients(clients) -> None:
    structure = clients(ToolboxStructureClient, base_url=f"{A}/")
    artifacts = clients(ToolboxArtifactClient, endpoints=[ToolboxEndpoint(B, "key")])
    assert artifact_endpoint_urls(structure, artifacts) == {A, B}
    assert artifact_endpoint_urls(structure, None) == {A}


def test_without_endpoints_the_base_url_is_used_without_a_trailing_slash() -> None:
    legacy = SimpleNamespace(base_url=f"{A}/")
    assert artifact_endpoint_urls(legacy) == {A}
    assert artifact_endpoint_urls(SimpleNamespace(endpoints=(), base_url=B)) == {B}


def test_endpoints_win_over_the_base_url() -> None:
    client = SimpleNamespace(endpoints=(ToolboxEndpoint(A),), base_url=B)
    assert artifact_endpoint_urls(client) == {A}


def test_a_client_with_no_url_contributes_nothing() -> None:
    assert artifact_endpoint_urls(SimpleNamespace(), SimpleNamespace(base_url=None)) == set()
    assert artifact_endpoint_urls() == set()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("urls", "expected"),
    [
        ([], True),
        ([A], True),
        ([A, f"{A}/"], True),
        ([A, B], False),
    ],
    ids=["none", "one", "one-with-slash", "two"],
)
async def test_an_artifact_is_shared_only_within_one_url(clients, urls, expected) -> None:
    involved = [clients(ToolboxStructureClient, base_url=url) for url in urls]
    assert one_artifact_endpoint(*involved, None) is expected
