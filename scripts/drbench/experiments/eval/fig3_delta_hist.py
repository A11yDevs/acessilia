#!/usr/bin/env python
"""Fig. 3: histogram of per-page overall delta (Docling force-OCR − MinerU)."""
import csv
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

WS = Path(__file__).resolve().parents[1]
src = WS / "runs/dev/delta_per_page.csv"
out = Path(sys.argv[1]) if len(sys.argv) > 1 else WS / "paper/figures/fig3_delta_hist.pdf"
out.parent.mkdir(parents=True, exist_ok=True)

rows = list(csv.DictReader(open(src)))
d = np.array([float(r["delta"]) for r in rows])
fig, ax = plt.subplots(figsize=(3.3, 2.2))
ax.hist(d, bins=np.arange(-60, 61, 5), color="#4C72B0", edgecolor="white")
ax.axvline(0, color="k", lw=0.8)
ax.axvline(np.median(d), color="#C44E52", lw=1, ls="--", label=f"median {np.median(d):.1f}")
ax.set_xlabel("Δ overall per page (Docling force-OCR − MinerU)")
ax.set_ylabel("pages")
ax.legend(frameon=False, fontsize=7)
ax.text(0.02, 0.95, f"N={len(d)}\nDocling wins {int((d>=0.5).sum())}, MinerU wins {int((d<=-0.5).sum())}",
        transform=ax.transAxes, va="top", fontsize=7)
fig.tight_layout()
fig.savefig(out)
print(out)
