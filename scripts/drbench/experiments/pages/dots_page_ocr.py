#!/usr/bin/env python3
"""Whole-page layout parse with dots.ocr (vLLM) -> <doc>_p<N>.drbench.md, another independent tree source.

dots.ocr returns a JSON list of layout elements {bbox, category, text} in reading order; 'Picture' elements carry
no text (the GT never transcribes text that is part of a picture). Raw generations go to <out>-raw.jsonl;
--from-raw re-renders the markdown from it without a GPU (e.g. with --drop categories).

  dots_page_ocr.py --images-root R --out OUT [--only-gt R] [--keys F]
  dots_page_ocr.py --from-raw RAW.jsonl --out OUT [--drop Page-header,Page-footer]
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vlm_page_ocr import pages  # noqa: E402

PROMPT = """Please output the layout information from the PDF image, including each layout element's bbox, its category, and the corresponding text within the bbox.

1. Bbox format: [x1, y1, x2, y2]

2. Layout Categories: The possible categories are ['Caption', 'Footnote', 'Formula', 'List-item', 'Page-footer', 'Page-header', 'Picture', 'Section-header', 'Table', 'Text', 'Title'].

3. Text Extraction & Formatting Rules:
    - Picture: For the 'Picture' category, the text field should be omitted.
    - Formula: Format its text as LaTeX.
    - Table: Format its text as HTML.
    - All Others (Text, Title, etc.): Format their text as Markdown.

4. Constraints:
    - The output text must be the original text from the image, with no translation.
    - All layout elements must be sorted according to human reading order.

5. Final Output: The entire output must be a single JSON object.
"""


def parse(t: str):
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t.strip())
    try:
        x = json.loads(t)
    except json.JSONDecodeError:
        # truncated generation: keep complete elements
        x = []
        for m in re.finditer(r"\{[^{}]*\}", t):
            try:
                x.append(json.loads(m.group(0)))
            except json.JSONDecodeError:
                pass
    if isinstance(x, dict):
        x = next((v for v in x.values() if isinstance(v, list)), [x])
    return [e for e in x if isinstance(e, dict)]


def render(els, drop=(), hf_end=False):
    if hf_end:  # GT convention: running header / page number come last
        hf = ("Page-header", "Page-footer")
        els = [e for e in els if e.get("category") not in hf] + [e for e in els if e.get("category") in hf]
    out = []
    for e in els:
        c, t = e.get("category", "Text"), (e.get("text") or "").strip()
        if c == "Picture" or c in drop or not t:
            continue
        if c == "Formula" and not t.startswith("$"):
            t = f"$$\n{t}\n$$"
        elif c == "Title" and not t.startswith("#"):
            t = "# " + t
        elif c == "Section-header" and not t.startswith("#"):
            t = "## " + t
        out.append(t)
    return "\n\n\n\n\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images-root", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--only-gt", type=Path)
    ap.add_argument("--keys", type=Path)
    ap.add_argument("--from-raw", type=Path)
    ap.add_argument("--drop", default="", help="comma-separated categories to leave out")
    ap.add_argument("--hf-end", action="store_true", help="move Page-header/Page-footer to the end of the page")
    ap.add_argument("--model", default="dots-studio/dots.ocr")
    ap.add_argument("--revision", default=None, help="HF revision (commit/tag) to pin the model weights")
    ap.add_argument("--max-tokens", type=int, default=16000)
    ap.add_argument("--max-model-len", type=int, default=24000)
    ap.add_argument("--gpu-memory-utilization", type=float, default=0.90)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--enforce-eager", action="store_true")
    ap.add_argument("--ngram", type=int, default=0, help="ban repeating N-grams (vLLM NoRepeatNGram, window 3N) vs loops")
    a = ap.parse_args()
    drop = set(filter(None, a.drop.split(",")))
    a.out.mkdir(parents=True, exist_ok=True)
    if a.from_raw:
        n = 0
        for r in map(json.loads, a.from_raw.open(encoding="utf-8")):
            (a.out / f"{r['doc']}_p{r['page']}.drbench.md").write_text(render(parse(r["text"]), drop, a.hf_end), encoding="utf-8")
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
    from vllm import LLM, SamplingParams
    from vllm.model_executor.models.deepseek_ocr import NGramPerReqLogitsProcessor
    llm = LLM(model=a.model, revision=a.revision, max_model_len=a.max_model_len, gpu_memory_utilization=a.gpu_memory_utilization,
              limit_mm_per_prompt={"image": 1, "video": 0}, trust_remote_code=True, enforce_eager=a.enforce_eager,
              allowed_local_media_path=str(a.images_root.resolve()),
              **({"logits_processors": [NGramPerReqLogitsProcessor]} if a.ngram else {}))
    sp = SamplingParams(temperature=0.0, max_tokens=a.max_tokens, repetition_penalty=1.05,
                        extra_args=dict(ngram_size=a.ngram, window_size=3 * a.ngram) if a.ngram else None)
    raw = (a.out.parent / f"{a.out.name}-raw.jsonl").open("a", encoding="utf-8")
    B = 64
    for k in range(0, len(todo), B):
        chunk = todo[k: k + B]
        convs = [[{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"file://{img.resolve()}"}},
            {"type": "text", "text": PROMPT}]}] for _, _, img in chunk]
        outs = llm.chat(convs, sp)
        for (doc, n, _), o in zip(chunk, outs):
            t = o.outputs[0].text
            raw.write(json.dumps({"doc": doc, "page": n, "finish": o.outputs[0].finish_reason, "text": t},
                                 ensure_ascii=False) + "\n")
            (a.out / f"{doc}_p{n}.drbench.md").write_text(render(parse(t), drop, a.hf_end), encoding="utf-8")
        raw.flush()
        print(f"[{min(k + B, len(todo))}/{len(todo)}] done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
