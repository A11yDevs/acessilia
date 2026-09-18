#!/usr/bin/env python3
"""Build predictions.jsonl + submission.zip from *.drbench.md using the official
manifest (required_pages) for subject/document_id/page. Pages are 0-indexed."""
import argparse, json, sys, zipfile
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--predictions", type=Path, required=True)
ap.add_argument("--manifest", type=Path, required=True)
ap.add_argument("--out", type=Path, required=True)
a = ap.parse_args()

req = json.loads(a.manifest.read_text())["required_pages"]
rows, missing = [], []
for it in req:
    md = a.predictions / f"{it['document_id']}_p{it['page']}.drbench.md"
    if not md.exists():
        missing.append(md.name); continue
    rows.append({"subject": it["subject"], "document_id": it["document_id"],
                 "page": int(it["page"]), "markdown": md.read_text(encoding="utf-8")})
if missing:
    print(f"[ERROR] {len(missing)} required pages missing, e.g. {missing[:3]}", file=sys.stderr)
    sys.exit(1)
a.out.mkdir(parents=True, exist_ok=True)
zp = a.out / "submission.zip"
with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
    zf.writestr("predictions.jsonl", "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
print(f"Submission ready: {zp} ({len(rows)} predictions)")
