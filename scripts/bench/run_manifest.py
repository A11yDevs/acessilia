"""Identity and durable status for a local benchmark run.

The current ``structure`` protocol measures the Toolbox structure capability,
canonical conversion and Markdown writing for one document page. It does not
claim to capture the Core's full pipeline.
"""

from __future__ import annotations

import errno
import hashlib
import importlib.metadata
import json
import mimetypes
import os
import platform
import subprocess
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from docstruct.evaluation.holdout import (
    LOOP_METRICS,
    MAX_METRIC_LOSS,
    MIN_HOLDOUT_GAIN,
    MIN_TUNE_GAIN,
)

from scripts.bench.datasets.base import BenchPage
from scripts.bench import toolbox

RUN_MANIFEST_FILE = "run-manifest.json"
RUN_MANIFEST_SCHEMA = "acessilia-benchmark-run"
RUN_MANIFEST_VERSION = 1
GATE_PROTOCOL = {
    "id": "docstruct.evaluation.holdout.improvement",
    "kind": "improvement",
    "version": 1,
    "metrics": list(LOOP_METRICS),
    "minimum_tune_gain": MIN_TUNE_GAIN,
    "minimum_holdout_gain": MIN_HOLDOUT_GAIN,
    "maximum_metric_loss": MAX_METRIC_LOSS,
    "cdm_in_gate": False,
}

STRUCTURE_PROTOCOL = {
    "id": "toolbox-structure",
    "version": 2,
    "unit": "document-page",
    "stages": [
        "document.structure.extract",
        "scripts.bench.core.payload_to_canonical",
        "docstruct.export.markdown.document_to_markdown",
    ],
    "outputs": [
        "benchmark-markdown@1",
        "toolbox-provider-blocks@1",
        "structured-document@1 (optional raw payload)",
    ],
    "input_representation": {
        "unit": "one dataset page image",
        "core_transform": "none",
        "crop": "not_applicable",
        "toolbox_internal_transform": "not_observed",
    },
    "excludes": [
        "planner",
        "executor",
        "visual enrichment",
        "remote formula conversion and verbalization",
        "final product exports",
    ],
    "telemetry": {
        "observed": [
            "caller-observed Toolbox call duration",
            "post-call input integrity check duration",
            "page wall duration including conversion and artifact writes",
            "provider-reported duration and cache hit when exposed by Toolbox",
        ],
        "not_observed": [
            "provider attempt and retry counts",
            "provider queue wait duration and cache lookup duration",
            "effective remote cache policy",
        ],
    },
}


class RunInUseError(RuntimeError):
    """Another process is running or scoring the same benchmark round."""


@contextmanager
def lock_run_directory(run_dir: Path):
    """Hold an exclusive lease over the manifest and its artifacts."""
    run_dir.mkdir(parents=True, exist_ok=True)
    # Keep the lock file in place so every process locks the same inode.
    # The OS releases the lock when the handle closes, including after a crash.
    with (run_dir / ".run.lock").open("a+b") as lock:
        try:
            if os.name == "nt":
                import msvcrt

                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if not isinstance(exc, BlockingIOError) and not (
                os.name == "nt" and exc.errno == errno.EACCES
            ):
                raise
            raise RunInUseError(f"Run is already in use: {run_dir}") from exc
        yield


def digest(value: object) -> str:
    """Stable SHA-256 for JSON-compatible identity values."""
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def is_pinned_revision(value: object) -> bool:
    """Accept only full Git/HuggingFace commit ids, never mutable branch names."""
    return (
        isinstance(value, str)
        and len(value) in {40, 64}
        and all(character in "0123456789abcdefABCDEF" for character in value)
    )


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def package_version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _available_cpu_count() -> int | None:
    try:
        return len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return os.cpu_count()


