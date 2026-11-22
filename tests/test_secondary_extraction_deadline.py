"""The secondary provider's own deadline in a dual extraction (#603).

With the primary's result in hand, the secondary gets only the time left
before the extraction-wide deadline, so a secondary that hangs degrades the
extraction to the primary instead of failing it. Without a primary result the
secondary is the only source and keeps the whole deadline.
"""

from __future__ import annotations

import asyncio
import time
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from acessilia_core.manifest import toolbox_extractor
from acessilia_core.manifest.toolbox_extractor import ToolboxManifestExtractor
from acessilia_sdk.toolbox import ToolboxTimeout
from acessilia_sdk.toolbox.clients import ToolboxStructureClient
from acessilia_sdk.toolbox.errors import ToolboxProviderUnavailable
from tests.core_config_support import fusion_config, paths_config, toolbox_config
from tests.test_toolbox_manifest_extractor import (
    FIXTURE_PDF,
    HANG_SECONDS,
    SAMPLE_TOOLBOX_RESPONSE,
)

DUAL = {"mode": "dual", "secondary_provider": "mineru"}


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)


async def _hang(*_args, **_kwargs):
    await asyncio.sleep(HANG_SECONDS)


def _clients(monkeypatch, *, primary, secondary):
    primary_client = AsyncMock(spec=ToolboxStructureClient)
    primary_client.base_url = "http://primary.test"
    primary_client.provider = "docling"
    primary_client.extract_structure = AsyncMock(**primary)
    secondary_client = AsyncMock(spec=ToolboxStructureClient)
    secondary_client.base_url = "http://secondary.test"
    secondary_client.provider = "mineru"
    secondary_client.extract_structure = AsyncMock(**secondary)
    monkeypatch.setattr(
        "acessilia_core.manifest.toolbox_extractor.make_toolbox_client",
        lambda *_args, **_kwargs: secondary_client,
    )
    return primary_client, secondary_client


def _extract(primary_client, *, timeout):
    return ToolboxManifestExtractor(client=primary_client).extract(
        FIXTURE_PDF,
        fusion=fusion_config(**DUAL),
        toolbox=toolbox_config(use_artifact_store=False, extraction_timeout_seconds=timeout),
        paths=paths_config(),
        operations=None,
    )


def test_a_hung_secondary_degrades_within_the_deadline(monkeypatch):
    primary, secondary = _clients(
        monkeypatch,
        primary={"return_value": deepcopy(SAMPLE_TOOLBOX_RESPONSE)},
        secondary={"side_effect": _hang},
    )

    started = time.monotonic()
    result = _extract(primary, timeout=3)
    elapsed = time.monotonic() - started

    # Bounded by the deadline less the reserve (a tenth of 3 s), not by the hang.
    assert elapsed < 3
    assert result.configuration["fusion"]["status"] == "degraded"
    assert result.configuration["extraction_degraded"] is True
    assert "fusion_evidence" not in result.document
    secondary.close.assert_awaited_once()


def test_no_time_left_degrades_without_waiting_for_the_secondary(monkeypatch):
    """A primary that used the whole budget leaves the secondary nothing."""
    monkeypatch.setattr(toolbox_extractor, "_secondary_budget", lambda *_a: 0.0)
    primary, secondary = _clients(
        monkeypatch,
        primary={"return_value": deepcopy(SAMPLE_TOOLBOX_RESPONSE)},
        secondary={"side_effect": _hang},
    )

    started = time.monotonic()
    result = _extract(primary, timeout=30)

    assert time.monotonic() - started < 1
    assert result.configuration["fusion"]["status"] == "degraded"
    assert result.configuration["fusion"]["reason"] == "ToolboxTimeout"
    secondary.extract_structure.assert_not_awaited()


def test_without_a_primary_result_a_hung_secondary_still_fails(monkeypatch):
    primary, _ = _clients(
        monkeypatch,
        primary={"side_effect": ToolboxProviderUnavailable("primary down")},
        secondary={"side_effect": _hang},
    )

    started = time.monotonic()
    with pytest.raises(ToolboxTimeout):
        _extract(primary, timeout=1)

    assert time.monotonic() - started < 3


def test_a_secondary_that_answers_in_time_is_fused(monkeypatch):
    payload = deepcopy(SAMPLE_TOOLBOX_RESPONSE)
    payload["provider"] = "mineru"
    primary, _ = _clients(
        monkeypatch,
        primary={"return_value": deepcopy(SAMPLE_TOOLBOX_RESPONSE)},
        secondary={"return_value": payload},
    )

    result = _extract(primary, timeout=30)

    assert result.configuration["fusion"]["status"] == "complete"
    assert "fusion_evidence" in result.document


@pytest.mark.parametrize(
    ("deadline", "elapsed", "expected"),
    [(1500, 300, 1500 - 300 - 60), (1500, 1500, -60), (10, 2, 10 - 2 - 1)],
)
def test_the_secondary_budget_keeps_a_reserve_for_the_fusion(
    monkeypatch, deadline, elapsed, expected
):
    monkeypatch.setattr(toolbox_extractor, "perf_counter", lambda: 1000.0 + elapsed)

    budget = toolbox_extractor._secondary_budget(
        toolbox_config(extraction_timeout_seconds=deadline), 1000.0
    )

    assert budget == pytest.approx(expected)


def test_a_provider_that_failed_on_the_document_still_falls_back():
    """#608: the SDK's error for ``provider_execution_failed`` is a provider failure.

    So in dual mode a primary that failed on the document still hands over to
    the secondary, as a 500 does, while the SDK no longer retries it.
    """
    import httpx

    from acessilia_sdk.toolbox.transport import raise_for_error

    response = httpx.Response(
        502,
        json={"code": "provider_execution_failed", "message": "mineru-api rejected"},
        request=httpx.Request("POST", "http://toolbox.test/v1/capabilities/x:execute"),
    )
    with pytest.raises(Exception) as info:
        raise_for_error(response, "document.structure.extract")

    assert type(info.value).__name__ == "ToolboxError"
    assert toolbox_extractor._provider_failure(info.value)
