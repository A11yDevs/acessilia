#!/usr/bin/env python3
"""VLM adjudicator (paper's Adjudicator Agent) — exact-transcription mode.

For each record of the adjudication queue (tree_differ_v2 --dump-queue + make_crops.py), a VLM sees the
page-region crop plus the candidate texts as OCR hints and returns an exact transcription. The decision
is derived deterministically: transcription ~= a candidate -> select it; plausible but different ->
replace with the transcription; unreadable/unsupported unilateral -> drop. Unparseable/implausible
answers are skipped so the deterministic Differ rules remain the fallback.
Output feeds `tree_differ_v2 --adjudications`.

Usage (inside a GPU job):
  python scripts/vlm_adjudicate.py --queue queue_crops.jsonl --out adjudications.jsonl \
      --model Qwen/Qwen3-VL-8B-Instruct [--max-records 20000]
"""
import argparse
import difflib
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

TRANSCRIBE_PROMPT = """You are a precise OCR transcriber.
The image is a region cropped from a document page. OCR hypotheses for this region (may contain errors):

{cands}

Transcribe EXACTLY the text visible in the image.
- Do not paraphrase, translate, summarise or correct grammar.
- Preserve capitalisation, punctuation, numbers and symbols exactly as printed.
- Plain text only: no markdown syntax, no code fences, no commentary.
- If the region contains no readable text, answer exactly: <EMPTY>
Return ONLY the transcription."""


def nrm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[#*_`>|]", "", s or "")).strip().lower()


def ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, nrm(a), nrm(b), autojunk=False).ratio()


def clean(t: str) -> str:
    t = re.sub(r"^```[a-z]*\n?|```$", "", (t or "").strip()).strip()
    return "" if t == "<EMPTY>" else t


def decide(r: dict, t: str, stats: Counter) -> dict | None:
    """Turn a transcription into a differ decision (or None = keep deterministic fallback)."""
    a, b = r.get("md_d") or "", r.get("md_m") or ""
    if r["i"] >= 0 and r["j"] >= 0:  # matched pair
        if not t:
            stats["pair-empty"] += 1
            return None
        ra, rb = ratio(t, a), ratio(t, b)
        if max(ra, rb) >= 0.96:
            stats["pair-select"] += 1
            return {"action": "select_a" if ra >= rb else "select_b"}
        lm = max(len(nrm(a)), len(nrm(b)))
        if lm and 0.5 * lm <= len(nrm(t)) <= 3.0 * lm:
            stats["pair-replace"] += 1
            return {"action": "replace", "text": t}
        stats["pair-implausible"] += 1
        return None
    cand = a or b  # unilateral block (one provider only)
    if not t:
        stats["uni-drop-empty"] += 1
        return {"action": "drop"}
    rc = ratio(t, cand)
    if rc >= 0.96:
        stats["uni-keep"] += 1
        return None
    if rc <= 0.25 and len(nrm(t)) < 0.3 * len(nrm(cand)):
        stats["uni-drop-unsupported"] += 1
        return {"action": "drop"}
    if 0.4 * len(nrm(cand)) <= len(nrm(t)) <= 3.0 * len(nrm(cand)):
        stats["uni-replace"] += 1
        return {"action": "replace", "text": t}
    stats["uni-implausible"] += 1
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--model", default="Qwen/Qwen3-VL-8B-Instruct")
    ap.add_argument("--max-records", type=int, default=20000)
    ap.add_argument("--max-model-len", type=int, default=8192)
    ap.add_argument("--gpu-memory-utilization", type=float, default=0.90)
    ap.add_argument("--tensor-parallel-size", type=int, default=1)
    # jobs 33371/33372: JIT do DeepGEMM/FlashInfer quebra no ptxas -> modo eager evita CUDA graphs/compilação
    ap.add_argument("--enforce-eager", action="store_true")
    # v24: tables go to the table specialist (a plain-text transcription would destroy the HTML table)
    ap.add_argument("--skip-kinds", default="", help="+-list of block kinds to leave out (e.g. table)")
    a = ap.parse_args()

    recs = [json.loads(l) for l in a.queue.read_text(encoding="utf-8").splitlines() if l.strip()]
    recs = [r for r in recs if r.get("crop")]
    if a.skip_kinds:
        skip = set(a.skip_kinds.split("+"))
        recs = [r for r in recs if not ({r.get("kind_d"), r.get("kind_m")} & skip)]
    if len(recs) > a.max_records:
        # prioritise content disputes by lowest similarity, then unilaterals by longest text
        pairs = sorted((r for r in recs if r["i"] >= 0 and r["j"] >= 0), key=lambda r: r.get("sim") or 0.0)
        unis = sorted((r for r in recs if r["i"] < 0 or r["j"] < 0),
                      key=lambda r: -len(r.get("md_d") or r.get("md_m") or ""))
        recs = (pairs + unis)[: a.max_records]
    print(f"queue: {len(recs)} records "
          f"({Counter(r['cls'] for r in recs)})", flush=True)
    print(f"model={a.model} max_model_len={a.max_model_len} "
          f"gpu_mem={a.gpu_memory_utilization} tp={a.tensor_parallel_size}", flush=True)

    from vllm import LLM, SamplingParams
    # vLLM recusa file:// fora de allowed_local_media_path (job 33358)
    media_root = os.path.commonpath([os.path.dirname(os.path.abspath(r["crop"])) for r in recs])
    # Qwen3-VL: disable video to save VRAM; trust_remote_code for newer configs
    llm_kwargs = dict(
        model=a.model,
        max_model_len=a.max_model_len,
        gpu_memory_utilization=a.gpu_memory_utilization,
        tensor_parallel_size=a.tensor_parallel_size,
        limit_mm_per_prompt={"image": 1, "video": 0},
        enforce_eager=a.enforce_eager,
        allowed_local_media_path=media_root,
        trust_remote_code=True,
    )
    try:
        llm = LLM(**llm_kwargs)
    except TypeError:
        llm_kwargs.pop("trust_remote_code", None)
        llm = LLM(**llm_kwargs)
    sampling = SamplingParams(temperature=0.0, max_tokens=1024)

    convs = []
    for r in recs:
        cands = "\n\n".join(f"Hypothesis {k}:\n\"\"\"{c[:1800]}\"\"\""
                            for k, c in (("A", r.get("md_d")), ("B", r.get("md_m"))) if c)
        convs.append([{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"file://{r['crop']}"}},
            {"type": "text", "text": TRANSCRIBE_PROMPT.format(cands=cands)}]}])

    decisions, stats = [], Counter()
    B = 512
    for k in range(0, len(convs), B):
        outs = llm.chat(convs[k: k + B], sampling)
        for r, o in zip(recs[k: k + B], outs):
            d = decide(r, clean(o.outputs[0].text), stats)
            if d is not None:
                decisions.append({"page": r["page"], "i": r["i"], "j": r["j"], **d})
        print(f"[{min(k + B, len(convs))}/{len(convs)}] stats: {dict(stats)}", flush=True)

    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("w", encoding="utf-8") as f:
        for d in decisions:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    print(f"wrote {len(decisions)} decisions -> {a.out}; stats={dict(stats)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
