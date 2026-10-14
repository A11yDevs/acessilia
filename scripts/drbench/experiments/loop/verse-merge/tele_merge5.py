"""Merge consecutive Tele text blocks only when one V block contains both (V confirms they are one paragraph).
usage: tele_merge3.py OUT VDIR J RAW1 [RAW2 ...]"""
import json, re, sys
from pathlib import Path
sys.path.insert(0, "scripts")
import teleocr_page_ocr as T
TAG = re.compile(r"<[^>]+>|\$+|\\[a-z]+|[#*_`|]")
norm = lambda t: " ".join(re.sub(r"[^\w]+", " ", TAG.sub(" ", t).lower()).split())
from rapidfuzz import fuzz
out, V, J, TH = Path(sys.argv[1]), Path(sys.argv[2]), {"sp": " ", "nl": "\n"}[sys.argv[3]], float(sys.argv[4])
recs = {}
for f in sys.argv[5:]:
    for r in map(json.loads, open(f, encoding="utf-8")):
        recs[(r["doc"], r["page"])] = r
out.mkdir(parents=True, exist_ok=True)
nm = npg = 0
for (doc, pg), r in recs.items():
    vp = V / f"{doc}_p{pg}.drbench.md"
    vb = [f" {norm(b)} " for b in re.split(r"\n\s*\n", vp.read_text(encoding="utf-8"))] if vp.exists() else []
    mb, m0 = [], nm
    for b in r["blocks"]:
        t = (b.get("text") or "").strip()
        p = mb[-1] if mb else None
        if p is not None and b["type"] == "text" and p["type"] == "text" and t and len(norm(t)) >= 8:
            a, c = f" {norm(p['text'])} ", f" {norm(t)} "
            if len(a) >= 10 and any((a in x or fuzz.partial_ratio(a, x) >= TH) and (c in x or fuzz.partial_ratio(c, x) >= TH) for x in vb if len(x) >= len(a) + len(c) - 4):
                p["text"] = p["text"].strip() + J + t
                nm += 1
                continue
        mb.append(dict(b))
    npg += nm > m0
    (out / f"{doc}_p{pg}.drbench.md").write_text(T.render(mb), encoding="utf-8")
print("merged", nm, "on pages", npg, "of", len(recs))
