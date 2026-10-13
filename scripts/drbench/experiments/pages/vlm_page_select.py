#!/usr/bin/env python3
"""v26: page-level adjudication between the differ output (A) and the whole-page VLM OCR (B).

When the two provider trees disagree strongly on a page (ratio(Docling, MinerU) < --dm), the differ has little
to stand on; there we take the VLM page (its blocks reordered by A's matched order, page_fuse --mode order)
if it is longer than A and the generation finished. Dev-986: tune +0.11, hold +1.59 (LOOP.md #10).

  vlm_page_select.py --a A_DIR --vlm VLM_DIR --docling D --mineru M --out OUT [--dm 0.6]
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_fuse import fuse, norm  # noqa: E402
from rapidfuzz import fuzz  # noqa: E402


# VLM "no text on this page" commentary (blank / picture-only pages): dropped, never transcription
COMMENT = re.compile(r"^\(?\s*(there is no (visible )?(text|content)|no (visible )?text|there is nothing (to|visible)|"
                     r"there is no visible content|the image (provided )?(appears|contains|shows|displays)|"
                     r"this (image|page) (appears|contains|shows))", re.I)

COMMENT2 = re.compile(r"\b(nothing|no (visible )?(text|content))\b.{0,40}\btranscrib", re.I)


def strip_comment(t: str) -> str:
    return "\n\n\n\n\n".join(b for b in re.split(r"\n\s*\n", t) if b.strip() and not COMMENT.match(b.strip())
                          and not COMMENT2.search(b))


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", type=Path, required=True)
    ap.add_argument("--vlm", type=Path, required=True, help="vlm_page_ocr.py predictions dir (raw jsonl next to it)")
    ap.add_argument("--docling", type=Path, required=True)
    ap.add_argument("--mineru", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--dm", type=float, default=0.6)
    ap.add_argument("--ab", type=float, default=0.0,
                    help="also take the VLM page when it is not longer but agrees with A (ratio >= AB): same content, "
                         "VLM block structure (0 = off)")
    a = ap.parse_args()
    raw = a.vlm.parent / f"{a.vlm.name}-raw.jsonl"
    fin = {f"{r['doc']}_p{r['page']}": r["finish"] for r in map(json.loads, raw.open(encoding="utf-8"))}
    a.out.mkdir(parents=True, exist_ok=True)
    n = 0
    for pa in sorted(a.a.glob("*.drbench.md")):
        k = pa.name.split(".drbench")[0]
        ta, tv = read(pa), strip_comment(read(a.vlm / pa.name))
        out = ta
        if tv.strip() and fin.get(k) == "stop":
            tb = fuse(ta, tv, "order", 0.6)
            d, m = norm(read(a.docling / pa.name)), norm(read(a.mineru / pa.name))
            dm = fuzz.ratio(d, m) / 100 if d and m else 0.0
            na, nb = norm(ta), norm(tb)
            agree = a.ab > 0 and na and fuzz.ratio(na, norm(tv)) / 100 >= a.ab
            if dm < a.dm and (len(nb) > len(na) or agree):
                out, n = tb, n + 1
        (a.out / pa.name).write_text(out, encoding="utf-8")
    print(f"pages {len(list(a.a.glob('*.drbench.md')))}  VLM pages picked: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
