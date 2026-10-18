"""ToolboxTableClient sends table.recognize as the Toolbox adapter expects."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from acessilia_sdk.toolbox.clients.table import ToolboxTableClient

BASE = "http://toolbox.test"
ROUTE = f"{BASE}/v1/capabilities/table.recognize:execute"
DOCUMENT = {
    "greedy": {"text": "<table></table>", "finish": "stop"},
    "samples": [{"text": "<table></table>", "finish": "stop", "seed": 0}],
    "temperature": 0.7,
    "top_p": 0.95,
    "use_hints": True,
    "header_cells": "th",
    "model": "qwen3-vl-8b",
}


@pytest.mark.asyncio
async def test_recognize_sends_the_experiment_parameters() -> None:
    client = ToolboxTableClient(base_url=BASE, api_key="k")
    try:
        with respx.mock() as router:
            route = router.post(ROUTE).mock(
                return_value=httpx.Response(200, json={"status": "succeeded", "document": DOCUMENT})
            )
            result = await client.recognize(
                artifact_id="crop-1",
                hints=["<table>a</table>"],
                use_hints=False,
                header_cells="td",
                samples=1,
                seed=7,
            )
        form = dict(httpx.QueryParams(route.calls.last.request.content.decode()))
        assert form["provider"] == "qwen3-vl-8b"
        assert form["artifact_id"] == "crop-1"
        assert json.loads(form["parameters"]) == {
            "hints": ["<table>a</table>"],
            "use_hints": False,
            "header_cells": "td",
            "samples": 1,
            "temperature": 0.7,
            "top_p": 0.95,
            "seed": 7,
        }
        assert route.calls.last.request.headers["Authorization"] == "Bearer k"
        assert result["document"]["greedy"]["finish"] == "stop"
    finally:
        await client.close()