def _git(root: Path, *args: str) -> bytes | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=root, check=False, capture_output=True, timeout=5
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def source_identity() -> dict:
    """Core revision and a digest of relevant tracked and untracked source changes."""
    root = Path(__file__).resolve().parents[2]
    revision = _git(root, "rev-parse", "HEAD")
    status = _git(root, "status", "--porcelain", "--untracked-files=all") or b""
    diff = _git(root, "diff", "--binary", "HEAD") or b""
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z") or b""
    source_suffixes = {".py", ".toml", ".cfg", ".ini", ".md", ".sh", ".yml", ".yaml"}
    untracked_hashes = {}
    for raw_path in untracked.split(b"\0"):
        if not raw_path:
            continue
        path = root / os.fsdecode(raw_path)
        if path.suffix.lower() not in source_suffixes or "var" in path.relative_to(root).parts:
            continue
        try:
            if path.is_file():
                untracked_hashes[path.relative_to(root).as_posix()] = sha256_file(path)
        except OSError:
            untracked_hashes[path.relative_to(root).as_posix()] = "unreadable"
    return {
        "revision": revision.decode("ascii", errors="replace") if revision else None,
        "dirty": bool(status),
        "working_tree_sha256": digest({
            "status": status.decode("utf-8", errors="replace"),
            "diff_sha256": hashlib.sha256(diff).hexdigest(),
            "untracked_source_sha256": untracked_hashes,
        }),
    }


def software_identity() -> dict:
    return {
        "core": {"version": package_version("acessilia"), **source_identity()},
        "sdk": package_version("acessilia-sdk"),
        "docstruct": package_version("acessilia-docstruct"),
        # Provider and model versions, when present, are per-call provenance.
        "toolbox_release": "not_exposed_by_current_response",
    }


def _safe_endpoint(endpoint, *, include_port: bool = True) -> str:
    """Keep the endpoint origin while dropping credentials, paths and query data."""
    try:
        parts = urlsplit(str(getattr(endpoint, "base_url", endpoint)))
        host = parts.hostname
        if not host:
            return "unknown"
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        netloc = f"{host}:{parts.port}" if include_port and parts.port else host
        return urlunsplit((parts.scheme, netloc, "", "", ""))
    except ValueError:
        return "unknown"


def _endpoint_path_sha256(base_url: str) -> str:
    path = urlsplit(base_url).path
    # HTTPX appends a slash to a base URL before resolving relative requests.
    if not path.endswith("/"):
        path += "/"
    return hashlib.sha256(path.encode("utf-8")).hexdigest()


def toolbox_provenance_identity(provenance: object) -> dict[str, str | int]:
    """Extract only observed fields that identify the producer, independently of timing and cache."""
    if not isinstance(provenance, dict):
        return {}
    identity: dict[str, str | int] = {
        field: value for field in ("capability", "provider", "provider_version")
        if isinstance(value := provenance.get(field), str) and value.strip()
    }
    version = provenance.get("capability_version")
    if type(version) is int:
        identity["capability_version"] = version
    models = provenance.get("model_versions")
    if isinstance(models, dict):
        identity.update({
            f"model_versions.{name}": value for name, value in models.items()
            if isinstance(value, str) and value.strip()
        })
    return identity


def merge_toolbox_identity(
    observed: dict[str, str | int], incoming: dict[str, str | int]
) -> dict[str, str | int] | None:
    """Combine known fields, returning None if an observed value changes."""
    if any(field in observed and observed[field] != value for field, value in incoming.items()):
        return None
    return {**observed, **incoming}


def completed_toolbox_identity(items: dict) -> dict[str, str | int] | None:
    """Check the successful calls that produced the currently completed pages."""
    observed: dict[str, str | int] = {}
    for state in items.values():
        if state.get("status") != "completed":
            continue
        calls = state.get("observed_calls")
        if not isinstance(calls, list):
            continue
        call = next(
            (call for call in reversed(calls) if isinstance(call, dict) and call.get("status") == "completed"),
            {},
        )
        merged = merge_toolbox_identity(
            observed, toolbox_provenance_identity(call.get("toolbox_provenance"))
        )
        if merged is None:
            return None
        observed = merged
    return observed


def _dataset_revision(root: Path | None) -> str | None:
    if root is None:
        return None
    top = _git(root, "rev-parse", "--show-toplevel")
    revision = _git(root, "rev-parse", "HEAD")
    if not top or not revision:
        return None
    try:
        repository = Path(top.decode("utf-8")).resolve()
        dataset_root = root.resolve()
    except (OSError, ValueError):
        return None
    if dataset_root != repository:
        return None
    return revision.decode("ascii", errors="replace")


