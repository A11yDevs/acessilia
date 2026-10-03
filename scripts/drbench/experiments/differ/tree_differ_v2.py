#!/usr/bin/env python3
"""Tree Differ v2 (text + geometry): block-level merge of Docling and MinerU
outputs for the same page using the persisted ``<id>.blocks.json`` trees
(type, text, markdown, bbox, coord_origin, page_size) written by
``run_pipeline.py --save-raw`` / ``rerender_from_payloads.py``.

Matching: bipartite assignment (Hungarian) between Docling and MinerU blocks
with cost = (1-lambda)*(1-sim_txt) + lambda*(1-IoU); pairs with cost > tau are
unmatched. Boxes are normalised to the unit square (BOTTOMLEFT boxes are
y-flipped) so the two providers' page spaces are comparable.

Merge (MinerU reading order as skeleton):
  * matched pair: table -> --table-pref (or the only table); formula -> the
    formula side (--formula-pref if both); heading -> Docling heading with
    MinerU level fallback; text -> Docling text (better OCR) unless empty.
  * MinerU-only block: kept (tables, formulas, text).
  * Docling-only block: kept if it has >= --min-len chars or MinerU has no
    text at all (picture-only pages); inserted next to the geometrically
    nearest MinerU block (before it if above, after otherwise).
  * pictures never emit text; a MinerU picture bbox does not suppress
    Docling text (comics/speech bubbles are GT text).
Falls back to Differ-v1 behaviour (markdown split) when a page has no blocks.json.
"""
from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tree_differ_v1 import merge as merge_v1, norm, split_blocks  # noqa: E402

TABLE_RE = re.compile(r"<table", re.IGNORECASE)
FORMULA_RE = re.compile(r"\$\$")
# page number: short numeric / roman token, optional brackets, dashes, dots ("[ 102 ]", "- 7 -", "xii", "**1**")
PAGENUM_RE = re.compile(r"^[\W_]*(?:page\s*)?(\d{1,4}|[ivxlcdm]{1,7})[\W_]*$", re.IGNORECASE)
WORD_RE = re.compile(r"^[\W_]*(?:[A-Za-z\u00C0-\u024F]+(?:['\u2019\-][A-Za-z\u00C0-\u024F]+)*|\d+(?:[.,:/]\d+)*)[\W_]*$")
DECOR_TYPES = {"page_header": "header", "page_footer": "footer"}
DECOR_ORDER = {"header": 0, "footer": 1, "page_number": 2}
CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")
TRAIL_NUM_RE = re.compile(r"^(?:(.*?[A-Za-z].*?)\s+(\d{1,4})|(\d{1,4})\s+(.*?[A-Za-z].*?))$")


def quality(text: str) -> float:
    """Fraction of whitespace tokens that look like real words/numbers (OCR garbage scores low)."""
    toks = text.split()
    if not toks:
        return 0.0
    good = 0
    for t in toks:
        core = re.sub(r"[\W_]+", "", t)
        if WORD_RE.match(t) and (len(core) >= 2 or core.isdigit() or core.lower() in ("a", "i", "o", "e", "y", "à", "é")):
            good += 1
    return good / len(toks)


_LEXICON: set[str] | None = None
LEXICON_PATH = Path(__file__).resolve().parent.parent / "data" / "lexicon" / "words_alpha.txt"


def lexicon() -> set[str]:
    global _LEXICON
    if _LEXICON is None:
        _LEXICON = set()
        if LEXICON_PATH.exists():
            _LEXICON = {w.strip().lower() for w in LEXICON_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()}
    return _LEXICON


def lex_quality(text: str) -> float:
    """Fraction of alphabetic tokens (len>=3) found in the English lexicon; 1.0 when no such tokens.
    Catches misspelled OCR ('sympeomns', 'deciors') that `quality` accepts as word-like."""
    lex = lexicon()
    if not lex:
        return quality(text)
    toks = [t for t in re.findall(r"[A-Za-z]+", text) if len(t) >= 3]
    if not toks:
        return 1.0
    return sum(t.lower() in lex for t in toks) / len(toks)


def is_junk(text: str) -> bool:
    """Figure OCR residue: no real words, mostly digits/symbols, or a repeated character."""
    core = re.sub(r"\s+", "", text)
    if not core:
        return True
    if PAGENUM_RE.match(text):
        return False
    alnum = sum(c.isalnum() for c in core)
    if len(core) >= 8 and alnum / len(core) < 0.5:
        return True
    if len(set(core)) <= 2 and len(core) >= 4:
        return True
    if CJK_RE.search(core):  # corpus is English; CJK is figure-OCR noise
        return True
    return quality(text) < 0.34 and len(text.split()) >= 3


# display math worth keeping as a formula (CDM is scored only on real isolated equations; workout
# tables "1 3 5 \times 6" and chemistry "\mathsf{CH}_3" are text in the GT)
MATH_RE = re.compile(r"\\(frac|sum|int|sqrt|lim|partial|infty|prod|left|right|leq|geq|neq|approx|cdot|pm|alpha|beta|theta|pi|sigma|Delta)\b|[=<>]|\^\{?[a-zA-Z]")
LATEX_CMD_RE = re.compile(r"\\[A-Za-z]+\s*|[{}$^_]")


