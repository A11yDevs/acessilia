"""Refresh the Toolbox capability/provider contract fixture.

The Toolbox publishes its contract as ``contract/toolbox-contract.json`` in its
repository and on every release (acessilia-toolbox#71); that file is the source
of truth, and CI checks the SDK registry against it (#186).
``tests/fixtures/toolbox-contract.json`` is a copy of it for the offline tests.

``--ref`` copies byte-exact public files at an immutable Toolbox commit,
including route/schema metadata and a checksum manifest. ``--url`` captures
only a diagnostic snapshot of a running deployment, at an explicit output path
outside ``tests/fixtures``.

Usage:
    python scripts/capture_toolbox_contract.py --ref <40-character-commit-sha>
    python scripts/capture_toolbox_contract.py --url http://localhost:8002 --out /tmp/live.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "tests" / "fixtures" / "toolbox-contract.json"
CORE_OUT = REPO_ROOT / "libs" / "core" / "tests" / "fixtures" / "toolbox-contract.json"
#: Public contract URL, always addressed by an immutable commit SHA.
PUBLISHED_URL = "https://raw.githubusercontent.com/A11yDevs/acessilia-toolbox/{ref}/contract/toolbox-contract.json"
#: The published schemas the SDK generates models from (#185, #213), copied
#: from the same ref as the contract so the two snapshots always agree.
SDK_MODEL_SCHEMAS = (
    "reference@1.json",
    "structured-document@1.json",
    "layout-analysis@1.json",
    "latex@1.json",
    "mathml@1.json",
    "verbalized@1.json",
    "page-judgement@1.json",
    "region-transcription@1.json",
    "pdf-validation-report@1.json",
    "media-inspection@1.json",
    "image@2.json",
    "text-spans@1.json",
    "dataset-info@1.json",
    "dataset-split@1.json",
    "dataset-item-summary@1.json",
    "dataset-item@1.json",
    "dataset-artifact@1.json",
    "dataset-sync-entry@1.json",
    "dataset-list@1.json",
    "dataset-splits@1.json",
    "dataset-item-summary-list@1.json",
    "dataset-sample@1.json",
    "dataset-sync-report@1.json",
    "dataset-item-list@1.json",
)
SCHEMAS_OUT = REPO_ROOT / "tests" / "fixtures" / "toolbox-schemas"
PUBLISHED_SCHEMA_URL = (
    "https://raw.githubusercontent.com/A11yDevs/acessilia-toolbox/{ref}/schemas/{name}"
)

COMMENT = (
    "Toolbox capability/provider contract captured from a running toolbox. "
    "Regenerate with scripts/capture_toolbox_contract.py. Only the fields the "
    "core's contract checker reads are kept, so the fixture stays stable."
)


def _fetch_bytes(url: str, *, authenticated: bool = False) -> bytes:
    request = urllib.request.Request(url)
    api_key = os.getenv("TOOLBOX_API_KEY", "")
    if authenticated and api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SystemExit(f"cannot reach the Toolbox at {url}: {exc}")


def _fetch(url: str) -> object:
    return json.loads(_fetch_bytes(url, authenticated=True))


def _output(entry: dict) -> dict:
    """The output schema the SDK binding generator reads, as published.

    ``scripts/generate_sdk_bindings.py`` takes each selected capability's
    output schema from here (#213). Copied as it is, missing or not.
    """
    output = entry.get("output")
    if isinstance(output, dict) and "schema" in output:
        return {"output": {"schema": output["schema"]}}
    return {}


def _execution(entry: dict) -> dict:
    """The execution flags the checker reads, as published.

    The static contract and the catalogue publish ``execution.idempotent``
    (acessilia-toolbox#142). The value is copied as it is, missing or not, so
    the checker sees what the Toolbox published instead of a default.
    """
    execution = entry.get("execution")
    if isinstance(execution, dict) and "idempotent" in execution:
        return {"execution": {"idempotent": execution["idempotent"]}}
    return {}


def _normalize(capabilities: list, providers: list) -> dict:
    """Only the fields the checker and the SDK binding generator read, sorted
    so repeated captures of the same state produce identical files no matter
    which path produced them."""
    return {
        # One entry per published version, as /v1/capabilities lists them: the
        # core checks the exact contract version it was written against.
        "capabilities": [
            {
                "id": entry["id"],
                "version": entry.get("version", 1),
                "providers": sorted(entry.get("providers") or []),
                **_output(entry),
                **_execution(entry),
            }
            for entry in sorted(
                capabilities, key=lambda item: (item["id"], item.get("version", 1))
            )
        ],
        "providers": [
            {"id": entry["id"], "capabilities": sorted(entry.get("capabilities") or [])}
            for entry in sorted(providers, key=lambda item: item["id"])
        ],
    }


def build(url: str) -> dict:
    base = url.rstrip("/")
    capabilities = _fetch(f"{base}/v1/capabilities")
    providers = _fetch(f"{base}/v1/providers")

    return {"_comment": COMMENT, **_normalize(capabilities, providers)}


def snapshot(ref: str) -> dict[str, bytes]:
    """Download and validate every input before changing any local file."""
    if not re.fullmatch(r"[0-9a-f]{40}", ref):
        raise ValueError("--ref must be an immutable 40-character lowercase commit SHA")
    files = {"toolbox-contract.json": _fetch_bytes(PUBLISHED_URL.format(ref=ref))}
    contract = json.loads(files["toolbox-contract.json"])
    if not isinstance(contract, dict):
        raise ValueError(f"the Toolbox contract at {ref} must be a JSON object")
    for key in ("capabilities", "providers", "dataset_routes", "schema_refs"):
        if not isinstance(contract.get(key), list):
            raise ValueError(f"the Toolbox contract at {ref} is missing {key}")
    for name in SDK_MODEL_SCHEMAS:
        raw = _fetch_bytes(PUBLISHED_SCHEMA_URL.format(ref=ref, name=name))
        schema = json.loads(raw)
        if not isinstance(schema, dict) or not schema.get("$id"):
            raise ValueError(f"the Toolbox schema {name} at {ref} is malformed")
        files[f"toolbox-schemas/{name}"] = raw
    manifest = {
        "repository": "A11yDevs/acessilia-toolbox",
        "commit": ref,
        "sha256": {
            name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(files.items())
        },
    }
    files["toolbox-snapshot.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    return files


def write_snapshot(ref: str, out: Path) -> None:
    if out.name in {"toolbox-snapshot.json", "toolbox-schemas"}:
        raise ValueError("--out conflicts with a snapshot metadata path")
    files = snapshot(ref)
    if out.name != "toolbox-contract.json":
        manifest = json.loads(files["toolbox-snapshot.json"])
        digest = manifest["sha256"].pop("toolbox-contract.json")
        manifest["sha256"][out.name] = digest
        manifest["sha256"] = dict(sorted(manifest["sha256"].items()))
        files["toolbox-snapshot.json"] = (
            json.dumps(manifest, indent=2) + "\n"
        ).encode()
    out.parent.mkdir(parents=True, exist_ok=True)
    # Stage the complete validated download on the destination filesystem.
    # Network/parse failures leave every previous generation input untouched.
    with tempfile.TemporaryDirectory(dir=out.parent) as temporary:
        staging = Path(temporary)
        for name, raw in files.items():
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        for name in files:
            target = out if name == "toolbox-contract.json" else out.parent / name
            target.parent.mkdir(parents=True, exist_ok=True)
            (staging / name).replace(target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--ref", help="immutable Toolbox commit SHA")
    source.add_argument("--url", help="base URL of a running Toolbox")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    if args.ref:
        try:
            write_snapshot(args.ref, args.out)
        except (ValueError, TypeError) as exc:
            parser.error(str(exc))
    else:
        if args.out.resolve().is_relative_to(DEFAULT_OUT.parent.resolve()):
            parser.error("--url requires a diagnostic --out outside tests/fixtures")
        payload = build(args.url)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    if args.ref and args.out.resolve() == DEFAULT_OUT.resolve():
        # The core suite carries its own copy so it can run without the service
        # test tree; keep both snapshots in lockstep on every capture.
        CORE_OUT.parent.mkdir(parents=True, exist_ok=True)
        CORE_OUT.write_bytes(DEFAULT_OUT.read_bytes())
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
