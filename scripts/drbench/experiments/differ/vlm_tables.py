#!/usr/bin/env python3
"""VLM table specialist (paper: generate-compare-adjudicate) for table blocks of the adjudication queue.

For each table record (tree_differ_v2 --queue-tables --dump-queue + make_crops.py --kinds table) the VLM
re-generates the table as HTML from the crop (1 greedy + N sampled), with the provider tables as hints.
Candidates = {Docling table, MinerU table, VLM generations}; the medoid by pairwise TEDS is selected
(self-consistency): provider -> select_a/select_b, VLM -> replace with its HTML.
Raw generations are saved so the selection can be redone on CPU (--select-only).

Outputs: <prefix>-raw.jsonl, <prefix>-medoid.jsonl, <prefix>-greedy.jsonl (tree_differ_v2 --adjudications).
"""
import argparse
import json
import os
import re
import sys
from collections import Counter
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "repos" / "DrDocBench"))

TABLE_PROMPT = """You are a precise table recognition system.
The image is a table cropped from a document page. Two OCR systems produced these HTML hypotheses (may contain
errors in structure or text):

{cands}

Reproduce the table in the image as HTML.
- Output a single <table> using only <tr>, <td> (use <th> only for header cells), with colspan/rowspan where cells span.
- One <tr> per visual row; every visual cell becomes one cell, empty cells as <td></td>.
- Transcribe cell text EXACTLY as printed (numbers, punctuation, symbols, capitalisation). No styles, no markdown.
Return ONLY the HTML table."""

TAB_RE = re.compile(r"<table[\s\S]*?</table>", re.I)


def extract(t: str) -> str:
    t = re.sub(r"```[a-z]*", "", t or "")
    m = TAB_RE.search(t)
    return m.group(0) if m else ""


def norm(t: str) -> str:
    """Evaluator-style normalisation (utils/table_utils.convert_table_str) + drop non-structural attrs/tags."""
    t = re.sub(r"<table[^>]*>", "<table>", t)
    t = re.sub(r"<(/?)th\b", r"<\1td", t)
    t = re.sub(r"</?(thead|tbody|tfoot|eq|span|div|p|br)\b[^>]*>", "", t)
    t = re.sub(r"<(td|tr)\b([^>]*)>", lambda m: "<%s%s>" % (m.group(1), "".join(
        f' {k}="{v}"' for k, v in re.findall(r'(colspan|rowspan)\s*=\s*"?(\d+)"?', m.group(2)))), t)
    return t


_TEDS = None


def teds(args):
    global _TEDS
    if _TEDS is None:
        from metrics.table_metric import TEDS
        _TEDS = TEDS(structure_only=False)
    a, b = args
    try:
        return _TEDS.evaluate(f"<html><body>{a}</body></html>", f"<html><body>{b}</body></html>")
    except Exception:
        return 0.0


def valid(t: str) -> bool:
    return bool(t) and t.count("<tr") >= 1 and ("<td" in t or "<th" in t)


def select(raws: list[dict], recs: dict, workers: int, max_chars: int):
    """Returns (medoid decisions, greedy decisions, stats)."""
    jobs, meta = [], []
    for r in raws:
        q = recs.get((r["page"], r["i"], r["j"]))
        if q is None:
            continue
        cands = []  # (name, html)
        if q.get("kind_d") == "table" and valid(extract(q.get("md_d"))):
            cands.append(("a", extract(q["md_d"])))
        if q.get("kind_m") == "table" and valid(extract(q.get("md_m"))):
            cands.append(("b", extract(q["md_m"])))
        gens = [extract(g) for g in [r.get("greedy", "")] + r.get("samples", [])]
        for k, g in enumerate(gens):
            if valid(g) and len(g) <= max_chars:
                cands.append((f"v{k}", g))
        nc = [norm(h) for _, h in cands]
        pairs = [(x, y) for x in range(len(cands)) for y in range(x + 1, len(cands))]
        meta.append((r, q, cands, pairs, len(jobs)))
        jobs += [(nc[x], nc[y]) for x, y in pairs]
    with Pool(workers) as p:
        sc = p.map(teds, jobs, chunksize=4)
    med, grd, st = [], [], Counter()
    for r, q, cands, pairs, off in meta:
        key = {"page": r["page"], "i": r["i"], "j": r["j"]}
        names = [n for n, _ in cands]
        if not cands:
            st["no-cand"] += 1
            continue
        tot = [0.0] * len(cands)
        sim = {}
        for (x, y), s in zip(pairs, sc[off: off + len(pairs)]):
            tot[x] += s
            tot[y] += s
            sim[(x, y)] = sim[(y, x)] = s
        # tie-break: prefer providers (deterministic, already in the paper's Differ), then greedy
        best = max(range(len(cands)), key=lambda k: (round(tot[k], 6), -k))
        n = names[best]
        st[f"medoid-{n[0]}"] += 1
        if n in ("a", "b"):
            med.append({**key, "action": f"select_{n}"})
        else:
            med.append({**key, "action": "replace", "text": cands[best][1]})
        if "v0" in names:
            g = names.index("v0")
            # greedy unless it is ~identical to a provider table (then just select that provider)
            close = [(sim.get((g, k), 0.0), names[k]) for k in range(len(cands)) if names[k] in ("a", "b")]
            s, pn = max(close) if close else (0.0, "")
            if s >= 0.98:
                grd.append({**key, "action": f"select_{pn}"})
                st["greedy-select"] += 1
            else:
                grd.append({**key, "action": "replace", "text": cands[g][1]})
                st["greedy-replace"] += 1
    return med, grd, st