def latex_to_text(md: str) -> str:
    t = LATEX_CMD_RE.sub(" ", md)
    return re.sub(r"\s+", " ", t).strip()


def demote_formulas(blocks: list[dict], stats: Counter, tag: str) -> list[dict]:
    for b in blocks:
        if b["kind"] != "formula":
            continue
        txt = latex_to_text(b["md"])
        chem = re.fullmatch(r"[A-Z0-9\s=\-+()\[\].,]+", txt.replace("\\equiv", "=")) is not None  # CH3CH2C=N
        if txt and (chem or not MATH_RE.search(b["md"])):
            b["kind"], b["md"], b["text"] = "text", txt, norm(txt)
            stats[f"formula->text-{tag}"] += 1
    return blocks


def flood_guard(D: list[dict], M: list[dict], stats: Counter, ratio: float, min_blocks: int = 30,
                short: int = 15) -> list[dict]:
    """Chart/diagram pages: Docling emits every axis tick / label as a block (90 blocks) while MinerU sees
    the 5 captions. Drop short Docling text blocks without a lexicon word when Docling floods MinerU."""
    nd = sum(d["kind"] in ("text", "heading") for d in D)
    nm = sum(m["kind"] in ("text", "heading") for m in M)
    if nd < min_blocks or nd < ratio * max(nm, 1):
        return D
    lex = lexicon()
    keep = []
    for d in D:
        if d["kind"] == "text" and len(d["text"]) <= short and \
                not any(w.lower() in lex for w in re.findall(r"[A-Za-z]{3,}", d["md"])):
            stats["flood-docling-dropped"] += 1
        else:
            keep.append(d)
    if len(keep) < len(D):
        stats["flood-pages"] += 1
    return keep


def decor_role(b: dict, running: frozenset[str] = frozenset()) -> str | None:
    if b["kind"] in ("table", "formula"):
        return None
    if PAGENUM_RE.match(b["md"]) and len(b["md"]) <= 16:
        return "page_number"
    role = DECOR_TYPES.get(b["type"])
    if role is None and running and b["text"] in running and b["box"] is not None:
        cy = center(b["box"])[1]
        role = "header" if cy < 0.5 else "footer"
    return role


def doc_id_of(stem: str) -> str:
    return stem.rsplit("_p", 1)[0]


def running_texts(ids: list[str], docling: Path, mineru: Path, drop_d: frozenset, drop_m: frozenset,
                  min_pages: int = 3, max_len: int = 70, decor_share: float = 0.3) -> dict[str, frozenset[str]]:
    """Short texts that repeat near the top/bottom of >= min_pages pages of the same document are running
    headers/footers, even when the layout model labelled them as headings/paragraphs. Label propagation:
    the text must have been labelled page_header/page_footer in >= decor_share of its occurrences (so
    section headings that recur at the top, like "CHILE" / "ACROSS", stay body) and never appear mid-page."""
    per_doc: dict[str, Counter] = {}
    mid_doc: dict[str, Counter] = {}  # same text seen in the page body (label like "VHF") -> not a running head
    occ: dict[str, Counter] = {}; dec: dict[str, Counter] = {}
    for name in ids:
        stem = name.removesuffix(".drbench.md")
        seen: set[str] = set(); mid: set[str] = set()
        doc = doc_id_of(stem)
        occ.setdefault(doc, Counter()); dec.setdefault(doc, Counter())
        for path, drop in ((docling / f"{stem}.blocks.json", drop_d), (mineru / f"{stem}.blocks.json", drop_m)):
            for b in load_blocks(path, drop) or []:
                if b["kind"] in ("table", "formula") or b["box"] is None or not b["text"] or len(b["text"]) > max_len:
                    continue
                occ[doc][b["text"]] += 1
                if b["type"] in DECOR_TYPES:
                    dec[doc][b["text"]] += 1
                cy = center(b["box"])[1]
                if cy < 0.12 or cy > 0.88:
                    seen.add(b["text"])
                else:
                    mid.add(b["text"])
        per_doc.setdefault(doc, Counter()).update(seen)
        mid_doc.setdefault(doc, Counter()).update(mid)
    return {doc: frozenset(t for t, n in c.items() if n >= min_pages and len(t) >= 3 and not PAGENUM_RE.match(t)
                           and mid_doc[doc].get(t, 0) == 0 and dec[doc].get(t, 0) >= decor_share * occ[doc][t])
            for doc, c in per_doc.items()}


def load_blocks(path: Path, drop: frozenset[str] = frozenset(), pictures: list | None = None) -> list[dict] | None:
    if not path.exists():
        return None
    blocks = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for b in blocks:
        md = (b.get("markdown") or "").strip()
        t = (b.get("type") or "unknown").lower()
        bbox, size = b.get("bbox"), b.get("page_size") or [None, None]
        nb = None
        if bbox and all(v is not None for v in bbox) and size and all(size):
            w, h = float(size[0]), float(size[1])
            l, t0, r, b0 = (float(v) for v in bbox)
            if (b.get("coord_origin") or "").upper().startswith("BOTTOM"):
                t0, b0 = h - t0, h - b0
            y0, y1 = sorted((t0 / h, b0 / h))
            x0, x1 = sorted((l / w, r / w))
            nb = (max(0.0, x0), max(0.0, y0), min(1.0, x1), min(1.0, y1))
        if t == "picture":
            if pictures is not None and nb is not None:
                pictures.append(nb)
            continue
        if not md or t in drop:
            continue
        kind = "table" if t == "table" or TABLE_RE.search(md) else \
               "formula" if t == "formula" or FORMULA_RE.search(md) else \
               "heading" if t in ("heading", "title", "section_header") else "text"
        out.append({"md": md, "kind": kind, "box": nb, "text": norm(b.get("text") or md), "type": t})
    return out


