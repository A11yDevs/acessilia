#!/usr/bin/env python
"""Bulk-download Dr.DocBench ground truth (and page images).

Strategy:
1. Try the Toolbox dataset (``dr-docbench``) for page images and GT markdown.
2. The Toolbox currently mirrors only page images, so ground-truth markdown is
   fetched straight from the HuggingFace dataset
   (2077AIDataFoundation/DrDocBench, dev/<subject>/<doc>/mds/*.md).

Saves everything mirroring the released hierarchy:

    var/drbench/<split>/<subject>/<document_id>/mds/<document_id>_<page>.md
    var/drbench/<split>/<subject>/<document_id>/images/page_<page>.jpg

Usage:
    python -m scripts.drbench.download_gt --split dev [--limit 50]
    python -m scripts.drbench.download_gt --split test   # images only
    python -m scripts.drbench.download_gt --split dev --md-source hf
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

HF_REPO = "2077AIDataFoundation/DrDocBench"

from backend.tools.logger import logger  # noqa: E402
from backend.tools.toolbox_dataset_tools import (  # noqa: E402
    toolbox_get_drbench_ground_truth,
    toolbox_get_drbench_item,
    toolbox_get_drbench_page_image,
    toolbox_list_drbench_items,
)


def _hf_download(repo_path: str, dest: Path) -> bool:
    """Download one file from the HF dataset into dest. Returns success."""
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("[ERROR] huggingface_hub not installed "
              "(pip install huggingface_hub)", file=sys.stderr)
        return False
    try:
        local = hf_hub_download(
            repo_id=HF_REPO, filename=repo_path, repo_type="dataset")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(Path(local).read_bytes())
        return True
    except Exception as e:  # noqa: BLE001 - report and continue
        print(f"[WARN] HF download failed for {repo_path}: {e}",
              file=sys.stderr)
        return False


def _hf_md_path(subject: str, document_id: str, page: int) -> str:
    return f"dev/{subject}/{document_id}/mds/{document_id}_{page}.md"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bulk-download Dr.DocBench GT")
    parser.add_argument("--split", default="dev", choices=["dev", "test"])
    parser.add_argument("--limit", type=int, default=None,
                        help="max items to download (default: all)")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--out-dir", type=Path,
                        default=REPO_ROOT / "var" / "drbench")
    parser.add_argument("--skip-images", action="store_true",
                        help="only download ground-truth markdown")
    parser.add_argument(
        "--md-source", choices=["auto", "toolbox", "hf"], default="auto",
        help="where to fetch ground-truth markdown from (default: auto = "
             "toolbox first, then HuggingFace)")
    args = parser.parse_args(argv)

    # Toolbox caps page size at 1000; page through the whole split.
    items: list[dict] = []
    page_size = 1000
    while True:
        batch = toolbox_list_drbench_items(
            args.split, limit=page_size, offset=args.offset + len(items))
        if not batch:
            break
        items.extend(batch)
        if args.limit and len(items) >= args.limit:
            items = items[:args.limit]
            break
        if len(batch) < page_size:
            break
    if not items:
        print(f"[ERROR] no items returned for split={args.split}. "
              "Is the Toolbox running (docker compose up, port 8002)?",
              file=sys.stderr)
        return 1

    print(f"Downloading {len(items)} items from split={args.split} ...")
    ok_md = ok_img = skip = fail = 0
    fail_md = 0
    for i, raw in enumerate(items, 1):
        item_id = raw.get("id") or raw.get("item_id")
        if not item_id:
            fail += 1
            continue
        meta = raw.get("metadata") or {}
        subject = meta.get("subject") or "UNKNOWN"
        document_id = meta.get("document_id") or item_id.rsplit("_p", 1)[0]
        page = meta.get("page")
        if page is None:
            try:
                page = int(item_id.rsplit("_p", 1)[1])
            except (IndexError, ValueError):
                page = 0

        base = args.out_dir / args.split / subject / document_id
        md_path = base / "mds" / f"{document_id}_{page}.md"
        img_path = base / "images" / f"page_{page}.jpg"

        if md_path.exists() and (args.skip_images or img_path.exists()):
            skip += 1
            continue

        # Ground truth via HF only needs list metadata; get_item is flaky
        # (intermittent "item not found") and unneeded when skipping images.
        if args.split == "dev" and args.skip_images:
            if not md_path.exists() and args.md_source in ("auto", "hf"):
                if _hf_download(
                        _hf_md_path(subject, document_id, page), md_path):
                    ok_md += 1
                else:
                    fail_md += 1
            continue

        item = toolbox_get_drbench_item(item_id, split=args.split)
        if item is None:
            fail += 1
            continue

        if args.split == "dev":
            md_ref = next((r for r in item.get("artifacts", [])
                           if str(r.get("path", "")).endswith(".md")), None)
            got_md = False
            if md_ref and not md_path.exists():
                data = toolbox_get_drbench_ground_truth(
                    item_id, md_ref["path"], split=args.split)
                if data:
                    md_path.parent.mkdir(parents=True, exist_ok=True)
                    md_path.write_bytes(data)
                    ok_md += 1
                    got_md = True
            if not got_md and not md_path.exists() and args.md_source in (
                    "auto", "hf"):
                if _hf_download(
                        _hf_md_path(subject, document_id, page), md_path):
                    ok_md += 1
                    got_md = True
            if not got_md:
                fail_md += 1

        if not args.skip_images:
            img_ref = next(
                (r for r in item.get("artifacts", [])
                 if str(r.get("media_type", "")).startswith("image/")),
                None)
            if img_ref and not img_path.exists():
                data = toolbox_get_drbench_page_image(
                    item_id, img_ref["path"], split=args.split)
                if data:
                    img_path.parent.mkdir(parents=True, exist_ok=True)
                    img_path.write_bytes(data)
                    ok_img += 1

        if i % 50 == 0:
            print(f"  ... {i}/{len(items)} (md={ok_md}, img={ok_img}, "
                  f"skip={skip}, fail={fail})")

    print(f"Done: md={ok_md}, img={ok_img}, skipped={skip}, failed={fail}")
    logger.info("download_gt finished: split={} md={} img={} fail={}",
                args.split, ok_md, ok_img, fail)
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
