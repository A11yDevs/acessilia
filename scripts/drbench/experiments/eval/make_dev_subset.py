#!/usr/bin/env python3
"""Stratified dev subset for Dr.DocBench (seed 13).

Reads data/hf/dev/<SUBJECT>/<uuid>/json/<uuid>_page_<N>.json (OmniDocJSON: a
list with one page dict holding `layout_dets` and `page_info.page_attribute`).
Writes runs/dev/subset.json, subset_ids.txt and a symlink tree
runs/dev/subset-images/<SUBJECT>/<uuid>/images/page_<N>.jpg.
"""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

WS = Path("/raid/user_marcospaulo/drdocbench")
QUOTAS = {"table": 40, "equation": 25, "multicol": 20, "special": 20, "plain": 15}
MAX_PER_DOC = 4
TARGET_TOTAL = 120
SEED = 13


def load_pages(dev_root: Path) -> list[dict]:
    pages = []
    for jp in sorted(dev_root.glob("*/*/json/*.json")):
        raw = json.loads(jp.read_text(encoding="utf-8"))
        if not raw:
            continue
        page = raw[0] if isinstance(raw, list) else raw
        dets = page.get("layout_dets") or []
        if not dets:
            continue
        info = page.get("page_info", {})
        attr = info.get("page_attribute", {})
        doc_dir = jp.parent.parent
        uuid = doc_dir.name
        subject = doc_dir.parent.name
        page_no = int(info.get("page_no") or jp.stem.rsplit("page_", 1)[-1])
        cats = Counter(str(d.get("category_type", "")) for d in dets if not d.get("ignore"))
        layout = str(attr.get("layout", ""))
        special = attr.get("special_issue") or []
        if isinstance(special, str):
            special = [special]
        strata = []
        if any(c.startswith("table") for c in cats):
            strata.append("table")
        if any(c.startswith("equation_isolated") for c in cats):
            strata.append("equation")
        if layout and layout != "single_column" and "column" in layout:
            strata.append("multicol")
        if special:
            strata.append("special")
        if not strata:
            strata.append("plain")
        img = doc_dir / "images" / f"page_{page_no}.jpg"
        if not img.exists():
            continue
        md = doc_dir / "mds" / f"{uuid}_page_{page_no}.md"
        if not md.exists():
            cands = list((doc_dir / "mds").glob(f"*{page_no}.md")) if (doc_dir / "mds").exists() else []
            md = cands[0] if cands else md
        pages.append({
            "id": f"{uuid}_p{page_no}", "subject": subject, "document_id": uuid, "page": page_no,
            "image_path": str(img), "json_path": str(jp), "md_path": str(md) if md.exists() else None,
            "strata": strata, "layout": layout, "special_issue": special, "n_blocks": len(dets),
            "categories": dict(cats),
        })
    return pages


def sample(pages: list[dict]) -> list[dict]:
    rng = random.Random(SEED)
    chosen: dict[str, dict] = {}
    per_doc: Counter = Counter()
    # scarce strata first; sort by document so we spread across docs
    for stratum in ["equation", "special", "multicol", "table", "plain"]:
        pool = [p for p in pages if stratum in p["strata"] and p["id"] not in chosen]
        rng.shuffle(pool)
        have = sum(1 for p in chosen.values() if stratum in p["strata"])
        need = QUOTAS[stratum] - have
        for p in pool:
            if need <= 0:
                break
            if per_doc[p["document_id"]] >= MAX_PER_DOC:
                continue
            chosen[p["id"]] = p
            per_doc[p["document_id"]] += 1
            need -= 1
    # top-up to TARGET_TOTAL: first under-quota strata (equation), then anything
    for stratum in ["equation", "table", "multicol", "special", "plain", None]:
        pool = [p for p in pages if p["id"] not in chosen and (stratum is None or stratum in p["strata"])]
        rng.shuffle(pool)
        for p in pool:
            if len(chosen) >= TARGET_TOTAL:
                break
            if per_doc[p["document_id"]] >= MAX_PER_DOC:
                continue
            chosen[p["id"]] = p
            per_doc[p["document_id"]] += 1
    return sorted(chosen.values(), key=lambda p: (p["subject"], p["document_id"], p["page"]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev-root", type=Path, default=WS / "data/hf/dev")
    ap.add_argument("--out-dir", type=Path, default=WS / "runs/dev")
    args = ap.parse_args()

    pages = load_pages(args.dev_root)
    print(f"dev pages with blocks: {len(pages)}; docs: {len({p['document_id'] for p in pages})}")
    print("population per stratum:", dict(Counter(s for p in pages for s in p["strata"])))
    subset = sample(pages)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "subset.json").write_text(json.dumps(subset, indent=1, ensure_ascii=False), encoding="utf-8")
    (args.out_dir / "subset_ids.txt").write_text("\n".join(p["id"] for p in subset) + "\n", encoding="utf-8")
    root = args.out_dir / "subset-images"
    for p in subset:
        d = root / p["subject"] / p["document_id"] / "images"
        d.mkdir(parents=True, exist_ok=True)
        link = d / f"page_{p['page']}.jpg"
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(p["image_path"])

    print(f"subset pages: {len(subset)}; docs: {len({p['document_id'] for p in subset})}; "
          f"subjects: {len({p['subject'] for p in subset})}")
    print("per stratum:", dict(Counter(s for p in subset for s in p["strata"])))
    print("per doc max:", max(Counter(p["document_id"] for p in subset).values()))
    print(f"wrote {args.out_dir}/subset.json, subset_ids.txt, {root}")


if __name__ == "__main__":
    main()