def area(box) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1]) if box else 0.0


def contain_frac(inner, outer) -> float:
    """Fraction of `inner` area lying inside `outer`."""
    if inner is None or outer is None or area(inner) == 0:
        return 0.0
    ix = max(0.0, min(inner[2], outer[2]) - max(inner[0], outer[0]))
    iy = max(0.0, min(inner[3], outer[3]) - max(inner[1], outer[1]))
    return ix * iy / area(inner)


def union_box(boxes):
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def group_split_blocks(A: list[dict], B: list[dict], stats: Counter, tag: str, frac: float = 0.6,
                       min_sim: float = 0.0) -> list[dict]:
    """Merge text blocks of A that are geometrically contained (>= frac) in a single text block of B
    (A over-segmented the paragraph that B kept whole). Returns a new A list, order preserved."""
    owner: dict[int, int] = {}
    for i, a in enumerate(A):
        if a["kind"] != "text" or a["box"] is None:
            continue
        best, bf = None, 0.0
        for j, b in enumerate(B):
            if b["kind"] != "text" or b["box"] is None:
                continue
            f = contain_frac(a["box"], b["box"])
            if f > bf:
                best, bf = j, f
        if best is not None and bf >= frac:
            owner[i] = best
    groups: dict[int, list[int]] = {}
    for i, j in owner.items():
        groups.setdefault(j, []).append(i)
    merged_first: dict[int, dict] = {}
    absorbed: set[int] = set()
    for j, idxs in groups.items():
        if len(idxs) < 2:
            continue
        idxs.sort()
        parts = [A[i] for i in idxs]
        merged_text = "".join(p["text"] for p in parts)
        # the container must really be the same paragraph (not a garbage/table region swallowing a column)
        if sim(merged_text[:2000], B[j]["text"][:2000]) < min_sim:
            stats[f"merge-split-{tag}-rejected"] += 1
            continue
        merged_first[idxs[0]] = {
            "md": " ".join(p["md"] for p in parts), "kind": "text",
            "box": union_box(p["box"] for p in parts), "text": merged_text,
            "type": parts[0]["type"], "merged": len(parts),
        }
        absorbed.update(idxs[1:])
        stats[f"merge-split-{tag}"] += 1
        stats[f"merge-split-{tag}-blocks"] += len(parts)
    out = []
    for i, a in enumerate(A):
        if i in absorbed:
            continue
        out.append(merged_first.get(i, a))
    return out


