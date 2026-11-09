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
