"""Read and validate the Acessilia Dataset references contract.

The public readers accept either the current ``references/`` layout or the
legacy case folders. A present but invalid new manifest is always an error;
it must never be hidden by falling back to a legacy copy.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator

REPO = Path(__file__).resolve().parents[2]
LOCK_PATH = Path(__file__).with_name("dataset.lock.json")
with LOCK_PATH.open(encoding="utf-8") as _fh:
    _LOCK = json.load(_fh)

DATASET_REPOSITORY = _LOCK["repository"]
EXPECTED_DATASET_REVISION = _LOCK["revision"]
REFERENCES_SCHEMA_VERSION = _LOCK["references_schema_version"]
EXPECTED_REFERENCES_DIGEST = _LOCK["references_digest"]

TASK_JSON_SELECTORS = {
    "math_text_quality": ("rules", {"/text"}),
    "math_document_structure": ("rules", {"/structure"}),
    "math_formula_speech": ("items", {"/speech/formulas"}),
    "presentation_output_safety": ("items", {"/text/must_not_match"}),
    "presentation_structure": (
        "rules", {"/structure/slide_titles", "/structure/deck_title", "/structure/slide_count"}
    ),
    "presentation_degraded_run_behavior": ("rules", {"/degraded"}),
}


class DatasetReferenceError(ValueError):
    """The Dataset reference contract is missing, incompatible, or invalid."""


@dataclass(frozen=True)
class EvaluationSelection:
    """User-selected scope for a case evaluation."""

    tasks: tuple[str, ...] = ()
    pages: tuple[int, ...] = ()
    object_ids: tuple[str, ...] = ()

    @property
    def is_full_case(self) -> bool:
        return not (self.tasks or self.pages or self.object_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tasks": list(self.tasks),
            "pages": list(self.pages),
            "object_ids": list(self.object_ids),
            "full_case": self.is_full_case,
        }


def content_digest(paths: Iterable[Path]) -> str:
    """Hash named file contents for exported/non-Git dataset trees."""
    digest = hashlib.sha256()
    for path in sorted((Path(item) for item in paths), key=lambda item: item.as_posix()):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def dataset_dir(explicit: Path | None = None) -> Path:
    """Resolve an explicit path, environment path, or the checkout default."""
    return Path(explicit or os.environ.get("ACESSILIA_TEST_DATASET_DIR") or REPO / "tests" / "dataset")


def git_revision(root: Path) -> str | None:
    """Return a checkout revision when available; local exported trees are valid."""
    if not (root / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_file(root: Path, relative: str, field: str) -> Path:
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise DatasetReferenceError(f"{field} escapes the dataset root: {relative!r}") from exc
    if not path.is_file():
        raise DatasetReferenceError(f"required {field} is missing: {path}")
    return path


def _pointer(document: Any, pointer: str) -> Any:
    if not pointer.startswith("/"):
        raise DatasetReferenceError(f"invalid JSON pointer {pointer!r}")
    value = document
    for token in pointer[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict) and token in value:
            value = value[token]
        elif isinstance(value, list) and token.isdigit() and int(token) < len(value):
            value = value[int(token)]
        else:
            raise DatasetReferenceError(f"JSON pointer {pointer!r} does not resolve")
    return value


def _merge_pointer(target: dict[str, Any], pointer: str, value: Any) -> None:
    tokens = [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]
    current = target
    for token in tokens[:-1]:
        current = current.setdefault(token, {})
    current[tokens[-1]] = value


def _count_rules(value: Any) -> int:
    """Count selected rule records, not their individual JSON fields."""
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        if {"text", "level"}.issubset(value) or {"pattern", "level"}.issubset(value):
            return 1
        return sum(
            len(item) if isinstance(item, list) else 1
            for key, item in value.items()
            if key not in {"description", "why", "notes"}
        )
    return 1


@dataclass(frozen=True)
class DatasetReferences:
    root: Path
    input_id: str
    rows: tuple[dict[str, str], ...]
    digest: str
    revision: str | None
    schema_version: str

    def task_rows(self, task: str) -> tuple[dict[str, str], ...]:
        return tuple(row for row in self.rows if row["task"] == task)

    def metadata(self) -> dict[str, Any]:
        records_by_task: dict[str, list[dict[str, Any]]] = {}
        for row in self.rows:
            record = {
                "availability": row["availability"],
                "coverage_scope": row["coverage_scope"],
                "annotated_count": int(row["annotated_count"]),
                "eligible_count": int(row["eligible_count"]) if row["eligible_count"] else None,
                "coverage_unit": row["coverage_unit"],
                "review_state": row["review_state"],
                "annotation_revision": row["annotation_revision"] or None,
                "reference_type": row["reference_type"] or None,
                "format": row["format"] or None,
                "schema_version": row["schema_version"],
                "content_schema": row["content_schema"] or None,
                "file_path": row["file_path"] or None,
                "record_selector": row["record_selector"] or None,
                "provenance": row["provenance"],
                "notes": row["notes"],
            }
            records_by_task.setdefault(row["task"], []).append(record)
        tasks: dict[str, Any] = {}
        for task, records in records_by_task.items():
            task_metadata: dict[str, Any] = {"references": records}
            # Keep the legacy flat fields only when every record agrees. A
            # task with multiple reference files keeps each count, unit,
            # selector and provenance in `references` instead of silently
            # replacing one row with another or combining unlike counts.
            for field in records[0]:
                values = [record[field] for record in records]
                if all(value == values[0] for value in values[1:]):
                    task_metadata[field] = values[0]
            tasks[task] = task_metadata
        return {
            "repository": DATASET_REPOSITORY,
            "revision": self.revision,
            "references_digest": self.digest,
            "references_schema_version": self.schema_version,
            "input_id": self.input_id,
            "tasks": tasks,
        }

    def read_task(self, task: str, reference_type: str) -> tuple[list[dict[str, str]], dict[str, Any]]:
        """Load the selector-scoped records for one task.

        The return values are CSV rows and a JSON object. Unannotated task rows
        are valid and return empty collections while remaining visible in
        ``metadata()``.
        """
        task_rows = [r for r in self.task_rows(task) if r["reference_type"] == reference_type]
        if not task_rows:
            raise DatasetReferenceError(
                f"Dataset {self.input_id} has no {reference_type!r} reference for required task {task!r}"
            )
        csv_rows: list[dict[str, str]] = []
        json_value: dict[str, Any] = {}
        for row in task_rows:
            if row["availability"] == "unannotated":
                continue
            try:
                selector = json.loads(row["record_selector"])
            except json.JSONDecodeError as exc:
                raise DatasetReferenceError(
                    f"invalid record selector for Dataset task {row['task']!r}: {exc}"
                ) from exc
            if not isinstance(selector, dict):
                raise DatasetReferenceError(f"invalid record selector for Dataset task {task!r}")
            path = _safe_file(self.root, row["file_path"], "reference")
            schema_path = _safe_file(self.root, row["content_schema"], "reference schema")
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            try:
                Draft202012Validator.check_schema(schema)
            except Exception as exc:
                raise DatasetReferenceError(f"invalid content schema {schema_path}: {exc}") from exc
            if path.suffix.lower() == ".csv":
                with path.open(encoding="utf-8", newline="") as fh:
                    source_rows = list(csv.DictReader(fh))
                filters = selector.get("filters")
                if (
                    selector.get("type") != "csv_filter"
                    or selector.get("count_mode") != "rows"
                    or not isinstance(filters, dict)
                    or filters.get("manifest_id") != self.input_id
                ):
                    raise DatasetReferenceError(f"invalid CSV selector for {row['task']!r}")
                selected = [
                    item for item in source_rows
                    if all(item.get(key) == expected for key, expected in filters.items())
                ]
                validator = Draft202012Validator(schema)
                for item in selected:
                    try:
                        validator.validate(item)
                    except Exception as exc:
                        raise DatasetReferenceError(
                            f"invalid CSV reference row in {path}: {exc}"
                        ) from exc
                if len(selected) != int(row["annotated_count"]):
                    raise DatasetReferenceError(
                        f"reference count mismatch for {row['task']}: manifest says "
                        f"{row['annotated_count']}, selector found {len(selected)}"
                    )
                csv_rows.extend(selected)
            elif path.suffix.lower() == ".json":
                try:
                    Draft202012Validator.check_schema(schema)
                    document = json.loads(path.read_text(encoding="utf-8"))
                    Draft202012Validator(schema).validate(document)
                except Exception as exc:  # jsonschema exposes several validation exception types
                    raise DatasetReferenceError(f"invalid JSON reference {path}: {exc}") from exc
                pointers = selector.get("pointers")
                mode, allowed_pointers = TASK_JSON_SELECTORS.get(task, (None, set()))
                if (
                    selector.get("type") != "json_pointers"
                    or selector.get("count_mode") != mode
                    or not isinstance(pointers, list)
                    or not pointers
                    or any(not isinstance(pointer, str) or pointer not in allowed_pointers for pointer in pointers)
                    or len(pointers) != len(set(pointers))
                ):
                    raise DatasetReferenceError(f"invalid JSON selector for task {task!r}")
                count = 0
                for pointer in pointers:
                    selected = _pointer(document, pointer)
                    _merge_pointer(json_value, pointer, selected)
                    if mode == "rules":
                        count += _count_rules(selected)
                    elif isinstance(selected, list):
                        count += len(selected)
                    else:
                        raise DatasetReferenceError(f"selector {pointer!r} must identify a list")
                if count != int(row["annotated_count"]):
                    raise DatasetReferenceError(
                        f"reference count mismatch for {row['task']}: manifest says "
                        f"{row['annotated_count']}, selector found {count}"
                    )
            else:
                raise DatasetReferenceError(f"unsupported reference format {row['format']!r}")
        return csv_rows, json_value


def load_references(root: Path, input_id: str) -> DatasetReferences | None:
    """Load the new references contract, or return ``None`` for legacy layout.

    A references directory or an explicit input_path column declares the
    new layout, which requires its manifest.
    """
    root = Path(root).resolve()
    manifest_path = root / "references" / "manifest.csv"
    if not manifest_path.exists():
        if (root / "references").exists():
            raise DatasetReferenceError(f"references directory has no manifest: {manifest_path}")
        input_manifest = root / "input" / "manifest.csv"
        if input_manifest.is_file():
            with input_manifest.open(encoding="utf-8-sig", newline="") as stream:
                if "input_path" in next(csv.reader(stream), ()):
                    raise DatasetReferenceError(
                        f"input manifest declares input_path but references manifest is missing: {manifest_path}"
                    )
        return None
    schema_path = root / "references" / "manifest.schema.json"
    if not schema_path.is_file():
        raise DatasetReferenceError(f"references manifest schema is missing: {schema_path}")
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        with manifest_path.open(encoding="utf-8", newline="") as fh:
            all_rows = list(csv.DictReader(fh))
        validator = Draft202012Validator(schema)
        for row in all_rows:
            validator.validate(row)
            annotated = int(row["annotated_count"])
            eligible = int(row["eligible_count"]) if row["eligible_count"] else None
            if (eligible is not None and eligible < annotated) or (
                row["availability"] == "complete" and eligible != annotated
            ):
                raise ValueError(
                    f"inconsistent coverage for input {row['input_id']} task {row['task']!r}: "
                    f"{annotated} annotated, {eligible} eligible"
                )
    except Exception as exc:
        raise DatasetReferenceError(f"invalid Dataset references manifest {manifest_path}: {exc}") from exc
    version = schema.get("x-manifest-schema-version")
    if version != REFERENCES_SCHEMA_VERSION:
        raise DatasetReferenceError(
            f"unsupported references schema {version!r}; expected {REFERENCES_SCHEMA_VERSION!r}"
        )
    rows = tuple(row for row in all_rows if row["input_id"] == input_id)
    if not rows:
        raise DatasetReferenceError(f"references manifest has no rows for input {input_id}")
    if any(row["schema_version"] != version for row in rows):
        raise DatasetReferenceError(f"input {input_id} mixes unsupported reference schema versions")

    digest = hashlib.sha256()
    digest.update(manifest_path.read_bytes())
    digest.update(schema_path.read_bytes())
    for row in rows:
        if row["availability"] == "unannotated":
            continue
        for field in ("content_schema", "file_path"):
            path = _safe_file(root, row[field], field)
            digest.update(row[field].encode("utf-8"))
            digest.update(path.read_bytes())
    return DatasetReferences(
        root=root,
        input_id=input_id,
        rows=rows,
        digest=digest.hexdigest(),
        revision=git_revision(root),
        schema_version=version,
    )


def assert_pinned_dataset(root: Path, input_ids: Iterable[str] = ("036", "006")) -> dict[str, Any]:
    """Verify a CI fixture checkout or an exported tree against the lockfile."""
    actual_revision = git_revision(Path(root))
    if actual_revision is not None and actual_revision != EXPECTED_DATASET_REVISION:
        raise DatasetReferenceError(
            f"Dataset revision mismatch at {root}: expected {EXPECTED_DATASET_REVISION}, "
            f"found {actual_revision}"
        )
    identities = [load_references(Path(root), input_id) for input_id in input_ids]
    if any(identity is None for identity in identities):
        raise DatasetReferenceError(f"pinned Dataset at {root} has no references contract")
    digest = hashlib.sha256("".join(item.digest for item in identities if item).encode()).hexdigest()
    if digest != EXPECTED_REFERENCES_DIGEST:
        raise DatasetReferenceError(
            f"Dataset references digest mismatch at {root}: expected {EXPECTED_REFERENCES_DIGEST}, "
            f"found {digest}"
        )
    return {
        "repository": DATASET_REPOSITORY,
        "revision": actual_revision,
        "expected_revision": EXPECTED_DATASET_REVISION,
        "references_digest": digest,
        "references_schema_version": REFERENCES_SCHEMA_VERSION,
    }
