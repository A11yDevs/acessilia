#!/usr/bin/env python3
"""v28: page-level arbitration between A and the dots.ocr page (D), with the Qwen whole-page VLM (V) as referee.

When D agrees with V clearly better than A does (ratio(D, V) - ratio(A, V) > --th) and D's generation finished,
the page is taken from D (rendered with --hf-end: running header / page number last, as in the GT).
Dev-986 fastscore: th 0.05 -> tune +0.54, hold +0.93 (plateau 0.04..0.08; LOOP.md #21).

  dots_page_select.py --a A --dots D --vlm V --out OUT [--th 0.05]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_fuse import norm  # noqa: E402
from rapidfuzz import fuzz  # noqa: E402
from vlm_page_select import strip_comment  # noqa: E402


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", type=Path, required=True)
    ap.add_argument("--dots", type=Path, required=True, help="dots_page_ocr.py --hf-end predictions dir")
    ap.add_argument("--raw", type=Path, required=True, help="dots raw jsonl (finish reasons)")
    ap.add_argument("--vlm", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--th", type=float, default=0.05)
    a = ap.parse_args()
    fin = {f"{r['doc']}_p{r['page']}": r["finish"] for r in map(json.loads, a.raw.open(encoding="utf-8"))}
    a.out.mkdir(parents=True, exist_ok=True)
    n = 0
    for pa in sorted(a.a.glob("*.drbench.md")):
        k = pa.name.split(".drbench")[0]
        ta, td = read(pa), read(a.dots / pa.name)
        A, D, V = norm(ta), norm(td), norm(strip_comment(read(a.vlm / pa.name)))
        out = ta
        if fin.get(k) == "stop" and D and V:
            if fuzz.ratio(D, V) / 100 - (fuzz.ratio(A, V) / 100 if A else 0.0) > a.th:
                out, n = td, n + 1
        (a.out / pa.name).write_text(out, encoding="utf-8")
    print(f"pages {len(list(a.a.glob('*.drbench.md')))}  dots pages picked: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
