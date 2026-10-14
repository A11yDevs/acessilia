#!/usr/bin/env python3
"""Materialise page-region crops for the VLM adjudication queue.

Reads the queue JSONL produced by `tree_differ_v2 --dump-queue` (normalised [0,1] TOPLEFT boxes),
crops the union of the two candidate boxes (2% pad) from the page image
(data/hf/dev/<SUBJ>/<doc>/images/page_<n>.jpg) and writes a queue JSONL with a "crop" field.

Usage:
  python scripts/make_crops.py --queue runs/dev-full/adjudication-queue/queue.jsonl \
      --out runs/dev-full/adjudication-queue/queue_crops.jsonl \
      --crops runs/dev-full/adjudication-queue/crops
"""
import argparse
import json
import re
import sys
from pathlib import Path

from PIL import Image

DEV = Path(__file__).resolve().parent.parent / "data" / "hf" / "dev"
PAD = 0.02


def doc_dirs() -> dict[str, Path]:
    return {p.name: p for p in DEV.glob("*/*/") if (p / "images").is_dir()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--crops", type=Path, required=True)
    a = ap.parse_args()
    dirs = doc_dirs()
    a.crops.mkdir(parents=True, exist_ok=True)
    n_ok = n_skip = 0
    with a.queue.open(encoding="utf-8") as f, a.out.open("w", encoding="utf-8") as out:
        for line in f:
            r = json.loads(line)
            m = re.match(r"(.+)_p(\d+)$", r["page"])
            ddir = m and dirs.get(m.group(1))
            img_path = ddir and ddir / "images" / f"page_{int(m.group(2))}.jpg"
            boxes = [b for b in (r.get("box_d"), r.get("box_m")) if b]
            if not (img_path and img_path.exists() and boxes):
                n_skip += 1
                continue
            x0 = max(0.0, min(b[0] for b in boxes) - PAD)
            y0 = max(0.0, min(b[1] for b in boxes) - PAD)
            x1 = min(1.0, max(b[2] for b in boxes) + PAD)
            y1 = min(1.0, max(b[3] for b in boxes) + PAD)
            with Image.open(img_path) as im:
                W, H = im.size
                crop = im.crop((int(x0 * W), int(y0 * H), max(int(x1 * W), int(x0 * W) + 8),
                                max(int(y1 * H), int(y0 * H) + 8)))
                if max(crop.size) > 1568:  # keep VLM token cost bounded
                    s = 1568 / max(crop.size)
                    crop = crop.resize((max(8, int(crop.size[0] * s)), max(8, int(crop.size[1] * s))))
                cpath = a.crops / f"{r['page']}_{r['i']}_{r['j']}.jpg"
                crop.convert("RGB").save(cpath, quality=90)
            r["crop"] = str(cpath)
            out.write(json.dumps(r, ensure_ascii=False) + "\n")
            n_ok += 1
    print(f"crops: {n_ok} written, {n_skip} skipped (missing image/box) -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
