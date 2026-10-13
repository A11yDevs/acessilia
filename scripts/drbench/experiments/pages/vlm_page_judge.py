#!/usr/bin/env python3
"""Page-level adjudication by the VLM: Qwen3-VL sees the page image and two candidate transcriptions (A, B) and
says which one is more faithful. Both orders are asked (position debiasing); p(B better) is the mean of the two
first-token probabilities. Only pages where A and B diverge (ratio < --max-ratio, both non-empty) are judged; --list-keys writes that page list
(needs rapidfuzz, CPU env) for --keys in the vLLM env.

  vlm_page_judge.py --images-root R --a A --b B --list-keys KEYS [--max-ratio 0.97]
  vlm_page_judge.py --images-root R --a A --b B --keys KEYS --out OUT.jsonl
"""
import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vlm_page_ocr import pages  # noqa: E402

PROMPT = """The image is a document page. Below are two candidate transcriptions of it (Markdown/HTML), produced by different OCR systems.

Decide which candidate is the more faithful transcription of the page, judging:
1. Text accuracy: no missing text, no extra/hallucinated/repeated text, no garbled characters or words.
2. Reading order: blocks in the natural order a human reads the page (columns top to bottom, left column first). Running headers, footers and page numbers are expected at the END.
3. Text that is part of a picture (photo, illustration, diagram, chart, map, logo) should NOT be transcribed; captions outside pictures should be.
Ignore Markdown/HTML formatting differences (heading marks, bold, line breaks).

=== Candidate 1 ===
{c1}

=== Candidate 2 ===
{c2}

Which candidate is more faithful? Answer with exactly one character: 1 or 2."""
# variants for prompt ensembling (LOOP #46)
PROMPTS = {"base": PROMPT,
           "para": PROMPT.replace("Ignore Markdown/HTML formatting", "4. Block structure: each paragraph, verse stanza, list or table kept whole as ONE block (not split line by line, not "
                                  "several paragraphs glued together); blank lines separate blocks.\nIgnore other Markdown/HTML formatting"),
           "err": PROMPT.replace("Decide which candidate is the more faithful transcription of the page, judging:",
                                 "Compare both candidates against the page image, word by word, and count their errors. Consider:")
                        .replace("Which candidate is more faithful?", "Which candidate has FEWER errors overall?")}


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images-root", type=Path, required=True)
    ap.add_argument("--a", type=Path, required=True)
    ap.add_argument("--b", type=Path, required=True)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--keys", type=Path)
    ap.add_argument("--list-keys", type=Path)
    ap.add_argument("--max-ratio", type=float, default=0.97)
    ap.add_argument("--max-chars", type=int, default=14000)
    ap.add_argument("--model", default="Qwen/Qwen3-VL-32B-Instruct-FP8")
    ap.add_argument("--max-model-len", type=int, default=32768)
    ap.add_argument("--gpu-memory-utilization", type=float, default=0.90)
    ap.add_argument("--enforce-eager", action="store_true")
    ap.add_argument("--prompt", default="base", choices=["base", "para", "err"])
    a = ap.parse_args()
    if a.list_keys:
        from page_fuse import norm
        from rapidfuzz import fuzz
        ks = []
        for doc, n, _ in pages(a.images_root):
            k = f"{doc}_p{n}"
            A, B = norm(read(a.a / f"{k}.drbench.md")), norm(read(a.b / f"{k}.drbench.md"))
            if A and B and fuzz.ratio(A, B) / 100 < a.max_ratio:
                ks.append(k)
        a.list_keys.write_text("\n".join(ks) + "\n")
        print(f"divergent pages: {len(ks)}")
        return 0
    keys = set(a.keys.read_text().split())
    done = {json.loads(l)["key"] for l in a.out.open()} if a.out.exists() else set()
    todo = []
    for doc, n, img in pages(a.images_root):
        k = f"{doc}_p{n}"
        if k in keys and k not in done:
            ta, tb = read(a.a / f"{k}.drbench.md"), read(a.b / f"{k}.drbench.md")
            todo.append((k, img, ta[: a.max_chars], tb[: a.max_chars]))
    print(f"pages to judge: {len(todo)}", flush=True)
    if not todo:
        return 0
    from vllm import LLM, SamplingParams
    llm = LLM(model=a.model, max_model_len=a.max_model_len, gpu_memory_utilization=a.gpu_memory_utilization,
              limit_mm_per_prompt={"image": 1, "video": 0}, enforce_eager=a.enforce_eager,
              allowed_local_media_path=str(a.images_root.resolve()), trust_remote_code=True)
    sp = SamplingParams(temperature=0.0, max_tokens=1, logprobs=20)
    out = a.out.open("a", encoding="utf-8")

    def p2(o):  # P("2") / (P("1") + P("2")) from the first generated token
        lp = o.outputs[0].logprobs[0]
        d = {x.decoded_token.strip(): math.exp(x.logprob) for x in lp.values()}
        p1, q2 = d.get("1", 0.0), d.get("2", 0.0)
        return q2 / (p1 + q2) if p1 + q2 > 0 else 0.5

    B_ = 32
    for i in range(0, len(todo), B_):
        chunk = todo[i: i + B_]
        convs = []
        for _, img, ta, tb in chunk:
            for c1, c2 in ((ta, tb), (tb, ta)):
                convs.append([{"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": f"file://{img.resolve()}"}},
                    {"type": "text", "text": PROMPTS[a.prompt].format(c1=c1, c2=c2)}]}])
        outs = llm.chat(convs, sp)
        for j, (k, _, _, _) in enumerate(chunk):
            pab, pba = p2(outs[2 * j]), p2(outs[2 * j + 1])  # p(B) in order (A,B); p(A) in order (B,A)
            out.write(json.dumps({"key": k, "pB_ab": pab, "pA_ba": pba, "pB": (pab + 1 - pba) / 2}) + "\n")
        out.flush()
        print(f"[{min(i + B_, len(todo))}/{len(todo)}] done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
