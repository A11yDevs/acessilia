"""Atomic Core acceptance of input-bound, bounded normalization observations."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from email.parser import BytesParser
from email.policy import HTTP
from pathlib import Path

import httpx
import pytest
from core_config_support import core_config
from pddl_support import build_element, build_manifest, build_obligation

from acessilia_core.i18n import reset_request_locale, set_request_locale
from acessilia_core.manifest.models import ProcessingManifest
from acessilia_core.pipeline.handlers.text_normalization import _handle_norm_fix_method
from acessilia_core.ports import RunPorts

ENDPOINT = "http://toolbox-render.test/v1/capabilities/document.text.normalize:execute"


def digest(value):
    return "sha256:" + hashlib.sha256(value).hexdigest()


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def manifest_for(texts):
    elements = [
        build_element(
            f"e{i}", "paragraph", text=text, metadata={"keep": i}, reading_order=i + 1
        )
        for i, text in enumerate(texts)
    ]
    return build_manifest(
        elements,
        [build_obligation("normalize-text", [e.id for e in elements], ["norm-fix"])],
    )


class Probe:
    def __init__(self):
        self.requests = []
        self.outputs = {}
        self.change = lambda payload: None
        self.before = lambda number: None

    def answer(self, request):
        message = BytesParser(policy=HTTP).parsebytes(
            b"Content-Type: "
            + request.headers["content-type"].encode()
            + b"\r\n\r\n"
            + request.content
        )
        fields = {
            p.get_param("name", header="content-disposition"): p.get_payload(
                decode=True
            )
            for p in message.iter_parts()
        }
        raw = fields["file"]
        self.requests.append((request, raw))
        self.before(len(self.requests))
        targets = json.loads(raw)["targets"]
        results = []
        for target in targets:
            text = self.outputs.get(target["id"], target["text"])
            results.append(
                {
                    **target,
                    "text": text,
                    "input_fingerprint": digest(canonical(target)),
                    "processed": bool(target["text"]),
                    "changed": text != target["text"],
                }
            )
        payload = {
            "status": "succeeded",
            "capability": "document.text.normalize@1",
            "provider": "docstruct-text",
            "document": {
                "results": results,
                "processed_count": sum(t["processed"] for t in results),
                "changed_count": sum(t["changed"] for t in results),
            },
            "provenance": {
                "capability": "document.text.normalize",
                "capability_version": 1,
                "provider": "docstruct-text",
                "provider_version": "1.0.0",
                "input_fingerprints": [digest(raw)],
                "parameters_hash": digest(b"{}"),
                "model_versions": {
                    "runtime": "0.2.0",
                    "docstruct": "0.5.8",
                    "norm_fix": "0.5.8",
                },
            },
        }
        self.change(payload)
        return httpx.Response(200, json=payload)


@pytest.fixture
def provider(respx_mock):
    probe = Probe()
    respx_mock.post(ENDPOINT).mock(side_effect=probe.answer)
    return probe


def normalize(manifest, ports=None, config=None):
    token = set_request_locale("en_US")
    try:
        return _handle_norm_fix_method(
            manifest,
            "o-1",
            config=config or core_config(),
            ports=ports or RunPorts.none(),
        )
    finally:
        reset_request_locale(token)


LEGACY = json.loads(
    (Path(__file__).parent / "fixtures" / "text-normalization-legacy.json").read_text()
)


@pytest.mark.parametrize("case", LEGACY["cases"], ids=lambda case: case["name"])
def test_frozen_original_handler_text_metadata_counts_and_noop_parity(provider, case):
    elements = [
        build_element(
            item["id"],
            "paragraph",
            text=item["text"],
            metadata=deepcopy(item["metadata"]),
            reading_order=i + 1,
        )
        for i, item in enumerate(case["input"])
    ]
    manifest = build_manifest(
        elements,
        [build_obligation("normalize-text", [e.id for e in elements], ["norm-fix"])],
    )
    provider.outputs = {item["id"]: item["text"] for item in case["output"]}
    result = normalize(manifest)
    assert result.success == case["success"] and result.validated == case["validated"]
    assert [
        {"id": e.id, "text": e.text, "metadata": e.metadata} for e in manifest.elements
    ] == case["output"]
    count = sum(bool(item["text"]) for item in case["input"])
    assert len(provider.requests) == bool(count)
    if count:
        assert str(count) in result.message
        assert len(json.loads(provider.requests[0][1])["targets"]) == count


def test_scope_includes_only_requested_targets_in_reading_order(provider):
    manifest = manifest_for(["first", "second", "third"])
    manifest.obligations[0].target_ids = ["e2", "missing", "e0"]
    assert normalize(manifest).success
    assert [t["id"] for t in json.loads(provider.requests[0][1])["targets"]] == [
        "e0",
        "e2",
    ]


@pytest.mark.parametrize(
    "change", ["text", "metadata", "target_ids", "revision", "remove", "order"]
)
def test_current_context_is_rechecked_before_any_update(provider, change):
    manifest = manifest_for(["ﬁ", "ﬁ"])
    provider.outputs = {"e0": "fi", "e1": "fi"}

    def mutate(_):
        if change == "text":
            manifest.elements[0].text = "new revision"
        elif change == "metadata":
            manifest.elements[0].metadata["concurrent"] = True
        elif change == "target_ids":
            manifest.obligations[0].target_ids.pop()
        elif change == "revision":
            manifest.revision += 1
        elif change == "remove":
            manifest.obligations.clear()
        else:
            manifest.elements[0].reading_order = 10

    provider.before = mutate
    result = normalize(manifest)
    assert not result.success and "stale" in result.message
    assert manifest.elements[1].text == "ﬁ"
    assert all("norm_fixed" not in e.metadata for e in manifest.elements)


@pytest.mark.parametrize("error", ["timeout", "malformed", "old_toolbox"])
def test_later_batch_failure_never_applies_the_successful_prefix(provider, error):
    manifest = manifest_for(["ﬁ"] * 257)
    before = manifest.model_dump()
    provider.outputs = {e.id: "fi" for e in manifest.elements}

    def before_call(number):
        if number == 2 and error == "timeout":
            raise httpx.ReadTimeout("second batch timed out")

    def change(payload):
        if len(provider.requests) == 2:
            if error == "malformed":
                payload["document"]["results"][0]["input_fingerprint"] = (
                    "sha256:" + "0" * 64
                )
            elif error == "old_toolbox":
                payload["provenance"]["capability_version"] = 2

    provider.before, provider.change = before_call, change
    result = normalize(manifest)
    assert not result.success and not result.validated
    assert manifest.model_dump() == before
    assert [len(json.loads(raw)["targets"]) for _, raw in provider.requests] == [256, 1]
    ids = [
        request.headers["X-Acessilia-Operation-Id"] for request, _ in provider.requests
    ]
    assert len(set(ids)) == 2


@pytest.mark.parametrize(
    "bad", ["x" * 1_048_576, "\ud800"], ids=["oversized", "invalid-unicode"]
)
def test_indivisible_invalid_input_never_makes_a_remote_call(provider, bad):
    manifest = manifest_for([bad])
    assert not normalize(manifest).success
    assert not provider.requests
    assert manifest.elements[0].text == bad


def test_long_id_refused_and_missing_obligation_preserves_legacy_failure(provider):
    manifest = manifest_for(["ﬁ"])
    manifest.elements[0].id = "x" * 257
    manifest.obligations[0].target_ids = [manifest.elements[0].id]
    assert not normalize(manifest).success
    manifest.obligations.clear()
    assert not normalize(manifest).success
    assert not provider.requests


class Interrupted(BaseException):
    pass


class Operations:
    job_id = "job-normalize"

    def __init__(self, journal):
        self.journal = journal
        self.active = set()

    def begin(self, slot):
        operation_id = self.journal.setdefault(slot, f"operation-{len(self.journal)}")
        self.active.add(operation_id)
        return operation_id

    def finish(self, operation_id):
        self.active.remove(operation_id)


def test_interrupt_and_rehydrate_retry_original_batches_with_durable_slot_identity(
    provider,
):
    manifest = manifest_for(["ﬁ"] * 257)
    checkpoint = manifest.model_dump_json()
    journal = {}
    operations = Operations(journal)
    provider.outputs = {e.id: "fi" for e in manifest.elements}

    def interrupt(number):
        if number == 2:
            raise Interrupted()

    provider.before = interrupt
    with pytest.raises(Interrupted):
        normalize(manifest, replace(RunPorts.none(), operations=operations))
    assert manifest.model_dump_json() == checkpoint and not operations.active
    original = [
        (req.headers["X-Acessilia-Operation-Id"], raw) for req, raw in provider.requests
    ]
    resumed = ProcessingManifest.model_validate_json(checkpoint)
    provider.before = lambda _: None
    restarted = Operations(journal)
    assert normalize(resumed, replace(RunPorts.none(), operations=restarted)).success
    assert [
        (req.headers["X-Acessilia-Operation-Id"], raw)
        for req, raw in provider.requests[2:]
    ] == original
    assert all(e.text == "fi" and e.metadata["norm_fixed"] for e in resumed.elements)
    assert not restarted.active


def test_changed_input_and_cache_policy_use_distinct_journal_slots(provider):
    journal = {}
    operations = Operations(journal)
    ports = replace(RunPorts.none(), operations=operations)
    for text in ("ﬁ", "other input"):
        assert normalize(manifest_for([text]), ports).success
    config = core_config()
    config = replace(config, toolbox=replace(config.toolbox, use_remote_cache=True))
    assert normalize(manifest_for(["other input"]), ports, config).success
    assert len(journal) == 3


@pytest.mark.parametrize(
    "catalogue", ["published", "absent", "new-version", "wrong-provider"]
)
def test_normalization_gate_requires_exact_contract_and_provider(catalogue):
    from acessilia_core.planning import toolbox_gate
    from acessilia_sdk.toolbox import snapshot_from_payloads

    payload = json.loads(
        (Path(__file__).parent / "fixtures" / "toolbox-contract.json").read_text()
    )
    capability = next(
        item
        for item in payload["capabilities"]
        if item["id"] == "document.text.normalize"
    )
    if catalogue == "absent":
        payload["capabilities"].remove(capability)
    elif catalogue == "new-version":
        capability["version"] = 2
    config = core_config()
    if catalogue == "wrong-provider":
        config = replace(
            config,
            toolbox=replace(
                config.toolbox,
                providers={
                    "toolbox_text_normalize_provider": "pure-text",
                },
            ),
        )
    decision = toolbox_gate.evaluate(
        ["norm-fix"],
        snapshot_from_payloads(
            payload["capabilities"], payload["providers"], fetched_at=0
        ),
        mode="enforce",
        config=config,
    )
    assert ("norm-fix" in decision.blocked) == (catalogue != "published")
    selected = "pure-text" if catalogue == "wrong-provider" else "docstruct-text"
    assert decision.catalogue_facts().offers(
        ("document.text.normalize@1", selected)
    ) == (catalogue == "published")
    assert "norm-fix" not in toolbox_gate.LOCAL_METHODS


def test_older_toolbox_without_capability_fails_without_local_repair(respx_mock):
    manifest = manifest_for(["ﬁrst  text"])
    original = manifest.model_dump_json()
    route = respx_mock.post(ENDPOINT).respond(
        404, json={"code": "capability_not_found", "message": "unknown capability"}
    )
    result = normalize(manifest)
    assert not result.success and not result.validated
    assert manifest.model_dump_json() == original
    assert route.call_count == 1
