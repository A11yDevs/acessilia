#!/usr/bin/env python3
"""Post-filter VLM adjudications (vlm_adjudicate.py output) into safer subsets.

dev-986 (v18/v20, 2026-09-27): raw 1252 decisions = 77.5 (16 `replace` on <table> blocks
turned tables into plain text: TEDS 69.1->66.7, text -97 on those pages). Filtered:
  notab  = no replace/select across structural blocks (table/img/formula)      78.4
  tight  = notab + replace only if 0.6 <= len(transcription)/len(candidate) <= 1.6   78.5
  sel    = select_a/select_b/drop only (never inject VLM text)                  78.5
Writes <out-prefix>-{notab,tight,sel}.jsonl.
"""
import argparse
import json
import re
from collections import Counter
from pathlib import Path

STRUCT = ("<table", "<img", "$$", "![", "<eq")


def nrm(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def struct(md: str | None) -> bool:
    return (md or "").lstrip().startswith(STRUCT)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", type=Path, required=True)
    ap.add_argument("--decisions", type=Path, required=True)
    ap.add_argument("--out-prefix", type=Path, required=True)
    a = ap.parse_args()
    q = [json.loads(l) for l in a.queue.read_text(encoding="utf-8").splitlines() if l.strip()]
    key = {(r["page"], r["i"], r["j"]): r for r in q}
    d = [json.loads(l) for l in a.decisions.read_text(encoding="utf-8").splitlines() if l.strip()]
    out: dict[str, list] = {"notab": [], "tight": [], "sel": []}
    for x in d:
        r = key.get((x["page"], x["i"], x["j"]))
        if r is None:
            continue
        cands = [r.get("md_d"), r.get("md_m")]
        anystruct = any(struct(c) for c in cands if c)
        if x["action"] == "replace":
            if anystruct:
                continue
            out["notab"].append(x)
            cand = max((nrm(c) for c in cands if c), key=len, default="")
            rt = len(nrm(x.get("text"))) / max(1, len(cand))
            if 0.6 <= rt <= 1.6:
                out["tight"].append(x)
        else:
            if anystruct and x["action"].startswith("select") and struct(cands[0]) != struct(cands[1]):
                continue
            for k in out:
                out[k].append(x)
    for k, v in out.items():
        p = Path(f"{a.out_prefix}-{k}.jsonl")
        p.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in v), encoding="utf-8")
        print(f"{k}: {len(v)} {dict(Counter(x['action'] for x in v))} -> {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
