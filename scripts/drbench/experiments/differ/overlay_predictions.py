#!/usr/bin/env python3
"""Build an overlay prediction dir: symlink every file of BASE, then override with the files of
OVERLAY (e.g. re-inferred rotated pages). Usage: overlay_predictions.py BASE OVERLAY OUT [ORIENTATION_JSON]
With ORIENTATION_JSON (runs/orientation_*.json) pages whose angle != 0 are NOT overridden (the overlay
was inferred on unrotated images, the base already holds the rotated re-inference)."""
import json
import sys
from pathlib import Path

base, over, out = (Path(p).resolve() for p in sys.argv[1:4])
out.mkdir(parents=True, exist_ok=True)
stems = {p.name.split(".")[0] for p in over.glob("*.drbench.md")}
n_rot = 0
if len(sys.argv) > 4:
    orient = json.loads(Path(sys.argv[4]).read_text())
    rotated = {k for k, v in orient.items() if v.get("angle", 0) != 0}
    n_rot = len(stems & rotated)
    stems -= rotated
n_base = n_over = 0
for p in base.iterdir():
    if p.is_file() and p.name.split(".")[0] not in stems:
        (out / p.name).unlink(missing_ok=True); (out / p.name).symlink_to(p); n_base += 1
for p in over.iterdir():
    if p.is_file() and p.name.split(".")[0] in stems:
        (out / p.name).unlink(missing_ok=True); (out / p.name).symlink_to(p); n_over += 1
print(f"overlay {out}: {n_base} files from base, {n_over} files from overlay "
      f"({len(stems)} pages overridden, {n_rot} rotated pages kept from base)")
