"""Page-number vertical position per page (top|bot) from TeleOCR layout (normalised bboxes), dots.ocr category as
fallback.  usage: pnpos.py TELE_RAW DOTS_RAW OUT.json"""
import json, re, sys
sys.path.insert(0, "scripts")
from dots_page_ocr import parse
num = lambda s: re.fullmatch(r"[\divxlcIVXLC]{1,5}", (s or "").strip()) is not None
pos = {}
for r in map(json.loads, open(sys.argv[2], encoding="utf-8")):
    for e in parse(r["text"]):
        if e.get("category") in ("Page-header", "Page-footer") and num(e.get("text")):
            pos[f"{r['doc']}_p{r['page']}"] = "top" if e["category"] == "Page-header" else "bot"
for r in map(json.loads, open(sys.argv[1], encoding="utf-8")):
    for b in r["blocks"]:
        if b["type"] in ("header", "footer", "page_number") and num(b.get("text")):
            pos[f"{r['doc']}_p{r['page']}"] = "top" if (b["bbox"][1] + b["bbox"][3]) / 2 < 0.5 else "bot"
            break
json.dump(pos, open(sys.argv[3], "w"))
from collections import Counter; print(len(pos), Counter(pos.values()))
