#!/usr/bin/env python3
"""Whole-page OCR with DeepSeek-OCR-2 (vLLM) -> <doc>_p<N>.drbench.md, another independent page source.

Grounding mode returns blocks "<|ref|>CAT<|/ref|><|det|>[[x1,y1,x2,y2]]<|/det|>\\nTEXT"; image blocks are dropped and,
with --hf-end, header/footer-like categories go last (GT convention). Raw generations go to <out>-raw.jsonl;
--from-raw re-renders without a GPU.

  dsocr_page_ocr.py --images-root R --out OUT [--only-gt R] [--keys F]
  dsocr_page_ocr.py --from-raw RAW.jsonl --out OUT [--hf-end]
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vlm_page_ocr import pages  # noqa: E402

PROMPT = "<image>\n<|grounding|>Convert the document to markdown. "
BLK = re.compile(r"<\|ref\|>(.*?)<\|/ref\|><\|det\|>.*?<\|/det\|>\s*", re.S)
HF = ("header", "footer", "page_header", "page_footer", "page_number")
SKIP = ("image",)


def parse(t: str):
    t = t.replace("<｜end▁of▁sentence｜>", "")
    ms = list(BLK.finditer(t))
    if not ms:
        return [{"category": "text", "text": t.strip()}]
    return [{"category": m.group(1).strip(), "text": t[m.end(): ms[i + 1].start() if i + 1 < len(ms) else len(t)].strip()}
            for i, m in enumerate(ms)]


def render(els, hf_end=False):
    if hf_end:
        els = [e for e in els if e["category"] not in HF] + [e for e in els if e["category"] in HF]
    out = [e["text"] for e in els if e["category"] not in SKIP and e["text"]]
    return "\n\n\n\n\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images-root", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--only-gt", type=Path)
    ap.add_argument("--keys", type=Path)
    ap.add_argument("--from-raw", type=Path)
    ap.add_argument("--hf-end", action="store_true")
    ap.add_argument("--model", default="deepseek-ai/DeepSeek-OCR-2")
    ap.add_argument("--revision", default=None, help="HF revision (commit/tag) to pin the model weights")
    ap.add_argument("--max-tokens", type=int, default=7000)
    ap.add_argument("--max-model-len", type=int, default=8192)
    ap.add_argument("--gpu-memory-utilization", type=float, default=0.90)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--enforce-eager", action="store_true")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    if a.from_raw:
        n = 0
        for r in map(json.loads, a.from_raw.open(encoding="utf-8")):
            (a.out / f"{r['doc']}_p{r['page']}.drbench.md").write_text(render(parse(r["text"]), a.hf_end), encoding="utf-8")
            n += 1
        print(f"rendered {n}")
        return 0

    keys = set(a.keys.read_text().split()) if a.keys else None
    todo = []
    for doc, n, img in pages(a.images_root):
        if a.only_gt and not list(a.only_gt.glob(f"*/{doc}/mds/{doc}_{n}.md")):
            continue
        if keys is not None and f"{doc}_p{n}" not in keys:
            continue
        if not (a.out / f"{doc}_p{n}.drbench.md").exists():
            todo.append((doc, n, img))
    if a.limit:
        todo = todo[: a.limit]
    print(f"pages to do: {len(todo)}", flush=True)
    if not todo:
        return 0
    from PIL import Image
    from vllm import LLM, SamplingParams
    from vllm.model_executor.models.deepseek_ocr import NGramPerReqLogitsProcessor
    llm = LLM(model=a.model, revision=a.revision, max_model_len=a.max_model_len, gpu_memory_utilization=a.gpu_memory_utilization,
              enable_prefix_caching=False, mm_processor_cache_gb=0, logits_processors=[NGramPerReqLogitsProcessor],
              trust_remote_code=True, enforce_eager=a.enforce_eager)
    sp = SamplingParams(temperature=0.0, max_tokens=a.max_tokens, skip_special_tokens=False,
                        extra_args=dict(ngram_size=30, window_size=90, whitelist_token_ids={128821, 128822}))
    raw = (a.out.parent / f"{a.out.name}-raw.jsonl").open("a", encoding="utf-8")
    B = 64
    for k in range(0, len(todo), B):
        chunk = todo[k: k + B]
        reqs = [{"prompt": PROMPT, "multi_modal_data": {"image": Image.open(img).convert("RGB")}} for _, _, img in chunk]
        outs = llm.generate(reqs, sp)
        for (doc, n, _), o in zip(chunk, outs):
            t = o.outputs[0].text
            raw.write(json.dumps({"doc": doc, "page": n, "finish": o.outputs[0].finish_reason, "text": t},
                                 ensure_ascii=False) + "\n")
            (a.out / f"{doc}_p{n}.drbench.md").write_text(render(parse(t), a.hf_end), encoding="utf-8")
        raw.flush()
        print(f"[{min(k + B, len(todo))}/{len(todo)}] done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
