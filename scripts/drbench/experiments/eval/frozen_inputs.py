"""Freeze Git revisions and selected raw inputs before a paired replay.

Outputs belong in an external experiment directory, never in a source checkout.
Only committed source is exported; working-tree edits are not silently evaluated.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def resolve_path(base: Path, value: str) -> Path:
    return (base / value).resolve()


def validate_pages(pages: list[dict]) -> None:
    if not pages:
        raise ValueError("The selection contains no pages")
    ids = set()
    for page in pages:
        for field in ("id", "subject", "document_id"):
            value = page[field]
            if not value or value in (".", "..") or "/" in value or "\\" in value:
                raise ValueError(f"Invalid page field: {field}")
        if page["id"] != f"{page['document_id']}_p{page['page']}":
            raise ValueError("Page id does not match document/page")
        if page["id"] in ids:
            raise ValueError(f"Duplicate selected page: {page['id']}")
        ids.add(page["id"])
        if not isinstance(page["page"], int) or page["page"] < 1:
            raise ValueError("Page numbers must be positive integers")
        if not isinstance(page["batch"], int) or page["batch"] < 1:
            raise ValueError("Batch numbers must be positive integers")
        image = Path(page["image"])
        if image.is_absolute() or ".." in image.parts:
            raise ValueError("Images must be relative to data/hf")


def export_revision(repo: Path, ref: str, destination: Path) -> dict:
    commit = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "--verify", f"{ref}^{{commit}}"], text=True
    ).strip()
    archive = subprocess.check_output(["git", "-C", str(repo), "archive", commit])
    destination.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(destination, filter="data")
    return {
        "repository": str(repo), "requested_ref": ref, "commit": commit,
        "archive_sha256": hashlib.sha256(archive).hexdigest(),
        "working_tree_included": False,
    }


def freeze(spec_path: Path, output: Path, limit: int = 0) -> dict:
    spec_path = spec_path.resolve()
    spec = json.loads(spec_path.read_text())
    base = spec_path.parent
    data_root = resolve_path(base, spec["data_root"])
    pages_path = resolve_path(base, spec["pages"])
    pages = json.loads(pages_path.read_text())
    if limit < 0:
        raise ValueError("limit must be non-negative")
    if limit:
        pages = pages[:limit]
    validate_pages(pages)
    if set(spec["variants"]) != {"baseline", "candidate"}:
        raise ValueError("Exactly baseline and candidate are required")
    if any(not isinstance(v.get("docling_native_order", False), bool) for v in spec["variants"].values()):
        raise ValueError("docling_native_order must be a boolean")
    # A unique root prevents stale outputs from being interpreted as this run.
    output = output.resolve()
    for repo_spec in [spec["evaluator"]] + [
        variant[component]
        for variant in spec["variants"].values()
        for component in ("acessilia", "toolbox")
    ]:
        repo = resolve_path(base, repo_spec["repo"])
        if output.is_relative_to(repo):
            raise ValueError("Experiment output must be outside source repositories")
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "spec.json", spec)
    write_json(output / "pages.json", pages)
    manifest = {
        "status": "freezing", "selection_count": len(pages),
        "selected_documents": len({p["document_id"] for p in pages}),
        "selection_sha256": sha256(output / "pages.json"),
        "dataset": spec.get("dataset", {}), "seed": spec.get("seed"),
        "inference": spec.get("inference", {}), "variants": {}, "input_hashes": {},
    }
    write_json(output / "manifest.json", manifest)
    try:
        for page in pages:
            relative_paths = [
                Path("raw") / provider / f"{page['id']}.json"
                for provider in ("docling", "mineru")
            ] + [
                Path("data/hf") / page["image"],
                Path("data/hf/dev") / page["subject"] / page["document_id"]
                / "mds" / f"{page['document_id']}_{page['page']}.md",
            ]
            for relative in relative_paths:
                target = output / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((data_root / relative).read_bytes())
                manifest["input_hashes"][str(relative)] = sha256(target)
        for variant_name, variant in spec["variants"].items():
            frozen = {"policy": variant.get("policy", "v12"),
                      "fusion_args": variant.get("fusion_args", []),
                      "docling_native_order": variant.get("docling_native_order", False)}
            for component in ("acessilia", "toolbox"):
                source = variant[component]
                frozen[component] = export_revision(
                    resolve_path(base, source["repo"]), source["ref"],
                    output / "sources" / variant_name / component,
                )
            manifest["variants"][variant_name] = frozen
        evaluator = spec["evaluator"]
        manifest["evaluator"] = export_revision(
            resolve_path(base, evaluator["repo"]), evaluator["ref"],
            output / "sources/evaluator",
        )
        sources = {str(p.relative_to(output)): sha256(p)
                   for p in sorted((output / "sources").rglob("*")) if p.is_file()}
        write_json(output / "source-hashes.json", sources)
        manifest["source_hashes_sha256"] = sha256(output / "source-hashes.json")
        # Preserve extraction options/locks as evidence, not verified model identity.
        evidence = output / "evidence"
        evidence.mkdir()
        for index, name in enumerate(spec.get("evidence_files", [])):
            source = resolve_path(base, name)
            target = evidence / f"{index:02d}-{source.name}"
            target.write_bytes(source.read_bytes())
            manifest["input_hashes"][str(target.relative_to(output))] = sha256(target)
        manifest["status"] = "frozen"
    except Exception as exc:
        manifest["status"] = "freeze_failed"
        manifest["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        write_json(output / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    manifest = freeze(args.spec, args.out, args.limit)
    print(f"Frozen {manifest['selection_count']} pages at {args.out}")


if __name__ == "__main__":
    main()
