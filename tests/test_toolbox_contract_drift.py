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
        "pdf.validate.pdf_ua",
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
