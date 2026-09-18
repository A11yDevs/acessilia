#!/usr/bin/env python
"""Rebuild toolbox manifests from MinerU `middle.json` files already on disk.

The toolbox keeps every MinerU job under repos/acessilia-toolbox/output/<job>/page_N/auto/
(middle.json + uploads/page_N.jpg). Job dirs carry no document id, so pages are mapped
back to dataset items by the sha256 of the uploaded image.

Run with the TOOLBOX venv (needs acessilia_toolbox):
  .venv/bin/python scripts/replay_mineru_manifests.py --images <root> [--images <root2>] \
      --out runs/dev/mineru-raw  [--ids runs/dev/subset_ids.txt]

Writes <item_id>.provider.json = {"document": {"elements": [...], "pages": [...]}}
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

TB_OUT = Path("/raid/user_marcospaulo/drdocbench/repos/acessilia-toolbox/output")


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def item_id_for(jpg: Path) -> str:
    doc_dir = jpg.parent
    if doc_dir.name == "images":
        doc_dir = doc_dir.parent
    return f"{doc_dir.name}_p{jpg.stem.split('_')[-1]}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", type=Path, action="append", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--ids", type=Path, help="restrict to these item ids (one per line)")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)

    from acessilia_toolbox.core.normalization.builder import _build_elements, _build_pages
    from acessilia_toolbox.providers.mineru_document import MineruDocument

    want = set(a.ids.read_text().split()) if a.ids else None
    by_hash: dict[str, str] = {}
    for root in a.images:
        for jpg in root.rglob("page_*.jpg"):
            iid = item_id_for(jpg)
            if want is None or iid in want:
                by_hash[sha(jpg)] = iid
    print(f"dataset images indexed: {len(by_hash)}", file=sys.stderr)

    done = missing = dup = 0
    seen: set[str] = set()
    for up in sorted(TB_OUT.glob("*/uploads/page_*.jpg")):
        iid = by_hash.get(sha(up))
        if iid is None:
            continue
        mid = next((up.parent.parent / up.stem / "auto").glob("*_middle.json"), None)
        if mid is None:
            missing += 1
            continue
        if iid in seen:
            dup += 1
            continue
        seen.add(iid)
        doc = MineruDocument(json.load(mid.open()))
        elements = _build_elements(doc)
        payload = {
            "document": {
                "elements": [e.model_dump(mode="json") for e in elements],
                "pages": [p.model_dump(mode="json") for p in _build_pages(doc, elements)],
            },
            "source_middle_json": str(mid),
        }
        (a.out / f"{iid}.provider.json").write_text(json.dumps(payload, ensure_ascii=False))
        done += 1
    print(f"manifests written: {done}  (missing middle.json: {missing}, duplicate jobs skipped: {dup})")
    if want:
        lost = sorted(want - seen)
        print(f"items without a MinerU job on disk: {len(lost)}")
        for x in lost[:10]:
            print("  ", x)
    return 0 if done else 1


if __name__ == "__main__":
    raise SystemExit(main())
