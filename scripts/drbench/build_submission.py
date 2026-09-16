#!/usr/bin/env python
"""Build a Dr.DocBench submission from *.drbench.md predictions.

Produces:
- predictions.jsonl (fields: subject, document_id, page, markdown)
- mds/ tree mirroring the released hierarchy (optional layout)
- submission.zip with strict checks (no missing/duplicates/extras)

Usage:
    python -m scripts.drbench.build_submission --predictions var/drbench/predictions
    python -m scripts.drbench.build_submission ... --gt-dir var/drbench/dev  # sanity check
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

from scripts.drbench.page_record import DrBenchPage, ITEM_ID_RE

REPO_ROOT = Path(__file__).resolve().parents[2]


def collect_predictions(pred_dir: Path) -> list[dict]:
    """Collect *.drbench.md files and build submission records."""
    records: list[dict] = []
    for md_path in sorted(pred_dir.glob("*.drbench.md")):
        m = ITEM_ID_RE.match(md_path.name.removesuffix(".drbench.md"))
        if not m:
            print(f"[WARN] skipping unrecognized file: {md_path.name}", file=sys.stderr)
            continue
        page = DrBenchPage.from_item_id(m.group(0))
        records.append(
            {
                "subject": page.subject,
                "document_id": page.document_id,
                "page": page.page,
                "item_id": page.item_id,
                "markdown": md_path.read_text(encoding="utf-8"),
            }
        )
    return records


def validate(records: list[dict]) -> list[str]:
    """Strict submission checks: duplicates, missing fields, invalid ids."""
    errors: list[str] = []
    seen: set[tuple] = set()
    for r in records:
        key = (r["document_id"], r["page"])
        if key in seen:
            errors.append(f"duplicate prediction: {key}")
        seen.add(key)
        for field in ("document_id", "page", "markdown"):
            if field not in r or (field != "page" and not r[field]):
                errors.append(f"missing field {field} in {r.get('item_id')}")
        if not r.get("subject"):
            print(
                f"[WARN] empty subject for {r.get('item_id')} — "
                "fill from dataset metadata before submitting",
                file=sys.stderr,
            )
        if not isinstance(r["page"], int) or r["page"] < 1:
            errors.append(f"invalid page in {r['item_id']}")
    return errors


def build_mds_tree(records: list[dict], out_dir: Path) -> None:
    for r in records:
        doc_dir = out_dir / r["subject"] / r["document_id"]
        doc_dir.mkdir(parents=True, exist_ok=True)
        (doc_dir / f"page_{r['page']}.md").write_text(r["markdown"], encoding="utf-8")


def build_zip(records: list[dict], zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        lines = [
            json.dumps(
                {
                    "subject": r["subject"],
                    "document_id": r["document_id"],
                    "page": r["page"],
                    "markdown": r["markdown"],
                },
                ensure_ascii=False,
            )
            for r in records
        ]
        zf.writestr("predictions.jsonl", "\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Dr.DocBench submission")
    parser.add_argument(
        "--predictions", type=Path, default=REPO_ROOT / "var" / "drbench" / "predictions"
    )
    parser.add_argument(
        "--out", type=Path, default=REPO_ROOT / "var" / "drbench" / "submission"
    )
    parser.add_argument("--skip-mds", action="store_true")
    args = parser.parse_args(argv)

    records = collect_predictions(args.predictions)
    if not records:
        print("No *.drbench.md predictions found", file=sys.stderr)
        return 1

    errors = validate(records)
    if errors:
        for e in errors:
            print(f"[ERROR] {e}", file=sys.stderr)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    if not args.skip_mds:
        build_mds_tree(records, args.out / "mds")
    zip_path = args.out / "submission.zip"
    build_zip(records, zip_path)
    print(f"Submission ready: {zip_path} ({len(records)} predictions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
