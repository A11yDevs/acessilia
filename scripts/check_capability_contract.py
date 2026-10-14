"""Detect drift between the Toolbox capability catalogue and this core.

The core talks to the Toolbox over HTTP using capability ids and provider ids
that are declared in two different repositories. Nothing in either repository
currently verifies that they still match, so a rename on one side silently
produces a client that can only fail at runtime.

This script builds the cross-repository contract from the core side and checks
it against the Toolbox, either live (``--url``) or from a captured snapshot
(``--snapshot``), so it can run inside CI without a running Toolbox.

Usage:
    python scripts/check_capability_contract.py --snapshot tests/fixtures/toolbox-contract.json
    python scripts/check_capability_contract.py --url http://localhost:8002

Exit status is 0 when the contract holds, 1 when any drift is reported.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "backend" / "tools"
SETTINGS_PATH = REPO_ROOT / "backend" / "config" / "settings.py"

# Capabilities that the Toolbox implements internally and that the core must
# never call directly: they belong to the Toolbox's own orchestration.
INTERNAL_CAPABILITIES = frozenset({"cache.get", "cache.put"})

# Rest surfaces that back a whole capability family instead of a single
# ":execute" call. The core reaches these through dedicated REST routes.
REST_ROUTE_CAPABILITIES: dict[str, frozenset[str]] = {
    "/v1/datasets": frozenset(
        {
            "dataset.list",
            "dataset.describe",
            "dataset.list_splits",
            "dataset.list_items",
            "dataset.get_item",
            "dataset.get_artifact",
            "dataset.sample",
            "dataset.sync",
        }
    ),
    "/v1/artifacts": frozenset({"artifact.store", "artifact.retrieve"}),
}

_CAPABILITY_RE = re.compile(r'^[A-Z_]*CAPABILITY(?:_[A-Z]+)?\s*=\s*"([^"]+)"')
_PROVIDER_ENV_RE = re.compile(
    r'os\.getenv\(\s*"(TOOLBOX_[A-Z_]*PROVIDER)"\s*,\s*"([^"]*)"'
)
# Some clients inline the capability in the execute URL instead of declaring a
# constant, e.g. f"{base}/v1/capabilities/document.structure.extract:execute".
_INLINE_EXECUTE_RE = re.compile(
    r"/v1/capabilities/([a-z][a-z0-9]*(?:\.[a-z0-9]+)+):execute"
)
_URL_LITERAL_RE = re.compile(
    r'["\']([^"\']*?/v1/capabilities/([a-z][a-z0-9]*(?:\.[a-z0-9]+)+)[^"\']*)["\']'
)


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


def read_core_contract() -> CoreContract:
    contract = CoreContract()

    for path in sorted(TOOLS_DIR.glob("toolbox_*.py")):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))

        declared: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                match = _CAPABILITY_RE.match(f'{target.id} = "{_literal(node.value)}"')
                if match:
                    declared.add(match.group(1))

        # Capabilities that only appear inside an execute URL, built either as
        # a literal or as an f-string with a declared capability constant.
        for match in _INLINE_EXECUTE_RE.finditer(text):
            declared.add(match.group(1))
        for _, capability in _URL_LITERAL_RE.findall(text):
            declared.add(capability)

        for capability in declared:
            contract.capabilities.setdefault(capability, set()).add(path.name)

        for route, capabilities in REST_ROUTE_CAPABILITIES.items():
            if route in text:
                for capability in capabilities:
                    contract.capabilities.setdefault(capability, set()).add(
                        path.name
                    )

    settings_text = SETTINGS_PATH.read_text(encoding="utf-8")
    for env_name, default in _PROVIDER_ENV_RE.findall(settings_text):
        if default:
            contract.providers.setdefault(default, set()).add(env_name)

    return contract


def _literal(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ""


def read_toolbox_live(url: str) -> ToolboxContract:
    capabilities = _fetch(f"{url.rstrip('/')}/v1/capabilities")
    providers = _fetch(f"{url.rstrip('/')}/v1/providers")
    return _from_payloads(capabilities, providers)


def read_toolbox_snapshot(path: Path) -> ToolboxContract:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _from_payloads(payload["capabilities"], payload["providers"])


def _fetch(url: str) -> object:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
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
