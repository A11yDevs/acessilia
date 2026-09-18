#!/usr/bin/env python3
"""Build an overlay prediction dir: symlink every file of BASE, then override with the files of
OVERLAY (e.g. re-inferred rotated pages). Usage: overlay_predictions.py BASE OVERLAY OUT"""
import sys
from pathlib import Path

base, over, out = (Path(p).resolve() for p in sys.argv[1:4])
out.mkdir(parents=True, exist_ok=True)
stems = {p.name.split(".")[0] for p in over.glob("*.drbench.md")}
n_base = n_over = 0
for p in base.iterdir():
    if p.is_file() and p.name.split(".")[0] not in stems:
        (out / p.name).unlink(missing_ok=True); (out / p.name).symlink_to(p); n_base += 1
for p in over.iterdir():
    if p.is_file() and p.name.split(".")[0] in stems:
        (out / p.name).unlink(missing_ok=True); (out / p.name).symlink_to(p); n_over += 1
print(f"overlay {out}: {n_base} files from base, {n_over} files from overlay ({len(stems)} pages overridden)")
