#!/usr/bin/env python3
"""Block-level text oracle on dev-986.

For each GT text block (data/hf/dev/<SUBJ>/<doc>/mds/<doc>_<n>.md), the best-matching block of each
provider run is scored with difflib ratio over normalised text. The block-level oracle picks, per GT
block, the better provider — the ceiling of any block-level selector over these two sources. We also
score the current differ output, so headroom = oracle - differ is what the VLM adjudicator could add.

Tables and formulas are excluded from the text oracle (separate metrics, always inherited from MinerU
in our merges); their GT counts are reported for sizing.

Usage:
  python scripts/block_oracle.py --docling runs/dev-full/docling+rot/predictions \
      --mineru runs/dev-full/mineru-hyb+rot/predictions --differ runs/dev-full/v16-hyb-rec300/predictions \
      --out runs/dev-full/block-oracle
"""
import argparse
import csv
import difflib
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tree_differ_v2 import split_blocks, norm  # noqa: E402

TABLE_RE = re.compile(r"<table", re.I)
FORMULA_RE = re.compile(r"\$\$|\\\[")
DEV = Path(__file__).resolve().parent.parent / "data" / "hf" / "dev"


def gt_index() -> dict[str, Path]:
    """prediction stem '<doc>_p<n>' -> GT md path '<doc>_<n>.md'."""
    idx = {}
    for p in DEV.glob("*/*/mds/*.md"):
        m = re.match(r"(.+)_(\d+)\.md$", p.name)
        if m:
            idx[f"{m.group(1)}_p{m.group(2)}"] = p
    return idx


def kind_of(block: str) -> str:
    if TABLE_RE.search(block):
        return "table"
    if FORMULA_RE.search(block):
        return "formula"
    return "text"


def best_score(g: str, pred_blocks: list[str], sm: difflib.SequenceMatcher) -> float:
    best = 0.0
    for p in pred_blocks:
        sm.set_seq2(p)
        if sm.real_quick_ratio() > best and sm.quick_ratio() > best:
            r = sm.ratio()
            if r > best:
                best = r
    return best


def page_scores(gt_blocks: list[str], pred_norm: dict[str, list[str]], sm) -> dict[str, float]:
    out = {}
    for name, blocks in pred_norm.items():
        vals = [best_score(g, blocks, sm) for g in gt_blocks]
        out[name] = sum(vals) / len(vals) if vals else float("nan")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docling", type=Path, required=True)
    ap.add_argument("--mineru", type=Path, required=True)
    ap.add_argument("--differ", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    runs = {"docling": a.docling, "mineru": a.mineru, "differ": a.differ}
    idx = gt_index()
    stems = sorted(set(idx) & {p.name[: -len(".drbench.md")] for p in a.docling.glob("*.drbench.md")}
                   & {p.name[: -len(".drbench.md")] for p in a.mineru.glob("*.drbench.md")})
    sm = difflib.SequenceMatcher()
    rows, agg, kind_tot = [], Counter(), Counter()
    for k, stem in enumerate(stems):
        gt_blocks = split_blocks(idx[stem].read_text(encoding="utf-8"))
        kinds = [kind_of(b) for b in gt_blocks]
        kind_tot.update(kinds)
        gt_text = [norm(b) for b, kd in zip(gt_blocks, kinds) if kd == "text" and len(norm(b)) >= 20]
        pred_norm = {}
        for name, d in runs.items():
            p = d / f"{stem}.drbench.md"
            pred_norm[name] = [norm(b) for b in split_blocks(p.read_text(encoding="utf-8"))] if p.exists() else []
        if not gt_text:
            continue
        sc = page_scores(gt_text, pred_norm, sm)
        oracle_vals, head = [], []
        for g in gt_text:
            sm.set_seq1(g)
            sd = best_score(g, pred_norm["docling"], sm)
            smn = best_score(g, pred_norm["mineru"], sm)
            sfd = best_score(g, pred_norm["differ"], sm)
            oracle_vals.append(max(sd, smn))
            head.append(max(sd, smn) - sfd)
        row = {"page": stem, "n_gt_text": len(gt_text),
               "docling": round(sc["docling"], 4), "mineru": round(sc["mineru"], 4),
               "differ": round(sc["differ"], 4),
               "oracle": round(sum(oracle_vals) / len(oracle_vals), 4),
               "headroom": round(sum(head) / len(head), 4)}
        rows.append(row)
        for key in ("docling", "mineru", "differ", "oracle", "headroom"):
            agg[key] += row[key]
        if (k + 1) % 200 == 0:
            print(f"[{k + 1}/{len(stems)}] oracle running mean = {agg['oracle'] / len(rows):.4f}", flush=True)
    n = len(rows)
    a.out.mkdir(parents=True, exist_ok=True)
    with (a.out / "per_page.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    top = sorted(rows, key=lambda r: -r["headroom"])[:20]
    lines = [
        "# Block-level text oracle (dev-986, md2md GT)",
        "",
        f"- pages scored: {n} (of {len(stems)}); GT block kinds: {dict(kind_tot)}",
        f"- mean per-page text score (0-1): docling {agg['docling'] / n:.4f} | mineru {agg['mineru'] / n:.4f} "
        f"| differ {agg['differ'] / n:.4f} | **oracle {agg['oracle'] / n:.4f}**",
        f"- **headroom (oracle - differ): {agg['headroom'] / n:.4f}** mean per page "
        f"(= points x100 a block-perfect selector would add to the text component)",
        f"- pages with headroom >= 0.05: {sum(1 for r in rows if r['headroom'] >= 0.05)} "
        f"({100 * sum(1 for r in rows if r['headroom'] >= 0.05) / n:.1f}%)",
        f"- pages where differ already at oracle (headroom < 0.005): {sum(1 for r in rows if r['headroom'] < 0.005)}",
        "",
        "## Top-20 pages by headroom",
        "",
        "| page | docling | mineru | differ | oracle | headroom |",
        "|---|---|---|---|---|---|",
    ] + [f"| {r['page']} | {r['docling']:.3f} | {r['mineru']:.3f} | {r['differ']:.3f} | {r['oracle']:.3f} "
         f"| {r['headroom']:.3f} |" for r in top]
    (a.out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:9]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