def dump(path: Path, rows: list[dict]):
    with path.open("w", encoding="utf-8") as f:
        for d in rows:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", type=Path, required=True, help="table queue_crops.jsonl")
    ap.add_argument("--out-prefix", type=Path, required=True)
    ap.add_argument("--model", default="Qwen/Qwen3-VL-32B-Instruct-FP8")
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--max-tokens", type=int, default=6000)
    ap.add_argument("--max-model-len", type=int, default=16384)
    ap.add_argument("--gpu-memory-utilization", type=float, default=0.90)
    ap.add_argument("--tensor-parallel-size", type=int, default=1)
    ap.add_argument("--enforce-eager", action="store_true")
    ap.add_argument("--hint-chars", type=int, default=6000)
    ap.add_argument("--max-chars", type=int, default=30000, help="drop runaway generations")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--select-only", action="store_true", help="reuse <prefix>-raw.jsonl (CPU)")
    ap.add_argument("--generate-only", action="store_true", help="stop after <prefix>-raw.jsonl (vLLM venv lacks apted)")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    recs = [json.loads(l) for l in a.queue.read_text(encoding="utf-8").splitlines() if l.strip()]
    recs = [r for r in recs if r.get("crop") and "table" in (r.get("kind_d"), r.get("kind_m"))]
    if a.limit:
        recs = recs[: a.limit]
    by_key = {(r["page"], r["i"], r["j"]): r for r in recs}
    raw_path = Path(f"{a.out_prefix}-raw.jsonl")
    print(f"table queue: {len(recs)} records", flush=True)

    if not (a.select_only or raw_path.exists() and raw_path.stat().st_size > 0):
        from vllm import LLM, SamplingParams
        media_root = os.path.commonpath([os.path.dirname(os.path.abspath(r["crop"])) for r in recs])
        llm = LLM(model=a.model, max_model_len=a.max_model_len, gpu_memory_utilization=a.gpu_memory_utilization,
                  tensor_parallel_size=a.tensor_parallel_size, limit_mm_per_prompt={"image": 1, "video": 0},
                  enforce_eager=a.enforce_eager, allowed_local_media_path=media_root, trust_remote_code=True)
        convs = []
        for r in recs:
            cands = "\n\n".join(f"Hypothesis {k}:\n{c[:a.hint_chars]}"
                                for k, c in (("A", r.get("md_d")), ("B", r.get("md_m"))) if c)
            convs.append([{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"file://{os.path.abspath(r['crop'])}"}},
                {"type": "text", "text": TABLE_PROMPT.format(cands=cands or "(none)")}]}])
        g_sp = SamplingParams(temperature=0.0, max_tokens=a.max_tokens)
        s_sp = SamplingParams(temperature=a.temperature, top_p=0.95, n=a.samples, max_tokens=a.max_tokens, seed=0)
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = raw_path.with_suffix(".partial")
        with tmp.open("w", encoding="utf-8") as f:
            B = 128
            for k in range(0, len(convs), B):
                go = llm.chat(convs[k: k + B], g_sp)
                so = llm.chat(convs[k: k + B], s_sp) if a.samples else [None] * len(go)
                for r, g, s in zip(recs[k: k + B], go, so):
                    f.write(json.dumps({"page": r["page"], "i": r["i"], "j": r["j"], "greedy": g.outputs[0].text,
                                        "samples": [o.text for o in s.outputs] if s else []},
                                       ensure_ascii=False) + "\n")
                f.flush()
                print(f"[{min(k + B, len(convs))}/{len(convs)}] generated", flush=True)
        tmp.rename(raw_path)
    if a.generate_only:
        return 0

    raws = [json.loads(l) for l in raw_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    med, grd, st = select(raws, by_key, a.workers, a.max_chars)
    dump(Path(f"{a.out_prefix}-medoid.jsonl"), med)
    dump(Path(f"{a.out_prefix}-greedy.jsonl"), grd)
    print(f"wrote medoid {len(med)} / greedy {len(grd)} decisions; stats={dict(st)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