def suppress_in_regions(D: list[dict], M: list[dict], m_pics: list, stats: Counter, frac: float = 0.75,
                        pic_min_blocks: int = 2, pic_max_quality: float = 0.7, pic_full_page: float = 0.9,
                        mode: str = "both", pic_rule: str = "count-or-quality",
                        table_full_page: float = 0.0, table_probe: bool = False) -> list[dict]:
    """Drop Docling text/heading blocks lying inside (>= frac) a MinerU table (its cells already carry the
    text) or inside a MinerU picture when the region looks like figure OCR (many low-quality fragments).
    Comics speech bubbles (few, word-like blocks) survive. table_full_page>0: a MinerU table covering that
    fraction of the page is treated as a mis-detected flyer/poster and does not suppress anything.
    table_probe: only suppress a block when a probe of its text occurs in the table's text (the table did
    capture it); text the table missed is kept."""
    tables = [(m["box"], m["text"]) for m in M if m["kind"] == "table" and m["box"]] if mode in ("both", "tables") else []
    if table_full_page:
        big = [tb for tb, _ in tables if area(tb) >= table_full_page]
        if big:
            stats["table-full-page-skipped"] += len(big)
        tables = [(tb, tt) for tb, tt in tables if area(tb) < table_full_page]

    def captured(t: str, table_text: str) -> bool:
        n = len(t)
        if n < 8:
            return True
        probes = {t[:10], t[max(0, n // 2 - 5):n // 2 + 5], t[-10:]}
        return any(p and p in table_text for p in probes)

    drop: set[int] = set()
    for i, d in enumerate(D):
        if d["kind"] not in ("text", "heading") or d["box"] is None:
            continue
        hit = [tt for tb, tt in tables if contain_frac(d["box"], tb) >= frac]
        if not hit:
            continue
        if table_probe and not any(captured(d["text"], tt) for tt in hit) \
                and min(quality(d["md"]), lex_quality(d["md"])) >= 0.5 \
                and len([t for t in re.findall(r"[A-Za-z]+", d["md"]) if len(t) >= 3]) >= 2:  # legible text the table missed
            stats["keep-in-table-missing"] += 1
            continue
        drop.add(i)
        stats["suppress-in-table"] += 1
    if mode not in ("both", "pictures"):
        return [d for i, d in enumerate(D) if i not in drop]
    for pb in m_pics:
        inside = [i for i, d in enumerate(D) if i not in drop and d["kind"] in ("text", "heading")
                  and d["box"] is not None and contain_frac(d["box"], pb) >= frac]
        if not inside:
            continue
        toks = sum(len(D[i]["md"].split()) for i in inside) or 1
        q = sum(min(quality(D[i]["md"]), lex_quality(D[i]["md"])) * len(D[i]["md"].split()) for i in inside) / toks
        full_page = area(pb) >= pic_full_page  # comics: the whole page is one picture and its text is GT
        if pic_rule == "quality":  # GT often keeps legible diagram labels; only drop garbage-ish regions
            hit = len(inside) >= pic_min_blocks and q < pic_max_quality
        else:
            hit = len(inside) >= pic_min_blocks or q < pic_max_quality
        if not full_page and hit:
            drop.update(inside)
            stats["suppress-in-picture"] += len(inside)
        elif full_page and q < 0.34:  # full-page picture but OCR is garbage
            drop.update(inside)
            stats["suppress-in-picture-garbage"] += len(inside)
        else:
            stats["keep-in-picture"] += len(inside)
    return [d for i, d in enumerate(D) if i not in drop]


def fuse_line_runs(blocks: list[dict], stats: Counter, tag: str, short: int = 80, min_run: int = 3,
                   max_len: int = 0, x_tol: float = 0.03, gap_mult: float = 1.3, h_ratio: float = 0.0) -> list[dict]:
    """Index / reference / name-list columns: GT keeps one block per column, providers emit one block per
    line. Fuse runs (>= min_run) of consecutive short text blocks that are left-aligned and vertically
    adjacent. max_len>0 caps the fused block length (evaluator forgives pred merges only up to 300 chars)."""
    def short_text(b):
        return (b["kind"] == "text" and b["box"] is not None and len(b["text"]) <= short
                and "\n" not in b["md"] and not b["md"].lstrip().startswith("#"))

    def adjacent(p, n):
        pb, nb = p["box"], n["box"]
        hp, hn = max(pb[3] - pb[1], 1e-3), max(nb[3] - nb[1], 1e-3)
        h = max(hp, hn)
        gap = nb[1] - pb[3]
        # a jump in line height = heading -> body transition (rose catalogue: title / spec / paragraph)
        return abs(pb[0] - nb[0]) <= x_tol and -0.5 * h <= gap <= gap_mult * h and min(hp, hn) / h >= h_ratio

    # cluster short blocks by left edge (columns), then chain them top-to-bottom (provider order is not
    # reliable: Docling emits index lines out of order)
    cand = [i for i, b in enumerate(blocks) if short_text(b)]
    cand.sort(key=lambda i: (blocks[i]["box"][0], blocks[i]["box"][1]))
    columns: list[list[int]] = []
    for i in cand:
        if columns and abs(blocks[columns[-1][0]]["box"][0] - blocks[i]["box"][0]) <= x_tol:
            columns[-1].append(i)
        else:
            columns.append([i])
    runs: list[list[int]] = []
    for col in columns:
        col.sort(key=lambda i: blocks[i]["box"][1])
        run = [col[0]]
        for i in col[1:]:
            if adjacent(blocks[run[-1]], blocks[i]):
                run.append(i)
            else:
                if len(run) >= min_run:
                    runs.append(run)
                run = [i]
        if len(run) >= min_run:
            runs.append(run)
    fused_at: dict[int, list[dict]] = {}
    absorbed: set[int] = set()
    for run in runs:
        chunk: list[int] = []
        chunks: list[list[int]] = []
        for i in run:
            if chunk and max_len and sum(len(blocks[c]["text"]) for c in chunk) + len(blocks[i]["text"]) > max_len:
                chunks.append(chunk); chunk = []
            chunk.append(i)
        chunks.append(chunk)
        for ch in chunks:
            if len(ch) == 1:
                continue
            parts = [blocks[i] for i in ch]
            fused_at.setdefault(min(ch), []).append(
                {"md": " ".join(p["md"] for p in parts), "kind": "text", "box": union_box(p["box"] for p in parts),
                 "text": "".join(p["text"] for p in parts), "type": parts[0]["type"], "fused": len(parts)})
            absorbed.update(ch)
            stats[f"fuse-lines-{tag}"] += 1
            stats[f"fuse-lines-{tag}-blocks"] += len(ch)
    out: list[dict] = []
    for i, b in enumerate(blocks):
        if i in fused_at:
            out.extend(fused_at[i])
        elif i not in absorbed:
            out.append(b)
    return out


def swallows(d: dict, others: list[dict], n: int = 30) -> bool:
    """True if the text of `d` also contains material from >=1 other block (probes of n chars): the
    provider read lines across columns / merged neighbouring paragraphs."""
    txt = d["text"]
    hits = 0
    for o in others:
        t = o["text"]
        if len(t) < n:
            continue
        probes = {t[k:k + n] for k in range(0, len(t) - n, max(n, (len(t) - n) // 4 or 1))}
        if sum(p in txt for p in probes) >= 2:
            hits += 1
            if hits >= 1:
                return True
    return False


def iou(a, b) -> float:
    if a is None or b is None:
        return 0.0
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def sim(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def center(box):
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2) if box else (0.5, 0.5)


def split_decor(blocks: list[dict], stats: Counter, tag: str,
                running: frozenset[str] = frozenset(), pagenum_cap: int = 0) -> tuple[list[dict], list[dict]]:
    body, decor = [], []
    demote: set[int] = set()
    if pagenum_cap:
        # clip / frame / item numbers ("425", "1851" in a videodisc index) match PAGENUM_RE too: when a page has
        # more numeric blocks than a page can have page numbers, only those in the margins are decor
        nums = [i for i, b in enumerate(blocks) if decor_role(b, running) == "page_number" and b["type"] not in DECOR_TYPES]
        if len(nums) > pagenum_cap:
            for i in nums:
                bx = blocks[i]["box"]
                cy = center(bx)[1] if bx else 0.5
                if 0.12 <= cy <= 0.88:
                    demote.add(i)
            stats[f"pagenum-{tag}-demoted"] += len(demote)
    for i, b in enumerate(blocks):
        role = None if i in demote else decor_role(b, running)
        if not role:
            body.append(b)
            continue
        if b["type"] not in DECOR_TYPES and role != "page_number":
            stats[f"decor-{tag}-running"] += 1
        # "Chapter 9: Photos & Art 159" -> footer + page_number (GT keeps them as separate blocks)
        m = TRAIL_NUM_RE.match(b["md"]) if role != "page_number" else None
        if m:
            txt, num = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
            decor.append({**b, "md": txt, "text": norm(txt), "role": role})
            decor.append({**b, "md": num, "text": norm(num), "role": "page_number"})
            stats[f"decor-{tag}-split-number"] += 1
        else:
            decor.append({**b, "role": role})
        stats[f"decor-{tag}-{role}"] += 1
    return body, decor


def decor_tail(dec_d: list[dict], dec_m: list[dict]) -> list[str]:
    """GT convention (mds/): header -> footer -> page_number after the body. Docling wins duplicates."""
    seen = {d["text"] for d in dec_d}
    items = list(dec_d) + [m for m in dec_m if m["text"] not in seen]
    items.sort(key=lambda b: (DECOR_ORDER[b["role"]], center(b["box"])[1], center(b["box"])[0]))
    return [b["md"] for b in items]


def merge_v2(D: list[dict], M: list[dict], *, lam: float, tau: float, min_len: int,
             table_pref: str, formula_pref: str, garbage_frac: float = 0.0,
             text_pick: str = "docling", decor: bool = False, junk: bool = False,
             merge_paragraphs: bool = False, merge_frac: float = 0.6, merge_min_sim: float = 0.0,
             m_pics: list | None = None, suppress: bool = False, pic_min_blocks: int = 2,
             pic_max_quality: float = 0.7, pic_full_page: float = 0.9,
             fuse_lines: bool = False, fuse_max_len: int = 0, fuse_short: int = 80,
             fuse_min_run: int = 3, merge_side: str = "both", pick_guard: float = 0.0,
             decor_wins: bool = False, running: frozenset[str] = frozenset(),
             suppress_mode: str = "both", pic_rule: str = "count-or-quality",
             table_full_page: float = 0.0, fuse_h_ratio: float = 0.0, table_probe: bool = False,
             pagenum_cap: int = 0, flood: float = 0.0, pic_need_text: bool = False,
             formula_text: bool = False) -> tuple[list[str], Counter]:
    stats: Counter = Counter()
    tail: list[str] = []
    if formula_text:
        D = demote_formulas(D, stats, "docling")
        M = demote_formulas(M, stats, "mineru")
    if suppress:
        mode = suppress_mode
        # MinerU saw only a picture: its picture box is the whole illustration and Docling's labels are the
        # only text we have (PETS breed labels, DK covers) -> do not suppress them
        if pic_need_text and mode in ("both", "pictures") and \
                sum(m["kind"] in ("text", "heading") for m in M) <= 1:
            stats["pic-suppress-skipped(mineru-no-text)"] += 1
            mode = "tables"
        D = suppress_in_regions(D, M, m_pics or [], stats, pic_min_blocks=pic_min_blocks,
                                pic_max_quality=pic_max_quality, pic_full_page=pic_full_page,
                                mode=mode, pic_rule=pic_rule, table_full_page=table_full_page,
                                table_probe=table_probe)
    if flood > 0:
        D = flood_guard(D, M, stats, flood)
    if decor:
        D, dec_d = split_decor(D, stats, "docling", running, pagenum_cap)
        M, dec_m = split_decor(M, stats, "mineru", running, pagenum_cap)
        # running header already emitted as a body heading by the other provider. GT (dev-986): header at
        # page end 390x vs at top 4x -> with decor_wins the body copy is dropped and the header goes to the tail
        body_txt = {b["text"] for b in D + M if b["text"]}
        kept = []
        for b in dec_d + dec_m:
            if b["role"] != "page_number" and b["text"] in body_txt and not decor_wins:
                stats["decor-dup-of-body"] += 1
            else:
                kept.append(b)
        if decor_wins:
            dec_txt = {b["text"] for b in kept if b["role"] != "page_number" and b["text"]}
            nD, nM = len(D), len(M)
            D = [b for b in D if not (b["kind"] in ("text", "heading") and b["text"] in dec_txt)]
            M = [b for b in M if not (b["kind"] in ("text", "heading") and b["text"] in dec_txt)]
            stats["body-dup-of-decor"] += (nD - len(D)) + (nM - len(M))
        dec_d = [b for b in kept if b in dec_d]
        dec_m = [b for b in kept if b in dec_m]
        tail = decor_tail(dec_d, dec_m)
    if junk:
        keep = []
        for d in D:
            if d["kind"] == "text" and is_junk(d["md"]):
                stats["junk-docling"] += 1
            else:
                keep.append(d)
        D = keep
        keep = []
        for m in M:
            if m["kind"] == "text" and is_junk(m["md"]):
                stats["junk-mineru"] += 1
            else:
                keep.append(m)
        M = keep
    if fuse_lines:  # before anti-split so that differing groupings get absorbed by containment
        D = fuse_line_runs(D, stats, "docling", short=fuse_short, min_run=fuse_min_run, max_len=fuse_max_len,
                           h_ratio=fuse_h_ratio)
        M = fuse_line_runs(M, stats, "mineru", short=fuse_short, min_run=fuse_min_run, max_len=fuse_max_len,
                           h_ratio=fuse_h_ratio)
    if merge_paragraphs:
        if merge_side in ("both", "docling"):
            D = group_split_blocks(D, M, stats, "docling", merge_frac, merge_min_sim)
        if merge_side in ("both", "mineru"):
            M = group_split_blocks(M, D, stats, "mineru", merge_frac, merge_min_sim)
    if not M:  # pictures are dropped in load_blocks -> nothing usable from MinerU
        stats["mineru_empty->docling"] += 1
        return [d["md"] for d in D] + tail, stats
    if not D:
        stats["docling_empty->mineru"] += 1
        return [m["md"] for m in M] + tail, stats

    cost = np.ones((len(D), len(M)))
    for i, d in enumerate(D):
        for j, m in enumerate(M):
            geo = iou(d["box"], m["box"]) if (d["box"] and m["box"]) else 0.0
            cost[i, j] = (1 - lam) * (1 - sim(d["text"], m["text"])) + lam * (1 - geo)
    ri, ci = linear_sum_assignment(cost)
    match_d2m = {int(i): int(j) for i, j in zip(ri, ci) if cost[i, j] <= tau}
    matched_m = set(match_d2m.values())

    # MinerU skeleton is unreliable when almost nothing matches (rotated/fuzzy scans -> garbage OCR)
    nd_txt = sum(d["kind"] == "text" for d in D)
    nm_txt = sum(m["kind"] == "text" for m in M)
    if garbage_frac > 0 and nd_txt >= 3 and nm_txt >= 3 and \
            len(match_d2m) < garbage_frac * min(len(D), len(M)):
        stats["garbage-mineru->docling"] += 1
        return [d["md"] for d in D] + tail, stats

    def pick_text(d: dict, m: dict) -> str:
        if text_pick == "docling":
            stats["pair-text->docling"] += 1
            return d["md"]
        if text_pick == "mineru":
            stats["pair-text->mineru"] += 1
            return m["md"]
        # auto: MinerU wins on body text unless it truncated the block or its OCR is worse
        ld, lm = len(d["text"]), len(m["text"])
        if lm < 0.6 * ld:
            # guard: a Docling block much longer than its MinerU partner that also contains text of other
            # MinerU blocks swallowed neighbours (cross-column OCR lines); MinerU segmentation is GT-like
            if pick_guard and ld > pick_guard * lm and swallows(d, [o for o in M if o is not m and o["kind"] == "text"]):
                stats["pair-text-auto->mineru(docling-swallowed)"] += 1
                return m["md"]
            stats["pair-text-auto->docling(longer)"] += 1
            return d["md"]
        if ld < 0.6 * lm:
            stats["pair-text-auto->mineru(longer)"] += 1
            return m["md"]
        qd, qm = quality(d["md"]), quality(m["md"])
        if qd > qm + 0.05:
            stats["pair-text-auto->docling(quality)"] += 1
            return d["md"]
        stats["pair-text-auto->mineru"] += 1
        return m["md"]

    def pick(d: dict, m: dict) -> str:
        if d["kind"] == "table" or m["kind"] == "table":
            if d["kind"] != m["kind"]:
                stats["pair-only-one-table"] += 1
                return d["md"] if d["kind"] == "table" else m["md"]
            stats[f"pair-table->{table_pref}"] += 1
            return d["md"] if table_pref == "docling" else m["md"]
        if d["kind"] == "formula" or m["kind"] == "formula":
            if d["kind"] != m["kind"]:
                stats["pair-only-one-formula"] += 1
                return d["md"] if d["kind"] == "formula" else m["md"]
            stats[f"pair-formula->{formula_pref}"] += 1
            return d["md"] if formula_pref == "docling" else m["md"]
        if d["kind"] == "heading" or m["kind"] == "heading":
            stats["pair-heading->docling"] += 1
            return d["md"] if d["kind"] == "heading" else m["md"]
        return pick_text(d, m)

    # skeleton: MinerU order, matched pairs resolved
    seq: list[tuple[float, float, str]] = []  # (order key, sub key, md)
    m2d = {j: i for i, j in match_d2m.items()}
    for j, m in enumerate(M):
        md = pick(D[m2d[j]], m) if j in m2d else m["md"]
        if j not in m2d:
            stats["unilateral-mineru"] += 1
        seq.append((float(j), 0.0, md))

    # insert unmatched Docling blocks next to the nearest MinerU block
    centers = [center(m["box"]) for m in M]
    for i, d in enumerate(D):
        if i in match_d2m:
            continue
        if len(d["text"]) < min_len and d["kind"] == "text":
            stats["dropped-docling-short"] += 1
            continue
        if pick_guard and d["kind"] == "text" and (
                (d["box"] is not None and sum(m["kind"] == "text" and m["box"] is not None and
                                              contain_frac(m["box"], d["box"]) >= 0.6 for m in M) >= 2)
                or (len(d["text"]) >= 200 and swallows(d, [o for o in M if o["kind"] == "text"]))):
            stats["dropped-docling-swallowing"] += 1  # unmatched Docling block covering >=2 MinerU blocks
            continue
        cx, cy = center(d["box"])
        j = int(np.argmin([(cx - x) ** 2 + (cy - y) ** 2 for x, y in centers]))
        above = cy < centers[j][1]
        seq.append((float(j) - 0.5 if above else float(j) + 0.5, cy, d["md"]))
        stats["unilateral-docling"] += 1
    seq.sort(key=lambda t: (t[0], t[1]))
    return [md for _, _, md in seq] + tail, stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docling", type=Path, required=True)
    ap.add_argument("--mineru", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--lam", type=float, default=0.5, help="weight of geometry in the match cost")
    ap.add_argument("--tau", type=float, default=0.6, help="max cost to accept a match")
    ap.add_argument("--min-len", type=int, default=20)
    ap.add_argument("--table-pref", choices=["docling", "mineru"], default="mineru")
    ap.add_argument("--formula-pref", choices=["docling", "mineru"], default="mineru")
    ap.add_argument("--drop-docling", default="", help="comma-separated Docling block types to drop")
    ap.add_argument("--drop-mineru", default="", help="comma-separated MinerU block types to drop")
    ap.add_argument("--garbage-fallback", type=float, default=0.0,
                    help="if matched pairs < FRAC*min(nD,nM) (both >=3 text blocks) use Docling order verbatim; 0=off")
    ap.add_argument("--text-pick", choices=["docling", "mineru", "auto"], default="docling",
                    help="which side to emit for matched body-text pairs")
    ap.add_argument("--decor-tail", action="store_true",
                    help="page_header/page_footer/page-number blocks excluded from matching and emitted after the body "
                         "in GT order header->footer->page_number")
    ap.add_argument("--junk-filter", action="store_true", help="drop text blocks that contain no real words (figure OCR)")
    ap.add_argument("--decor-wins", action="store_true",
                    help="with --decor-tail: a body block repeating a header/footer text is dropped (header goes to the tail)")
    ap.add_argument("--running-heads", type=int, default=0, metavar="N",
                    help="with --decor-tail: short top/bottom texts repeated on >= N pages of the same document are decor (0=off)")
    ap.add_argument("--pagenum-cap", type=int, default=0, metavar="K",
                    help="with --decor-tail: if a page has > K numeric-only blocks, only the ones in the margins are page numbers (0=off)")
    ap.add_argument("--merge-paragraphs", action="store_true",
                    help="fuse text blocks geometrically contained in one block of the other provider (anti-split)")
    ap.add_argument("--merge-frac", type=float, default=0.6, help="containment fraction for --merge-paragraphs")
    ap.add_argument("--merge-min-sim", type=float, default=0.0,
                    help="min text similarity between fused blocks and their container to accept a merge (0=off)")
    ap.add_argument("--suppress-regions", action="store_true",
                    help="drop Docling text inside MinerU tables, and inside MinerU pictures when it looks like figure OCR")
    ap.add_argument("--pic-min-blocks", type=int, default=2)
    ap.add_argument("--pic-max-quality", type=float, default=0.7)
    ap.add_argument("--suppress-mode", choices=["both", "tables", "pictures"], default="both")
    ap.add_argument("--pic-rule", choices=["count-or-quality", "quality"], default="count-or-quality",
                    help="quality: drop picture text only when >= --pic-min-blocks AND lexical quality < --pic-max-quality")
    ap.add_argument("--pic-full-page", type=float, default=0.9,
                    help="MinerU picture covering >= this page fraction is a comic/scan page: its text is kept")
    ap.add_argument("--table-full-page", type=float, default=0.0,
                    help="MinerU table covering >= this page fraction is a mis-detected flyer: do not suppress inside it (0=off)")
    ap.add_argument("--table-probe", action="store_true",
                    help="suppress Docling text inside a MinerU table only when the table text actually contains it")
    ap.add_argument("--fuse-lines", action="store_true",
                    help="fuse runs of >= --fuse-min-run short, left-aligned, adjacent text blocks (index/reference columns)")
    ap.add_argument("--fuse-max-len", type=int, default=0, help="cap fused block length (0 = unlimited)")
    ap.add_argument("--fuse-h-ratio", type=float, default=0.0,
                    help="break a fuse run when consecutive line heights differ by more than this ratio (0=off, e.g. 0.6)")
    ap.add_argument("--fuse-short", type=int, default=80)
    ap.add_argument("--fuse-min-run", type=int, default=3)
    ap.add_argument("--merge-side", choices=["both", "docling", "mineru"], default="both",
                    help="which provider's over-segmented blocks get fused by --merge-paragraphs")
    ap.add_argument("--pick-guard", type=float, default=0.0,
                    help="text-pick auto: never prefer a Docling block > GUARD x longer than its MinerU partner when it "
                         "also contains text of other MinerU blocks; drop unmatched Docling blocks that swallow others (0=off)")
    ap.add_argument("--flood-guard", type=float, default=0.0, metavar="R",
                    help="when Docling has >= R x MinerU text blocks (and >= 30), drop short Docling blocks with no lexicon word (chart ticks; 0=off)")
    ap.add_argument("--pic-need-text", action="store_true",
                    help="with --suppress-regions: skip picture suppression when MinerU has no text block on the page")
    ap.add_argument("--formula-text", action="store_true",
                    help="turn $$..$$ blocks without real math (workout tables, chemistry) into plain text")
    a = ap.parse_args()
    # '+' also accepted because Slurm --export splits values on commas
    drop_d = frozenset(t.strip().lower() for t in re.split(r"[,+]", a.drop_docling) if t.strip())
    drop_m = frozenset(t.strip().lower() for t in re.split(r"[,+]", a.drop_mineru) if t.strip())

    ids = sorted({p.name for p in a.docling.glob("*.drbench.md")} & {p.name for p in a.mineru.glob("*.drbench.md")})
    running: dict[str, frozenset[str]] = {}
    if a.running_heads:
        running = running_texts(ids, a.docling, a.mineru, drop_d, drop_m, min_pages=a.running_heads)
        print(f"running heads: {sum(len(v) for v in running.values())} texts in {sum(1 for v in running.values() if v)} docs")
    a.out.mkdir(parents=True, exist_ok=True)
    rows, tot = [], Counter()
    for name in ids:
        stem = name.removesuffix(".drbench.md")
        D = load_blocks(a.docling / f"{stem}.blocks.json", drop_d)
        m_pics: list = []
        M = load_blocks(a.mineru / f"{stem}.blocks.json", drop_m, m_pics)
        doc_md = (a.docling / name).read_text(encoding="utf-8")
        min_md = (a.mineru / name).read_text(encoding="utf-8")
        if D is None or M is None:
            blocks, stats, *_ = merge_v1(doc_md, min_md, 0.30, 0.80, 40)
            stats = Counter(stats); stats["fallback-v1"] += 1
        else:
            blocks, stats = merge_v2(D, M, lam=a.lam, tau=a.tau, min_len=a.min_len,
                                     table_pref=a.table_pref, formula_pref=a.formula_pref,
                                     garbage_frac=a.garbage_fallback, text_pick=a.text_pick,
                                     decor=a.decor_tail, junk=a.junk_filter,
                                     merge_paragraphs=a.merge_paragraphs, merge_frac=a.merge_frac,
                                     merge_min_sim=a.merge_min_sim, m_pics=m_pics, suppress=a.suppress_regions,
                                     pic_min_blocks=a.pic_min_blocks, pic_max_quality=a.pic_max_quality,
                                     pic_full_page=a.pic_full_page, fuse_lines=a.fuse_lines,
                                     fuse_max_len=a.fuse_max_len, fuse_short=a.fuse_short,
                                     fuse_min_run=a.fuse_min_run, merge_side=a.merge_side, pick_guard=a.pick_guard,
                                     decor_wins=a.decor_wins, running=running.get(doc_id_of(stem), frozenset()),
                                     suppress_mode=a.suppress_mode, pic_rule=a.pic_rule,
                                     table_full_page=a.table_full_page, fuse_h_ratio=a.fuse_h_ratio,
                                     table_probe=a.table_probe, pagenum_cap=a.pagenum_cap,
                                     flood=a.flood_guard, pic_need_text=a.pic_need_text,
                                     formula_text=a.formula_text)
        if not blocks:
            blocks = split_blocks(doc_md if len(norm(doc_md)) >= len(norm(min_md)) else min_md)
            stats["fallback-longer"] += 1
        (a.out / name).write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
        tot.update(stats)
        rows.append({"item": stem, "n_docling": len(D or []), "n_mineru": len(M or []), "n_out": len(blocks),
                     **dict(stats)})
    keys = ["item", "n_docling", "n_mineru", "n_out"] + sorted(tot)
    with (a.out / "decisions.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, restval=0); w.writeheader(); w.writerows(rows)
    print(f"pages={len(ids)} lam={a.lam} tau={a.tau} min_len={a.min_len} "
          f"table_pref={a.table_pref} formula_pref={a.formula_pref} "
          f"drop_docling={sorted(drop_d)} drop_mineru={sorted(drop_m)} garbage_fallback={a.garbage_fallback} "
          f"text_pick={a.text_pick} decor_tail={a.decor_tail} junk_filter={a.junk_filter} "
          f"merge_paragraphs={a.merge_paragraphs}")
    for k, v in sorted(tot.items()):
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
