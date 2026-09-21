#!/usr/bin/env python3
"""Detect page orientation (0/90/270) for Dr.DocBench page images with RapidOCR (CPU).

Stage 1: text detection at 0 deg; if most text boxes are tall (h > 1.3 w) the page is a
90/270 candidate.  Stage 2: full OCR at 90 and 270 on a downscaled copy; the angle with the
larger sum(len(txt)*score) wins.  Writes JSON {item_id: {"angle": int, "tall_frac": float, ...}}
and, with --out-root, rotated copies <root>/<subject>/<id>/images/page_N.jpg (only rotated pages)
so pipeline.sbatch can re-infer them with IMAGES_ROOT=<root>.

Usage (inside Slurm):
  .venv-docling/bin/python scripts/orient_pages.py --images-root data/hf/dev --out runs/orientation_dev.json \
      --out-root data/rotated/dev [--workers 8] [--items runs/dev/subset_ids.txt]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import cv2
import numpy as np

_ENGINE = None


def engine():
    global _ENGINE
    if _ENGINE is None:
        from rapidocr import RapidOCR
        _ENGINE = RapidOCR()
    return _ENGINE


def item_id(img: Path) -> str:
    d = img.parent
    if d.name == "images":
        d = d.parent
    return f"{d.name}_p{img.stem.removeprefix('page_')}"


def downscale(img: np.ndarray, max_side: int = 1400) -> np.ndarray:
    h, w = img.shape[:2]
    s = max_side / max(h, w)
    return cv2.resize(img, (int(w * s), int(h * s))) if s < 1 else img


def rotate(img: np.ndarray, angle: int) -> np.ndarray:
    # angle = counter-clockwise rotation to apply so the page reads upright
    if angle == 90:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    if angle == 270:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if angle == 180:
        return cv2.rotate(img, cv2.ROTATE_180)
    return img


WORD = re.compile(r"[A-Za-z]{2,}")


def ocr_score(img: np.ndarray) -> tuple[float, int]:
    r = engine()(img, use_det=True, use_cls=False, use_rec=True)
    if r is None or r.txts is None:
        return 0.0, 0
    s = 0.0
    for t, c in zip(r.txts, r.scores):
        words = WORD.findall(t)
        s += sum(len(w) for w in words) * float(c)
    return s, len(r.txts)


def analyse(path: str, tall_thr: float) -> dict:
    img = cv2.imread(path)
    if img is None:
        return {"error": "unreadable"}
    small = downscale(img)
    det = engine()(small, use_det=True, use_cls=False, use_rec=False)
    boxes = det.boxes if det is not None and det.boxes is not None else []
    if len(boxes) == 0:
        return {"angle": 0, "n_boxes": 0, "tall_frac": 0.0}
    tall = 0
    for b in boxes:
        b = np.asarray(b)
        w = np.linalg.norm(b[1] - b[0]); h = np.linalg.norm(b[3] - b[0])
        if h > 1.3 * w:
            tall += 1
    tall_frac = tall / len(boxes)
    out = {"n_boxes": int(len(boxes)), "tall_frac": round(tall_frac, 3)}
    if tall_frac < tall_thr or len(boxes) < 3:
        out["angle"] = 0
        return out
    s90, n90 = ocr_score(rotate(small, 90))
    s270, n270 = ocr_score(rotate(small, 270))
    out.update({"score90": round(s90, 1), "score270": round(s270, 1)})
    out["angle"] = 90 if s90 >= s270 else 270
    return out


def work(args) -> tuple[str, str, dict]:
    path, tall_thr = args
    try:
        return path, item_id(Path(path)), analyse(path, tall_thr)
    except Exception as e:  # keep the batch going; page stays at angle 0
        return path, item_id(Path(path)), {"angle": 0, "error": repr(e)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images-root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--out-root", type=Path, help="write rotated copies here (mirrors <subject>/<id>/images/)")
    ap.add_argument("--items", type=Path, help="optional file with item ids to restrict to")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--tall-thr", type=float, default=0.6)
    a = ap.parse_args()
    want = set(a.items.read_text().split()) if a.items else None
    imgs = sorted(p for p in a.images_root.rglob("page_*.jpg") if want is None or item_id(p) in want)
    done = json.loads(a.out.read_text()) if a.out.exists() else {}
    todo = [p for p in imgs if item_id(p) not in done]
    print(f"images={len(imgs)} done={len(done)} todo={len(todo)}", flush=True)
    with ProcessPoolExecutor(a.workers) as ex:
        futs = [ex.submit(work, (str(p), a.tall_thr)) for p in todo]
        for k, f in enumerate(as_completed(futs), 1):
            path, iid, res = f.result()
            res["path"] = str(Path(path).relative_to(a.images_root))
            done[iid] = res
            if k % 25 == 0 or res.get("angle"):
                print(f"[{k}/{len(todo)}] {iid} {res}", flush=True)
                a.out.write_text(json.dumps(done, indent=1, sort_keys=True))
    a.out.write_text(json.dumps(done, indent=1, sort_keys=True))
    rot = {k: v for k, v in done.items() if v.get("angle")}
    print(f"rotated pages: {len(rot)} / {len(done)}")
    if a.out_root:
        for iid, v in rot.items():
            src = a.images_root / v["path"]
            dst = a.out_root / v["path"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(dst), rotate(cv2.imread(str(src)), v["angle"]))
        (a.out_root / "items.txt").write_text("\n".join(sorted(rot)) + "\n")
        print(f"rotated copies -> {a.out_root} (items.txt: {len(rot)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