def selection_snapshot(pages: list[BenchPage]) -> dict:
    """Hash selected inputs and references without copying document content."""
    item_ids: set[str] = set()
    document_pages: set[tuple[str, int]] = set()
    items = []
    for page in pages:
        if (
            not isinstance(page.item_id, str)
            or not page.item_id
            or Path(page.item_id).name != page.item_id
            or "/" in page.item_id
            or "\\" in page.item_id
            or any(character in page.item_id for character in "\r\n\t")
            or page.item_id in {".", ".."}
        ):
            raise ValueError(f"invalid benchmark item id: {page.item_id!r}")
        if (
            not isinstance(page.document_id, str)
            or not page.document_id
            or not isinstance(page.page, int)
            or isinstance(page.page, bool)
            or page.page < 1
        ):
            raise ValueError(f"invalid document/page identity for item {page.item_id!r}")
        if page.item_id in item_ids:
            raise ValueError(f"duplicate benchmark item id: {page.item_id}")
        document_page = (page.document_id, page.page)
        if document_page in document_pages:
            raise ValueError(
                f"duplicate document/page selection: {page.document_id}_page_{page.page}"
            )
        if not page.image_path.is_file():
            raise ValueError(f"benchmark input is missing for item {page.item_id}")
        item_ids.add(page.item_id)
        document_pages.add(document_page)
        if page.gt_path is not None and not page.gt_path.is_file():
            raise ValueError(f"benchmark reference is missing for item {page.item_id}")
        input_type, _ = mimetypes.guess_type(page.image_path.name)
        reference_type = (
            mimetypes.guess_type(page.gt_path.name)[0] if page.gt_path is not None else None
        )
        items.append(
            {
                "item_id": page.item_id,
                "document_id": page.document_id,
                "page": page.page,
                "input_sha256": sha256_file(page.image_path),
                "input_representation": {
                    "media_type": input_type or "application/octet-stream",
                    "media_type_source": "filename_extension",
                    "size_bytes": page.image_path.stat().st_size,
                },
                "reference_sha256": sha256_file(page.gt_path) if page.gt_path else None,
                "reference_representation": (
                    {
                        "media_type": reference_type or "text/markdown",
                        "media_type_source": "filename_extension",
                        "size_bytes": page.gt_path.stat().st_size,
                    }
                    if page.gt_path is not None
                    else None
                ),
            }
        )
    items.sort(key=lambda item: item["item_id"])
    references = [
        {"item_id": item["item_id"], "sha256": item["reference_sha256"]}
        for item in items
    ]
    return {
        "count": len(items),
        "items": items,
        "sha256": digest(items),
        "references_sha256": digest(references),
    }


