"""Published normalization limits, input correlation and immutable HTTP retries."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from email.parser import BytesParser
from email.policy import HTTP
from pathlib import Path

import httpx
import pytest

from acessilia_sdk.toolbox.clients import ToolboxTextNormalizeClient
from acessilia_sdk.toolbox.errors import ToolboxContractViolation, ToolboxInvalidInput
from acessilia_sdk.toolbox.operation import operation_context
from acessilia_sdk.toolbox.text_normalization import (
    CAPABILITY,
    MAX_PAYLOAD_BYTES,
    TextTarget,
    canonical_json,
    normalization_batches,
    read_normalization,
    target_fingerprint,
)


def digest(value):
    return "sha256:" + hashlib.sha256(value).hexdigest()


def response(batch):
    results = [
        {
            "id": item.id,
            "text": item.text,
            "input_fingerprint": digest(
                json.dumps(
                    {"id": item.id, "text": item.text},
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode()
            ),
            "processed": bool(item.text),
            "changed": False,
        }
        for item in batch.targets
    ]
    return {
        "status": "succeeded",
        "capability": CAPABILITY + "@1",
        "provider": "docstruct-text",
        "document": {
            "results": results,
            "processed_count": sum(bool(t.text) for t in batch.targets),
            "changed_count": 0,
        },
        "provenance": {
            "capability": CAPABILITY,
            "capability_version": 1,
            "provider": "docstruct-text",
            "provider_version": "1.0.0",
            "input_fingerprints": [digest(batch.payload)],
            "parameters_hash": digest(b"{}"),
            "model_versions": {
                "runtime": "0.2.0",
                "docstruct": "0.5.8",
                "norm_fix": "0.5.8",
            },
        },
    }


def multipart(request):
    message = BytesParser(policy=HTTP).parsebytes(
        b"Content-Type: "
        + request.headers["content-type"].encode()
        + b"\r\n\r\n"
        + request.content
    )
    return {
        part.get_param("name", header="content-disposition"): part.get_payload(
            decode=True
        )
        for part in message.iter_parts()
    }


def test_fingerprint_vectors_captured_from_the_published_provider():
    path = (
        Path(__file__).parents[1] / "fixtures" / "text-normalization-fingerprints.json"
    )
    for vector in json.loads(path.read_text())["vectors"]:
        target = TextTarget(vector["id"], vector["text"])
        assert (
            canonical_json({"id": target.id, "text": target.text})
            == vector["canonical"].encode()
        )
        assert target_fingerprint(target) == vector["input_fingerprint"]


def test_partition_count_bytes_escaping_order_and_immutable_snapshot():
    targets = [TextTarget(str(i), "value") for i in range(257)]
    batches = normalization_batches(targets)
    assert [len(batch.targets) for batch in batches] == [256, 1]
    assert [item.id for batch in batches for item in batch.targets] == [
        str(i) for i in range(257)
    ]
    targets.clear()
    assert len(batches[0].targets) == 256
    # Each character takes six escaped JSON bytes; use the complete envelope budget.
    escaped = TextTarget("control", "\x00" * 180_000)
    with pytest.raises(ToolboxInvalidInput, match="byte limit"):
        normalization_batches([escaped])
    multibyte = [TextTarget(str(i), "😀" * 140_000) for i in range(2)]
    assert len(normalization_batches(multibyte)) == 2
    overhead = len(normalization_batches([TextTarget("edge", "")])[0].payload)
    exact = normalization_batches(
        [TextTarget("edge", "x" * (MAX_PAYLOAD_BYTES - overhead))]
    )[0]
    assert len(exact.payload) == MAX_PAYLOAD_BYTES
    with pytest.raises(ToolboxInvalidInput):
        normalization_batches(
            [TextTarget("edge", "x" * (MAX_PAYLOAD_BYTES - overhead + 1))]
        )


@pytest.mark.parametrize(
    "targets",
    [
        [TextTarget("same", "a"), TextTarget("same", "b")],
        [TextTarget("x" * 257, "a")],
        [TextTarget("", "a")],
        [TextTarget("x", "\ud800")],
        [TextTarget("\ud800", "a")],
        [TextTarget("x", 1)],
    ],
)
def test_invalid_requests_fail_before_transport(targets):
    with pytest.raises(ToolboxInvalidInput):
        normalization_batches(targets)


@pytest.mark.parametrize(
    "path,value",
    [
        (("capability",), "text.postprocess@1"),
        (("capability",), "document.text.normalize@2"),
        (("capability",), "document.text.normalize"),
        (("provider",), "other"),
        (("status",), "failed"),
        (("provenance", "capability_version"), True),
        (("provenance", "capability_version"), 2),
        (("provenance", "provider_version"), "1.1.0"),
        (("provenance", "provider"), "other"),
        (("provenance", "model_versions", "docstruct"), "0.5.9"),
        (("provenance", "model_versions", "norm_fix"), "0.5.9"),
        (("provenance", "model_versions", "runtime"), ""),
        (("provenance", "input_fingerprints"), ["sha256:" + "0" * 64]),
        (("provenance", "parameters_hash"), "sha256:" + "0" * 64),
        (("document", "results", 0, "id"), "other"),
        (("document", "results", 0, "input_fingerprint"), "sha256:" + "0" * 64),
        (("document", "results", 0, "processed"), False),
        (("document", "results", 0, "processed"), 1),
        (("document", "results", 0, "changed"), True),
        (("document", "results", 0, "text"), None),
        (("document", "results", 0, "text"), "\ud800"),
        (("document", "processed_count"), 0),
        (("document", "changed_count"), True),
        (("document", "unknown"), True),
        (("document", "results", 0, "unknown"), True),
    ],
)
def test_untrusted_observations_are_rejected(path, value):
    batch = normalization_batches([TextTarget("a", "text")])[0]
    payload = response(batch)
    parent = payload
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = value
    with pytest.raises(ToolboxContractViolation):
        read_normalization(payload, batch, provider="docstruct-text")


def test_empty_null_duplicate_missing_and_reordered_results():
    batch = normalization_batches(
        [TextTarget("a", None), TextTarget("b", ""), TextTarget("c", " ")]
    )[0]
    payload = response(batch)
    result = read_normalization(payload, batch, provider="docstruct-text")
    assert [item.text for item in result.observations] == [None, "", " "]
    assert result.processed_count == 1 and result.changed_count == 0
    for results in (
        payload["document"]["results"][:-1],
        payload["document"]["results"][::-1],
        [payload["document"]["results"][0]] * 3,
    ):
        bad = deepcopy(payload)
        bad["document"]["results"] = results
        with pytest.raises(ToolboxContractViolation):
            read_normalization(bad, batch, provider="docstruct-text")
    bad = deepcopy(payload)
    bad["document"]["results"][0].update(text="", changed=True)
    bad["document"]["changed_count"] = 1
    with pytest.raises(ToolboxContractViolation):
        read_normalization(bad, batch, provider="docstruct-text")


@pytest.mark.asyncio
async def test_transport_pins_version_provider_bytes_and_retry_identity(respx_mock):
    batch = normalization_batches([TextTarget("a", "text")])[0]
    seen = []

    def answer(request):
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(503, json={"code": "provider_unavailable"})
        return httpx.Response(200, json=response(batch))

    respx_mock.post(
        "http://normalize.test/v1/capabilities/document.text.normalize:execute"
    ).mock(side_effect=answer)
    client = ToolboxTextNormalizeClient(
        base_url="http://normalize.test",
        api_key="secret",
        retries=1,
        retry_backoff_seconds=0,
    )
    try:
        with operation_context("task", "operation"):
            result = await client.normalize(batch, use_remote_cache=False)
    finally:
        await client.close()
    assert result.observations[0].text == "text"
    for request in seen:
        form = multipart(request)
        assert form["provider"] == b"docstruct-text" and form["version"] == b"1"
        assert form["file"] == batch.payload and form["no_cache"] == b"true"
        assert request.headers["authorization"] == "Bearer secret"
        assert request.headers["X-Acessilia-Task-Id"] == "task"
        assert request.headers["X-Acessilia-Operation-Id"] == "operation"
    assert (
        seen[0].headers["X-Acessilia-Attempt-Id"]
        != seen[1].headers["X-Acessilia-Attempt-Id"]
    )


@pytest.mark.asyncio
async def test_invalid_input_conflict_is_not_retried_or_failed_over(respx_mock):
    route = respx_mock.post(
        "http://normalize.test/v1/capabilities/document.text.normalize:execute"
    ).respond(400, json={"code": "invalid_input", "message": "conflicting identity"})
    client = ToolboxTextNormalizeClient(
        endpoints=["http://normalize.test", "http://other.test"], retries=2
    )
    try:
        with pytest.raises(ToolboxInvalidInput):
            await client.normalize(normalization_batches([TextTarget("a", "text")])[0])
    finally:
        await client.close()
    assert route.call_count == 1
