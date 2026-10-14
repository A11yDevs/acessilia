"""Move running header / page-number blocks that sit inside the body to the tail (GT: they come last). A block
is moved when it is short and equals (normalised) the text of a TeleOCR header/footer/page_number element AND of a
dots.ocr Page-header/Page-footer element (both layouts agree).  usage: hfmove.py SRC OUT TELE_RAW DOTS_RAW [one|both]"""
import json, re, sys
from pathlib import Path
sys.path.insert(0, "scripts")
from dots_page_ocr import parse
src, out, need = Path(sys.argv[1]), Path(sys.argv[2]), (sys.argv[5] if len(sys.argv) > 5 else "both")
nz = lambda s: re.sub(r"[\W_]+", "", (s or "").lower())
T, D = {}, {}
for r in map(json.loads, open(sys.argv[3], encoding="utf-8")):
    T[f"{r['doc']}_p{r['page']}"] = {nz(b.get("text")) for b in r["blocks"] if b["type"] in ("header", "footer", "page_number")} - {""}
for r in map(json.loads, open(sys.argv[4], encoding="utf-8")):
    D[f"{r['doc']}_p{r['page']}"] = {nz(e.get("text")) for e in parse(r["text"]) if e.get("category") in ("Page-header", "Page-footer")} - {""}
out.mkdir(parents=True, exist_ok=True); n = 0
for p in src.glob("*.drbench.md"):
    k = p.name.split(".drbench")[0]
    bl = [b.strip("\n") for b in re.split(r"\n\s*\n", p.read_text(encoding="utf-8")) if b.strip()]
    t, d = T.get(k, set()), D.get(k, set())
    hf = (t & d) if need == "both" else (t | d)
    # leave the existing tail (trailing run of hf blocks) alone; move hf blocks found before it
    j = len(bl)
    while j > 0 and nz(bl[j - 1].lstrip("# ")) in hf: j -= 1
    mv = [i for i in range(j) if len(bl[i]) <= 80 and nz(bl[i].lstrip("# ")) in hf]
    if mv and len(bl) > len(mv):
        bl = [b for i, b in enumerate(bl) if i not in mv] + [bl[i] for i in mv]; n += 1
    (out / p.name).write_text("\n\n\n\n\n".join(bl) + "\n", encoding="utf-8")
print("moved on", n)
