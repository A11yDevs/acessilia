"""Detect drift between the Toolbox capability catalogue and this core.

The core talks to the Toolbox over HTTP using capability ids and provider ids
that are declared in two different repositories. Nothing in either repository
currently verifies that they still match, so a rename on one side silently
produces a client that can only fail at runtime.

This script reads the core side from ``libs/sdk/src/acessilia_sdk/toolbox/capabilities.py``
(the allowlist every Toolbox client goes through) and checks it against the
Toolbox, either live (``--url``) or from a captured snapshot (``--snapshot``),
so it can run inside CI without a running Toolbox. Live reads send
``TOOLBOX_API_KEY`` as a Bearer token when it is set.

Usage:
    python scripts/check_capability_contract.py --snapshot tests/fixtures/toolbox-contract.json
    python scripts/check_capability_contract.py --url http://localhost:8002

Exit status is 0 when the contract holds, 1 when any drift is reported.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = (
    REPO_ROOT / "libs" / "sdk" / "src" / "acessilia_sdk" / "toolbox" / "capabilities.py"
)
REGISTRY_MODULE = "acessilia_sdk.toolbox.capabilities"

# Capabilities that the Toolbox implements internally and that the core must
# never call directly: they belong to the Toolbox's own orchestration.
INTERNAL_CAPABILITIES = frozenset({"cache.get", "cache.put"})


@dataclass
class CoreContract:
    """What the core believes the Toolbox exposes."""

    #: capability id -> modules that declare it
    capabilities: dict[str, set[str]] = field(default_factory=dict)
    #: provider id -> settings attribute default that points at it
    providers: dict[str, set[str]] = field(default_factory=dict)


@dataclass
class ToolboxContract:
    capabilities: dict[str, set[str]]
    providers: dict[str, set[str]]


def _load_registry():
    # Loaded by path: the registry is pure data and must not pull in settings,
    # HTTP clients or a .env file just to be compared.
    spec = importlib.util.spec_from_file_location(
        "toolbox_capabilities", REGISTRY_PATH
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def read_core_contract() -> CoreContract:
    registry = _load_registry()
    contract = CoreContract()

    for capability in registry.TOOLBOX_CAPABILITIES.values():
        contract.capabilities.setdefault(capability.id, set()).add(
            REGISTRY_MODULE
        )

    for setting, default in registry.PROVIDER_DEFAULTS.items():
        contract.providers.setdefault(default, set()).add(setting.upper())

    return contract


def read_toolbox_live(url: str) -> ToolboxContract:
    capabilities = _fetch(f"{url.rstrip('/')}/v1/capabilities")
    providers = _fetch(f"{url.rstrip('/')}/v1/providers")
    return _from_payloads(capabilities, providers)


def read_toolbox_snapshot(path: Path) -> ToolboxContract:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _from_payloads(payload["capabilities"], payload["providers"])


def _fetch(url: str) -> object:
    request = urllib.request.Request(url)
    api_key = os.getenv("TOOLBOX_API_KEY", "")
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SystemExit(f"cannot reach the Toolbox at {url}: {exc}")


def _from_payloads(capabilities: object, providers: object) -> ToolboxContract:
    caps: dict[str, set[str]] = {}
    for entry in capabilities or []:
        if isinstance(entry, dict) and entry.get("id"):
            caps[str(entry["id"])] = {
                str(item) for item in (entry.get("providers") or [])
            }

    provs: dict[str, set[str]] = {}
    for entry in providers or []:
        if isinstance(entry, dict) and entry.get("id"):
            provs[str(entry["id"])] = {
                str(item) for item in (entry.get("capabilities") or [])
            }
    return ToolboxContract(capabilities=caps, providers=provs)


def compare(
    core: CoreContract, toolbox: ToolboxContract
) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    notes: list[str] = []

    missing_caps = sorted(set(core.capabilities) - set(toolbox.capabilities))
    for capability in missing_caps:
        modules = ", ".join(sorted(core.capabilities[capability]))
        failures.append(
            f"core consumes capability {capability!r} ({modules}) "
            f"but the Toolbox does not expose it"
        )

    missing_providers = sorted(set(core.providers) - set(toolbox.providers))
    for provider in missing_providers:
        settings = ", ".join(sorted(core.providers[provider]))
        failures.append(
            f"core default for {settings} points at provider {provider!r} "
            f"which the Toolbox does not register"
        )

    provider_caps = {
        capability
        for capabilities in toolbox.providers.values()
        for capability in capabilities
    }
    unknown = sorted(provider_caps - set(toolbox.capabilities) - INTERNAL_CAPABILITIES)
    for capability in unknown:
        failures.append(
            f"Toolbox providers declare capability {capability!r} "
            f"but no capability manifest exposes it"
        )

    unconsumed = sorted(
        set(toolbox.capabilities)
        - set(core.capabilities)
        - set(INTERNAL_CAPABILITIES)
    )
    if unconsumed:
        notes.append(
            "capabilities exposed by the Toolbox with no client in the core: "
            + ", ".join(unconsumed)
        )

    return failures, notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--url", help="base URL of a running Toolbox")
    source.add_argument("--snapshot", type=Path, help="captured contract JSON")
    args = parser.parse_args(argv)

    core = read_core_contract()
    toolbox = (
        read_toolbox_live(args.url)
        if args.url
        else read_toolbox_snapshot(args.snapshot)
    )

    failures, notes = compare(core, toolbox)

    print(f"core capabilities: {len(core.capabilities)}")
    print(f"core provider defaults: {len(core.providers)}")
    print(f"toolbox capabilities: {len(toolbox.capabilities)}")
    print(f"toolbox providers: {len(toolbox.providers)}")

    for note in notes:
        print(f"\nnote: {note}")

    if failures:
        print(f"\n{len(failures)} contract violation(s):", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print("\ncapability contract holds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