def build_run_manifest(
    *,
    dataset: str,
    split: str,
    run_name: str,
    pages: list[BenchPage],
    provider: str | None,
    save_raw: bool,
    root: Path | None,
    dataset_revision: str | None = None,
) -> dict:
    selection = selection_snapshot(pages)
    client_config = toolbox.client_config()
    effective_provider = provider or client_config.providers.get("toolbox_provider")
    slurm_toolbox = os.environ.get("BENCH_SLURM_TOOLBOX_SHA256")
    if slurm_toolbox:
        # Only the single loopback origin created by bench.sbatch gets a
        # job-independent port identity. Remote routes keep their full origin.
        if (
            len(slurm_toolbox) != 64
            or not is_pinned_revision(slurm_toolbox)
            or len(client_config.endpoints) != 1
            or _safe_endpoint(client_config.endpoints[0], include_port=False) != "http://localhost"
        ):
            raise ValueError("invalid Slurm Toolbox identity or endpoint")
    configuration = {
        "capability": "document.structure.extract",
        "language": "pt-BR",
        "provider": effective_provider or "sdk_default",
        "endpoints": [
            _safe_endpoint(endpoint, include_port=not slurm_toolbox)
            for endpoint in client_config.endpoints
        ],
        "endpoint_path_sha256": [
            _endpoint_path_sha256(endpoint.base_url) for endpoint in client_config.endpoints
        ],
        "timeout_seconds": client_config.timeouts.get(
            "toolbox_structure_timeout_seconds", client_config.timeout_seconds
        ),
        "retries": client_config.retries,
        "retry_backoff_seconds": client_config.retry_backoff_seconds,
        "raw_payload_saved": save_raw,
        "remote_cache_request": "toolbox_default",
        "remote_cache_policy": "not_exposed_by_toolbox",
        "worker_count": 1,
        "core_processing_configuration": {
            "applicable": False,
            "reason": "structure_protocol_does_not_run_the_core_pipeline",
        },
    }
    if slurm_toolbox:
        configuration["slurm_toolbox_sha256"] = slurm_toolbox
    software = software_identity()
    visible_devices = os.environ.get("CUDA_VISIBLE_DEVICES")
    hardware = {
        "platform": platform.system(),
        "machine": platform.machine(),
        "available_cpu_count": _available_cpu_count(),
        "gpu_visible": (
            None
            if visible_devices is None
            else bool(visible_devices.strip() not in {"", "-1"})
        ),
        "gpu_model": "not_observed",
    }
    if dataset_revision is not None:
        dataset_revision = dataset_revision.strip().lower()
        if not is_pinned_revision(dataset_revision):
            raise ValueError("dataset revision must be a full commit SHA")
    resolved_dataset_revision = dataset_revision or _dataset_revision(root)
    if dataset_revision is not None:
        dataset_revision_source = "explicit"
    elif resolved_dataset_revision is not None:
        dataset_revision_source = "git_checkout"
    else:
        dataset_revision_source = "unavailable"
    identity = {
        "schema_version": RUN_MANIFEST_VERSION,
        "dataset": dataset,
        "dataset_revision": resolved_dataset_revision,
        "dataset_revision_source": dataset_revision_source,
        "split": split,
        "protocol": STRUCTURE_PROTOCOL,
        "selection_sha256": selection["sha256"],
        "references_sha256": selection["references_sha256"],
        "configuration": configuration,
        "software": software,
        "hardware": hardware,
    }
    items = {
        item["item_id"]: {
            "status": "not_executed",
            "observed_call_count": 0,
            "observed_calls": [],
            "artifacts": {},
            "input_sha256": item["input_sha256"],
            "reference_sha256": item["reference_sha256"],
        }
        for item in selection["items"]
    }
    now = utc_now()
    return {
        "schema": RUN_MANIFEST_SCHEMA,
        "schema_version": RUN_MANIFEST_VERSION,
        "run_id": uuid4().hex,
        "run_name": run_name,
        "identity_sha256": digest(identity),
        "identity": identity,
        "dataset": {
            "name": dataset,
            "split": split,
            "revision": identity["dataset_revision"],
            "revision_source": dataset_revision_source,
        },
        "protocol": STRUCTURE_PROTOCOL,
        "selection": selection,
        "evaluation": {"gate": GATE_PROTOCOL, "gate_applied": False},
        "configuration": configuration,
        "software": software,
        "hardware": hardware,
        "status": "not_started",
        "created_at": now,
        "updated_at": now,
        "items": items,
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_text(path: Path, content: str) -> None:
    atomic_write_bytes(path, content.encode("utf-8"))


def atomic_write_json(path: Path, value: dict) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    atomic_write_text(path, payload)


def write_run_manifest(run_dir: Path, manifest: dict) -> None:
    manifest["updated_at"] = utc_now()
    atomic_write_json(run_dir / RUN_MANIFEST_FILE, manifest)


def load_run_manifest(run_dir: Path) -> dict | None:
    path = run_dir / RUN_MANIFEST_FILE
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} is not a run manifest object")
    if value.get("schema") != RUN_MANIFEST_SCHEMA:
        raise ValueError(f"{path} has an unknown schema")
    if value.get("schema_version") != RUN_MANIFEST_VERSION:
        raise ValueError(f"{path} has an unsupported schema version")
    identity = value.get("identity")
    identity_hash = value.get("identity_sha256")
    if not isinstance(identity, dict) or not isinstance(identity_hash, str):
        raise ValueError(f"{path} has no valid immutable identity")
    if digest(identity) != identity_hash:
        raise ValueError(f"{path} identity hash does not match")
    selection = value.get("selection")
    selection_items = selection.get("items") if isinstance(selection, dict) else None
    if not isinstance(selection_items, list):
        raise ValueError(f"{path} has no valid item selection")
    if digest(selection_items) != selection.get("sha256"):
        raise ValueError(f"{path} selection hash does not match")
    references = [
        {"item_id": item.get("item_id"), "sha256": item.get("reference_sha256")}
        for item in selection_items if isinstance(item, dict)
    ]
    if len(references) != len(selection_items):
        raise ValueError(f"{path} has an invalid item selection")
    if digest(references) != selection.get("references_sha256"):
        raise ValueError(f"{path} reference hash does not match")
    if (
        identity.get("selection_sha256") != selection.get("sha256")
        or identity.get("references_sha256") != selection.get("references_sha256")
        or identity.get("protocol") != value.get("protocol")
        or identity.get("configuration") != value.get("configuration")
        or identity.get("software") != value.get("software")
        or identity.get("hardware") != value.get("hardware")
    ):
        raise ValueError(f"{path} top-level identity fields do not match")
    dataset = value.get("dataset")
    if (
        not isinstance(dataset, dict)
        or identity.get("dataset") != dataset.get("name")
        or identity.get("dataset_revision") != dataset.get("revision")
        or identity.get("dataset_revision_source") != dataset.get("revision_source")
        or identity.get("split") != dataset.get("split")
    ):
        raise ValueError(f"{path} dataset identity fields do not match")
    item_states = value.get("items")
    selected_ids = [item.get("item_id") for item in selection_items if isinstance(item, dict)]
    if (
        not isinstance(item_states, dict)
        or any(not isinstance(item_id, str) for item_id in selected_ids)
        or len(selected_ids) != len(selection_items)
        or len(selected_ids) != len(set(selected_ids))
        or set(selected_ids) != set(item_states)
    ):
        raise ValueError(f"{path} item states do not match its selection")
    document_pages = set()
    valid_item_statuses = {
        "not_executed", "running", "completed", "failed", "cancelled",
        "legacy_unverified", "not_applicable", "absent",
    }
    for descriptor in selection_items:
        item_id = descriptor["item_id"]
        input_hash = descriptor.get("input_sha256")
        reference_hash = descriptor.get("reference_sha256")
        if (
            not item_id
            or Path(item_id).name != item_id
            or "/" in item_id
            or "\\" in item_id
            or not isinstance(descriptor.get("document_id"), str)
            or not descriptor.get("document_id")
            or not isinstance(descriptor.get("page"), int)
            or isinstance(descriptor.get("page"), bool)
            or descriptor["page"] < 1
            or not isinstance(input_hash, str)
            or len(input_hash) != 64
            or (reference_hash is not None and (not isinstance(reference_hash, str) or len(reference_hash) != 64))
        ):
            raise ValueError(f"{path} has an invalid page identity")
        document_page = (descriptor["document_id"], descriptor["page"])
        if document_page in document_pages:
            raise ValueError(f"{path} has duplicate document/page identities")
        document_pages.add(document_page)
        state = item_states[item_id]
        if (
            not isinstance(state, dict)
            or state.get("status") not in valid_item_statuses
            or state.get("input_sha256") != input_hash
            or state.get("reference_sha256") != reference_hash
        ):
            raise ValueError(f"{path} item state identity does not match the selection")
    if value.get("status") not in {
        "not_started", "running", "completed", "partial", "failed", "cancelled"
    }:
        raise ValueError(f"{path} has an unknown run status")
    return value


def completed_artifacts_are_valid(
    predictions: Path,
    item: dict,
    item_id: str,
    *,
    require_raw_payload: bool = False,
) -> bool:
    artifacts = item.get("artifacts")
    if item.get("status") != "completed" or not isinstance(artifacts, dict):
        return False
    expected_names = {
        "markdown": f"{item_id}.md",
        "blocks": f"{item_id}.blocks.json",
    }
    if require_raw_payload:
        expected_names["raw_payload"] = f"{item_id}.provider.json"
    required = set(expected_names)
    if not required.issubset(artifacts):
        return False
    if set(artifacts) - {"markdown", "blocks", "raw_payload"}:
        return False
    for key, artifact in artifacts.items():
        name = artifact.get("path") if isinstance(artifact, dict) else None
        expected = artifact.get("sha256") if isinstance(artifact, dict) else None
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or "/" in name
            or "\\" in name
            or (key in expected_names and name != expected_names[key])
            or not isinstance(expected, str)
            or len(expected) != 64
        ):
            return False
        path = predictions / name
        try:
            if (
                not path.is_file()
                or sha256_file(path) != expected
                or artifact.get("size_bytes") != path.stat().st_size
            ):
                return False
        except OSError:
            return False
    return True
