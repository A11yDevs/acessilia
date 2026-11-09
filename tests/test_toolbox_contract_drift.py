"""Keeps the core's Toolbox capability contract honest.

The core reaches the Toolbox by hard-coding capability and provider ids that
live in another repository (``acessilia-toolbox``). Nothing verified that those
ids still exist, so a rename on either side produced a client that could only
fail at runtime.

``scripts/check_capability_contract.py`` compares the two sides. CI runs it
against the contract the Toolbox publishes (``contract/toolbox-contract.json``
in its repository, #186). This module runs it offline against
``tests/fixtures/toolbox-contract.json``, a copy of that file refreshed with
``scripts/capture_toolbox_contract.py --ref develop``, and asserts an exact set
of findings: the known drift is recorded here, and any *new* drift
fails the suite. Fixing a finding requires removing it from the expected list,
which is what makes the ratchet tighten over time.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = REPO_ROOT / "scripts" / "check_capability_contract.py"
SNAPSHOT_PATH = REPO_ROOT / "tests" / "fixtures" / "toolbox-contract.json"

# Accepted drift between the core and the Toolbox catalogue. Each entry would be
# a capability the core consumes without the Toolbox exposing it, or a provider
# default in the SDK registry that the Toolbox does not register.
#
# Empty since the Toolbox publishes the Dr.DocBench VLM capabilities
# (acessilia-toolbox#50, provider qwen3-vl-8b) and the SDK defaults point at
# that provider. The snapshot was regenerated from Toolbox develop c777886.
KNOWN_DRIFT: frozenset[str] = frozenset()

# Capabilities the Toolbox exposes that the core has no client for at all. These
# are candidates for "integrate / keep as opt-in / retire" in the review.
EXPECTED_UNCONSUMED = frozenset(
    {
        "accessibility.mark",
        "chem.convert",
        "chem.recognize",
        "code.normalize",
        "music.omr",
        "text.postprocess",
    }
)


def _load_checker():
    spec = importlib.util.spec_from_file_location(
        "check_capability_contract", CHECKER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Register before execution: dataclasses resolve annotations through
    # sys.modules[cls.__module__].
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checker():
    return _load_checker()


@pytest.fixture(scope="module")
def snapshot() -> dict:
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def test_snapshot_is_well_formed(snapshot: dict) -> None:
    assert snapshot["capabilities"], "snapshot has no capabilities"
    assert snapshot["providers"], "snapshot has no providers"
    keys = [(entry["id"], entry["version"]) for entry in snapshot["capabilities"]]
    assert len(keys) == len(set(keys)), "duplicate capability versions in the snapshot"


def test_known_drift_is_unchanged(checker, snapshot: dict) -> None:
    core = checker.read_core_contract()
    toolbox = checker.read_toolbox_snapshot(SNAPSHOT_PATH)
    failures, _ = checker.compare(core, toolbox)

    new = sorted(set(failures) - KNOWN_DRIFT)
    assert not new, (
        "new capability contract drift:\n  - " + "\n  - ".join(new)
    )


def test_resolved_drift_is_removed_from_the_ratchet(checker, snapshot: dict) -> None:
    core = checker.read_core_contract()
    toolbox = checker.read_toolbox_snapshot(SNAPSHOT_PATH)
    failures, _ = checker.compare(core, toolbox)

    resolved = sorted(KNOWN_DRIFT - set(failures))
    assert not resolved, (
        "these findings were fixed; remove them from KNOWN_DRIFT:\n  - "
        + "\n  - ".join(resolved)
    )


def test_unconsumed_capabilities_match_the_review(checker, snapshot: dict) -> None:
    core = checker.read_core_contract()
    toolbox = checker.read_toolbox_snapshot(SNAPSHOT_PATH)
    _, notes = checker.compare(core, toolbox)

    assert len(notes) == 1
    prefix = "capabilities exposed by the Toolbox with no client in the SDK: "
    assert notes[0].startswith(prefix)
    unconsumed = {item.strip() for item in notes[0][len(prefix) :].split(",")}

    assert unconsumed == EXPECTED_UNCONSUMED, (
        "the set of capabilities with no core client changed; "
        "update the verdicts in docs/toolbox_capability_matrix.md and this test"
    )


def test_a_toolbox_without_the_sdk_contract_version_is_drift(checker) -> None:
    """The SDK sends its exact version on execute; v1 alone fails pdf.render@2."""
    core = checker.read_core_contract()
    toolbox = checker.read_toolbox_snapshot(SNAPSHOT_PATH)
    toolbox.versions["pdf.render"] = {1}

    failures, _ = checker.compare(core, toolbox)

    assert "core sends pdf.render@2 but the Toolbox publishes pdf.render@1" in failures


def _without_binding(toolbox, capability: str, provider: str) -> None:
    """Unbind ``provider`` from ``capability`` on both sides of the snapshot."""
    toolbox.capabilities[capability].discard(provider)
    for key in [key for key in toolbox.bindings if key[0] == capability]:
        toolbox.bindings[key].discard(provider)
    toolbox.providers[provider].discard(capability)


def test_a_default_provider_that_no_longer_serves_its_capability_is_drift(checker) -> None:
    """Reproduces the gap found in the review of #324.

    ``pp-formulanet`` stays registered (it is still a known provider id), but no
    longer serves ``math.recognize``. Before the binding check, the comparison
    still reported "capability contract holds" although every math recognition
    call would fail with the default configuration.
    """
    core = checker.read_core_contract()
    toolbox = checker.read_toolbox_snapshot(SNAPSHOT_PATH)
    toolbox.providers["pp-formulanet"] = {"math.recognize", "chem.recognize"}
    _without_binding(toolbox, "math.recognize", "pp-formulanet")

    failures, _ = checker.compare(core, toolbox)

    assert (
        "core default for TOOLBOX_MATH_RECOGNIZE_PROVIDER points at provider "
        "'pp-formulanet', which does not serve math.recognize@1"
    ) in failures


def test_a_default_provider_must_serve_the_version_the_sdk_sends(checker) -> None:
    """A provider bound to another version of the capability is not enough."""
    core = checker.read_core_contract()
    toolbox = checker.read_toolbox_snapshot(SNAPSHOT_PATH)
    toolbox.versions["pdf.render"] = {1, 2}
    toolbox.bindings[("pdf.render", 1)] = {"pymupdf-pdf"}
    toolbox.bindings[("pdf.render", 2)] = set()

    failures, _ = checker.compare(core, toolbox)

    assert (
        "core default for TOOLBOX_PDF_PROVIDER points at provider "
        "'pymupdf-pdf', which does not serve pdf.render@2"
    ) in failures


def test_every_default_binding_in_the_snapshot_holds(checker) -> None:
    """Each provider default serves every capability version it is used for."""
    core = checker.read_core_contract()
    toolbox = checker.read_toolbox_snapshot(SNAPSHOT_PATH)

    assert core.default_bindings, "the registry declares no provider defaults"
    for capability, version, provider, _setting in core.default_bindings:
        assert provider in toolbox.bindings[(capability, version)], (capability, version, provider)


def test_a_capability_that_disappears_is_reported_once(checker) -> None:
    """Review of #413: a missing capability must not also fail as a binding.

    ``math.recognize`` disappears from the catalogue and from every provider,
    while ``pp-formulanet`` stays registered for another capability. The only
    finding about it is the missing capability.
    """
    core = checker.read_core_contract()
    toolbox = checker.read_toolbox_snapshot(SNAPSHOT_PATH)
    del toolbox.capabilities["math.recognize"]
    del toolbox.versions["math.recognize"]
    for key in [key for key in toolbox.bindings if key[0] == "math.recognize"]:
        del toolbox.bindings[key]
    for capabilities in toolbox.providers.values():
        capabilities.discard("math.recognize")
    toolbox.providers["pp-formulanet"] = {"chem.recognize"}

    failures, _ = checker.compare(core, toolbox)

    about_math = [failure for failure in failures if "math.recognize" in failure]
    assert len(about_math) == 1, about_math
    assert about_math[0].startswith("core consumes capability 'math.recognize'")


# ── Idempotency (#406) ─────────────────────────────────────────────────────


def _snapshot_with(entries_for: dict[tuple[str, int], object], checker, *, drop=()):
    """The fixture's contract with some published ``idempotent`` values replaced.

    ``entries_for`` maps (capability, version) to the value to publish; ``drop``
    lists versions whose ``execution`` block is removed altogether.
    """
    payload = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    for entry in payload["capabilities"]:
        key = (entry["id"], entry["version"])
        if key in drop:
            entry.pop("execution", None)
        elif key in entries_for:
            entry["execution"] = {"idempotent": entries_for[key]}
    return checker._from_payloads(payload["capabilities"], payload["providers"])


def test_the_snapshot_publishes_idempotent_for_every_sdk_capability(checker) -> None:
    core = checker.read_core_contract()
    toolbox = checker.read_toolbox_snapshot(SNAPSHOT_PATH)

    for capability, version in core.versions.items():
        assert isinstance(toolbox.idempotent[(capability, version)], bool), capability
    assert core.idempotent["dataset.sample"] is False
    assert toolbox.idempotent[("dataset.sample", 1)] is False
    assert toolbox.idempotent[("dataset.sync", 1)] is True


def test_a_registry_that_disagrees_with_the_toolbox_is_drift(checker) -> None:
    core = checker.read_core_contract()
    toolbox = _snapshot_with({("dataset.sample", 1): True}, checker)

    failures, _ = checker.compare(core, toolbox)

    assert failures == [
        "the SDK registry has idempotent=False for dataset.sample@1, "
        "but the Toolbox publishes True"
    ]


def test_a_missing_idempotent_is_drift_not_permission_to_repeat(checker) -> None:
    core = checker.read_core_contract()
    toolbox = _snapshot_with({}, checker, drop={("dataset.sync", 1)})

    failures, _ = checker.compare(core, toolbox)

    assert failures == ["the Toolbox publishes no execution.idempotent for dataset.sync@1"]


@pytest.mark.parametrize("value", [None, "true", 1, 0])
def test_a_non_boolean_idempotent_is_drift(checker, value) -> None:
    core = checker.read_core_contract()
    toolbox = _snapshot_with({("dataset.sync", 1): value}, checker)

    failures, _ = checker.compare(core, toolbox)

    assert failures == [
        f"the Toolbox publishes execution.idempotent={value!r} for dataset.sync@1, "
        "which is not a boolean"
    ]


def test_idempotency_is_compared_at_the_version_the_sdk_sends(checker) -> None:
    """pdf.render is published as @1 and @2; the SDK sends @2."""
    core = checker.read_core_contract()
    assert core.versions["pdf.render"] == 2

    other_version_differs = _snapshot_with({("pdf.render", 1): False}, checker)
    assert checker.compare(core, other_version_differs)[0] == []

    sent_version_differs = _snapshot_with({("pdf.render", 2): False}, checker)
    assert checker.compare(core, sent_version_differs)[0] == [
        "the SDK registry has idempotent=True for pdf.render@2, "
        "but the Toolbox publishes False"
    ]


def test_the_capture_keeps_idempotent_and_the_output_schema_as_published() -> None:
    spec = importlib.util.spec_from_file_location(
        "capture_toolbox_contract", REPO_ROOT / "scripts" / "capture_toolbox_contract.py"
    )
    capture = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(capture)

    normalized = capture._normalize(
        [
            {"id": "b", "version": 1, "providers": [], "execution": {"idempotent": False,
                                                                   "cacheable": True},
             "output": {"schema": "artifact/x@1", "media_types": ["application/json"]}},
            {"id": "a", "version": 1, "providers": [], "execution": {"idempotent": None}},
            {"id": "c", "version": 1, "providers": []},
        ],
        [],
    )

    assert normalized["capabilities"] == [
        {"id": "a", "version": 1, "providers": [], "execution": {"idempotent": None}},
        {"id": "b", "version": 1, "providers": [], "output": {"schema": "artifact/x@1"},
         "execution": {"idempotent": False}},
        {"id": "c", "version": 1, "providers": []},
    ]
