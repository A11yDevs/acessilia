#!/usr/bin/env python3
"""Calculate per-block oracle pairing between Docling and MinerU.

Computes the potential headroom (e.g. +7.25 pts on dev-986) and category loss breakdown
by selecting the best prediction (lowest edit distance relative to upper_len)
between Docling and MinerU for each ground-truth block.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import glob
import json
from pathlib import Path
import re
import statistics as st
import sys
from typing import Any

try:
    import Levenshtein
except ImportError:
    Levenshtein = None  # type: ignore


def norm(s: str | None) -> str:
    """Normalize whitespace for text matching."""
    return re.sub(r"\s+", "", s or "")


def compute_edit_dist(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if Levenshtein is not None:
        return Levenshtein.distance(s1, s2)
    # Pure Python fallback for environments without Levenshtein package
    if s1 == s2:
        return 0
    if not s1:
        return len(s2)
    if not s2:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1, 1):
        curr = [i] * (len(s2) + 1)
        for j, c2 in enumerate(s2, 1):
            curr[j] = prev[j - 1] if c1 == c2 else 1 + min(prev[j], curr[j - 1], prev[j - 1])
        prev = curr
    return prev[len(s2)]


def classify_block(x: dict[str, Any], cat: str = "?") -> str:
    """Classify a block evaluation result into a loss taxonomy bucket."""
    if x.get("gt_position") == [""]:
        return "extra_pred"
    if x.get("pred_position") == "":
        return f"unmatched_gt:{cat if cat in ('header', 'footer', 'page_number', 'title') else 'body'}"
    upper = x.get("upper_len") or max(len(x.get("norm_pred", "")), len(x.get("norm_gt", ""))) or 1
    edit = x.get("Edit_num", 0)
    e = edit / upper
    lg, lp = len(x.get("norm_gt", "")), len(x.get("norm_pred", ""))
    if e <= 0.02:
        return "matched:near_perfect"
    if e <= 0.15:
        return "matched:ocr_small"
    if lp > 1.5 * lg:
        return "matched:pred_longer(merge)"
    if lg > 1.5 * lp:
        return "matched:pred_shorter(split/trunc)"
    if e > 0.6:
        return "matched:wrong_pair"
    return "matched:ocr_heavy"


def load_category_index(root_path: Path) -> dict[str, list[tuple[str, str]]]:
    """Build a mapping from page image ID to (normalized text, category_type)."""
    cat_index: dict[str, list[tuple[str, str]]] = defaultdict(list)
    pattern = str(root_path / "data" / "hf" / "dev" / "*" / "*" / "json" / "*_page_*.json")
    for jp in glob.glob(pattern):
        try:
            with open(jp, encoding="utf-8") as f:
                j = json.load(f)
            j = j[0] if isinstance(j, list) and j else j
            if not isinstance(j, dict):
                continue
            pi = j.get("page_info", {})
            if "page_name" not in pi or "page_no" not in pi:
                continue
            img = f"{pi['page_name']}_page_{pi['page_no']}-{pi['page_no']}.jpg"
            for det in j.get("layout_dets") or []:
                t = norm(det.get("text"))
                if t:
                    cat_index[img].append((t, det.get("category_type", "?")))
        except Exception:
            continue
    return cat_index


def lookup_category(img: str, gt: str, cat_index: dict[str, list[tuple[str, str]]]) -> str:
    """Find the category for a ground-truth snippet."""
    g = norm(gt)[:30]
    for t, c in cat_index.get(img, []):
        if g and (g in t or t[:30] in g):
            return c
    return "?"


def evaluate_oracle_headroom(
    baseline_records: list[dict[str, Any]],
    docling_records: list[dict[str, Any]],
    mineru_records: list[dict[str, Any]],
    cat_index: dict[str, list[tuple[str, str]]] | None = None,
) -> dict[str, Any]:
    """Compute per-block oracle pairing between Docling and MinerU against a baseline."""
    cat_index = cat_index or {}

    # Group by img_id
    base_by_page: dict[str, list[dict]] = defaultdict(list)
    for x in baseline_records:
        base_by_page[x["img_id"]].append(x)

    doc_by_page: dict[str, dict[str, dict]] = defaultdict(dict)
    for x in docling_records:
        if x.get("gt_position") != [""]:
            doc_by_page[x["img_id"]][norm(x.get("gt", ""))] = x

    min_by_page: dict[str, dict[str, dict]] = defaultdict(dict)
    for x in mineru_records:
        if x.get("gt_position") != [""]:
            min_by_page[x["img_id"]][norm(x.get("gt", ""))] = x

    n_pages = len(base_by_page) or 1
    base_page_scores: list[float] = []
    oracle_page_scores: list[float] = []

    wins = Counter()
    loss_base = Counter()
    loss_oracle = Counter()

    for img_id, records in base_by_page.items():
        doc_cands = doc_by_page.get(img_id, {})
        min_cands = min_by_page.get(img_id, {})

        page_up_base = sum(x.get("upper_len", 0) for x in records)
        page_ed_base = sum(x.get("Edit_num", 0) for x in records)
        base_score = (1.0 - page_ed_base / page_up_base) if page_up_base else 1.0
        base_page_scores.append(base_score)

        page_ed_oracle = 0
        page_up_oracle = 0

        for x in records:
            cat = lookup_category(img_id, x.get("gt", ""), cat_index)
            k = classify_block(x, cat)

            # Extra predictions penalty
            if x.get("gt_position") == [""]:
                page_ed_oracle += x.get("Edit_num", 0)
                page_up_oracle += x.get("upper_len", 0)
                if page_up_base:
                    v = (x.get("Edit_num", 0) / page_up_base / n_pages) * 100.0
                    loss_base[k] += v
                    loss_oracle[k] += v
                continue

            gt_key = norm(x.get("gt", ""))
            cand_d = doc_cands.get(gt_key)
            cand_m = min_cands.get(gt_key)

            # Evaluate each provider
            candidates: list[tuple[str, int, int]] = []
            if cand_d and cand_d.get("pred_position") != "":
                ed_d = compute_edit_dist(cand_d.get("norm_pred", ""), cand_d.get("norm_gt", ""))
                up_d = max(len(cand_d.get("norm_pred", "")), len(cand_d.get("norm_gt", "")), 1)
                candidates.append(("docling", ed_d, up_d))

            if cand_m and cand_m.get("pred_position") != "":
                ed_m = compute_edit_dist(cand_m.get("norm_pred", ""), cand_m.get("norm_gt", ""))
                up_m = max(len(cand_m.get("norm_pred", "")), len(cand_m.get("norm_gt", "")), 1)
                candidates.append(("mineru", ed_m, up_m))

            # Current baseline
            ed_base = x.get("Edit_num", 0)
            up_base = x.get("upper_len", 1)

            best_provider = "baseline"
            best_ed = ed_base
            best_up = up_base
            best_ratio = ed_base / up_base if up_base else 1.0

            for prov, e, u in candidates:
                ratio = e / u if u else 1.0
                if ratio < best_ratio:
                    best_ratio = ratio
                    best_ed = e
                    best_up = u
                    best_provider = prov

            # Track winner stats between docling and mineru
            has_d = any(c[0] == "docling" for c in candidates)
            has_m = any(c[0] == "mineru" for c in candidates)
            if has_d and has_m:
                e_d = next(c[1] for c in candidates if c[0] == "docling")
                u_d = next(c[2] for c in candidates if c[0] == "docling")
                e_m = next(c[1] for c in candidates if c[0] == "mineru")
                u_m = next(c[2] for c in candidates if c[0] == "mineru")
                r_d = e_d / u_d
                r_m = e_m / u_m
                if abs(r_d - r_m) < 1e-4:
                    wins["tie"] += 1
                elif r_d < r_m:
                    wins["docling"] += 1
                else:
                    wins["mineru"] += 1
            elif has_d:
                wins["docling_only"] += 1
            elif has_m:
                wins["mineru_only"] += 1
            else:
                wins["neither"] += 1

            page_ed_oracle += best_ed
            page_up_oracle += best_up

            if page_up_base:
                loss_base[k] += (ed_base / page_up_base / n_pages) * 100.0
                loss_oracle[k] += (best_ed / page_up_base / n_pages) * 100.0

        orc_score = (1.0 - page_ed_oracle / page_up_oracle) if page_up_oracle else 1.0
        oracle_page_scores.append(orc_score)

    mean_base = st.mean(base_page_scores) * 100.0 if base_page_scores else 0.0
    mean_oracle = st.mean(oracle_page_scores) * 100.0 if oracle_page_scores else 0.0
    headroom = mean_oracle - mean_base

    return {
        "n_pages": n_pages,
        "baseline_text_score": mean_base,
        "oracle_text_score": mean_oracle,
        "headroom_pts": headroom,
        "provider_wins": dict(wins),
        "loss_baseline": dict(loss_base),
        "loss_oracle": dict(loss_oracle),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Calculate per-block oracle pairing between Docling and MinerU.")
    parser.add_argument("--root", type=Path, default=Path("/raid/user_marcospaulo/drdocbench"))
    parser.add_argument("--run", type=str, default="v3a-clean", help="Baseline run name")
    parser.add_argument("--docling-run", type=str, default="docling", help="Docling run name")
    parser.add_argument("--mineru-run", type=str, default="mineru", help="MinerU run name")
    parser.add_argument("--results-dir", type=Path, default=None, help="Optional direct path to result JSON directory")
    parser.add_argument("--out-json", type=Path, default=None, help="Path to save output JSON metrics")
    args = parser.parse_args()

    res_dir = args.results_dir or (args.root / "runs" / "dev-full" / "official" / "result")

    base_file = res_dir / f"{args.run}-w1-md2md_text_block_result.json"
    doc_file = res_dir / f"{args.docling_run}-w1-md2md_text_block_result.json"
    min_file = res_dir / f"{args.mineru_run}-w1-md2md_text_block_result.json"

    for p in (base_file, doc_file, min_file):
        if not p.exists():
            print(f"Error: results file not found: {p}", file=sys.stderr)
            return 1

    with base_file.open(encoding="utf-8") as f:
        base_records = json.load(f)
    with doc_file.open(encoding="utf-8") as f:
        doc_records = json.load(f)
    with min_file.open(encoding="utf-8") as f:
        min_records = json.load(f)

    cat_index = load_category_index(args.root)

    res = evaluate_oracle_headroom(base_records, doc_records, min_records, cat_index)

    print(f"\n================ Block Oracle Evaluation ================")
    print(f"Pages analyzed: {res['n_pages']}")
    print(f"Baseline Text Score: {res['baseline_text_score']:.2f}%")
    print(f"Oracle Text Score:   {res['oracle_text_score']:.2f}%")
    print(f"Headroom Gain:       +{res['headroom_pts']:.2f} pts\n")

    print("| Provider Selection | Count | Share |")
    print("|---|---|---|")
    total_pairs = sum(res["provider_wins"].values()) or 1
    for k, v in sorted(res["provider_wins"].items(), key=lambda t: -t[1]):
        print(f"| {k} | {v} | {100 * v / total_pairs:.1f}% |")

    print("\n| Category / Loss Bucket | Baseline Loss (pts) | Oracle Loss (pts) | Delta (pts recovered) |")
    print("|---|---|---|---|")
    all_buckets = sorted(set(res["loss_baseline"]) | set(res["loss_oracle"]))
    for b in all_buckets:
        lb = res["loss_baseline"].get(b, 0.0)
        lo = res["loss_oracle"].get(b, 0.0)
        print(f"| {b} | {lb:.2f} | {lo:.2f} | +{lb - lo:.2f} |")

    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        with args.out_json.open("w", encoding="utf-8") as f:
            json.dump(res, f, indent=2)
        print(f"\nSaved metrics to {args.out_json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
