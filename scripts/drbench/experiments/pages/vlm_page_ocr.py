#!/usr/bin/env python3
"""Whole-page OCR with a VLM (Qwen3-VL) -> <doc>_p<N>.drbench.md, in the DrDocBench GT markdown style.

Used as a third tree source for the differ adjudication (page-level selection / block fallback).
Pages: every images/page_N.jpg under --images-root (<SUBJ>/<doc>/[images/]page_N.jpg). Resumable: pages whose
output already exists are skipped. Raw generations also appended to <out>/../raw.jsonl.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

PROMPT = """Transcribe this document page into Markdown, exactly as printed, in natural reading order.
Rules:
- Separate every block (paragraph, heading, list item, caption, footnote, header/footer line, page number) by a blank line.
- Headings start with '#' ('#' for the main title, '##' for section headings).
- Tables: output as HTML <table> with <tr>/<td> (colspan/rowspan where cells span). No Markdown pipe tables.
- Mathematical formulas in LaTeX: inline as $...$, display formulas as $$...$$ on their own lines.
- Use *italic* and **bold** where the text is italic or bold.
- Keep line-break hyphenation exactly as printed (e.g. "con-sidered" if the word is split across lines), but join the lines of a paragraph into one line.
- Include running headers, footers and page numbers as separate blocks at the position where they appear.
- Do not describe images or figures; transcribe only text that appears in them if it is a caption.
- Output only the Markdown, no commentary."""

# v2: GT never transcribes text that is part of a picture (photos, illustrations, scrapbook art, diagrams, maps)
PROMPT_V2 = PROMPT.replace(
    "- Do not describe images or figures; transcribe only text that appears in them if it is a caption.",
    "- Do NOT transcribe any text that is part of a picture: photographs, illustrations, drawings, scrapbook or "
    "decorative art, diagrams, charts, maps, screenshots, logos. Skip such regions entirely (no description). "
    "Captions printed outside the picture are transcribed.\n"
    "- If the page has no printed text outside pictures, output nothing.")

FENCE = re.compile(r"^```(?:markdown|md)?\s*\n|\n```\s*$")


def pages(root: Path):
    for img in sorted(root.glob("*/*/page_*.jpg")) + sorted(root.glob("*/*/images/page_*.jpg")):
        doc = img.parent.name if img.parent.name != "images" else img.parent.parent.name
        n = int(img.stem.split("_")[1])
        yield doc, n, img


def clean(t: str) -> str:
    t = FENCE.sub("", t.strip()).strip()
    return re.sub(r"\n{2,}", "\n\n\n\n\n", t) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images-root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--only-gt", type=Path, help="dev: keep only pages with <root>/<SUBJ>/<doc>/mds/<doc>_<N>.md")
    ap.add_argument("--model", default="Qwen/Qwen3-VL-32B-Instruct-FP8")
    ap.add_argument("--revision", default=None, help="HF revision (commit/tag) to pin the model weights")
    ap.add_argument("--max-tokens", type=int, default=6000)
    ap.add_argument("--max-model-len", type=int, default=16384)
    ap.add_argument("--max-pixels", type=int, default=2_400_000)
    ap.add_argument("--gpu-memory-utilization", type=float, default=0.90)
    ap.add_argument("--enforce-eager", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--prompt", default="v1", choices=["v1", "v2"])
    ap.add_argument("--keys", type=Path, help="only these <doc>_p<N> keys (one per line)")
    a = ap.parse_args()

    keys = set(a.keys.read_text().split()) if a.keys else None
    prompt = PROMPT_V2 if a.prompt == "v2" else PROMPT
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
    a.out.mkdir(parents=True, exist_ok=True)
    from vllm import LLM, SamplingParams
    llm = LLM(model=a.model, revision=a.revision, max_model_len=a.max_model_len, gpu_memory_utilization=a.gpu_memory_utilization,
              limit_mm_per_prompt={"image": 1, "video": 0}, enforce_eager=a.enforce_eager,
              allowed_local_media_path=str(a.images_root.resolve()), trust_remote_code=True,
              mm_processor_kwargs={"max_pixels": a.max_pixels})
    sp = SamplingParams(temperature=0.0, max_tokens=a.max_tokens, repetition_penalty=1.05)
    raw = (a.out.parent / f"{a.out.name}-raw.jsonl").open("a", encoding="utf-8")
    B = 64
    for k in range(0, len(todo), B):
        chunk = todo[k: k + B]
        convs = [[{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"file://{img.resolve()}"}},
            {"type": "text", "text": prompt}]}] for _, _, img in chunk]
        outs = llm.chat(convs, sp)
        for (doc, n, _), o in zip(chunk, outs):
            t = o.outputs[0].text
            raw.write(json.dumps({"doc": doc, "page": n, "finish": o.outputs[0].finish_reason, "text": t},
                                 ensure_ascii=False) + "\n")
            (a.out / f"{doc}_p{n}.drbench.md").write_text(clean(t), encoding="utf-8")
        raw.flush()
        print(f"[{min(k + B, len(todo))}/{len(todo)}] done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
