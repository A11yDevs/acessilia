#!/usr/bin/env python3
"""VLM reading-order adjudicator (v24).

Input: `tree_differ_v2 --dump-order` JSONL ({page, keys, boxes, text, xy}). The page image is rendered
with the blocks' boxes numbered in the Differ's (MinerU skeleton) order; the VLM returns the natural
reading order as a list of numbers.
Outputs (tree_differ_v2 --order-adjudications, {page, order: [[side, idx], ...]}):
  <prefix>-vlm.jsonl  VLM permutation as is (missing numbers appended in skeleton order)
  <prefix>-sel.jsonl  VLM only as a judge between skeleton order and XY-cut (closest by Kendall tau);
                      written only for pages where XY-cut wins.
  <prefix>-raw.jsonl  raw answers (reuse with --select-only).
"""
import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

DEV = Path(__file__).resolve().parent.parent / "data" / "hf" / "dev"

ORDER_PROMPT = """The image is a document page. Its content blocks are outlined in red and labelled with numbers 1..{n}
(the numbering is only a proposal and may be wrong).
Give the natural human reading order of ALL {n} blocks (e.g. columns top-to-bottom then left-to-right, titles before
their text, captions next to their figure/table).
Answer ONLY with the block numbers in reading order, comma-separated, each number exactly once."""


def page_image(page: str, dirs: dict, test: bool) -> Path | None:
    m = re.match(r"(.+)_p(\d+)$", page)
    d = m and dirs.get(m.group(1))
    p = d and (d if test else d / "images") / f"page_{int(m.group(2))}.jpg"
    return p if p and p.exists() else None


def render(img: Path, boxes: list, out: Path, max_side: int):
    with Image.open(img) as im:
        im = im.convert("RGB")
        s = min(1.0, max_side / max(im.size))
        if s < 1.0:
            im = im.resize((int(im.size[0] * s), int(im.size[1] * s)))
    W, H = im.size
    dr = ImageDraw.Draw(im)
    fs = max(14, int(min(W, H) * 0.022))
    try:
        font = ImageFont.load_default(size=fs)
    except TypeError:
        font = ImageFont.load_default()
    for n, b in enumerate(boxes, 1):
        x0, y0, x1, y1 = b[0] * W, b[1] * H, b[2] * W, b[3] * H
        dr.rectangle((x0, y0, x1, y1), outline=(230, 0, 0), width=max(2, fs // 8))
        lab = str(n)
        tw, th = dr.textbbox((0, 0), lab, font=font)[2:]
        lx, ly = max(0, x0 - tw - 6) if x0 > tw + 6 else x0, max(0, y0)
        dr.rectangle((lx, ly, lx + tw + 6, ly + th + 6), fill=(230, 0, 0))
        dr.text((lx + 3, ly + 2), lab, fill=(255, 255, 255), font=font)
    im.save(out, quality=90)


def parse(t: str, n: int) -> list[int]:
    seen, perm = set(), []
    for x in re.findall(r"\d+", t or ""):
        k = int(x) - 1
        if 0 <= k < n and k not in seen:
            seen.add(k)
            perm.append(k)
    return perm


def tau(p: list[int], q: list[int]) -> float:
    """Kendall tau between two orders (lists of the same items)."""
    pos = {x: r for r, x in enumerate(q)}
    r = [pos[x] for x in p]
    n = len(r)
    if n < 2:
        return 1.0
    c = sum(1 if r[i] < r[j] else -1 for i in range(n) for j in range(i + 1, n))
    return c / (n * (n - 1) / 2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--order", type=Path, required=True, help="tree_differ_v2 --dump-order JSONL")
    ap.add_argument("--out-prefix", type=Path, required=True)
    ap.add_argument("--images-dir", type=Path, required=True, help="where rendered pages go")
    ap.add_argument("--images-root", type=Path, default=None, help="EvalAI test layout (default: HF dev layout)")
    ap.add_argument("--model", default="Qwen/Qwen3-VL-32B-Instruct-FP8")
    ap.add_argument("--max-side", type=int, default=1600)
    ap.add_argument("--max-model-len", type=int, default=8192)
    ap.add_argument("--gpu-memory-utilization", type=float, default=0.90)
    ap.add_argument("--tensor-parallel-size", type=int, default=1)
    ap.add_argument("--enforce-eager", action="store_true")
    ap.add_argument("--min-cover", type=float, default=0.8, help="min fraction of blocks the VLM must list")
    ap.add_argument("--select-only", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    pages = [json.loads(l) for l in a.order.read_text(encoding="utf-8").splitlines() if l.strip()]
    if a.limit:
        pages = pages[: a.limit]
    raw_path = Path(f"{a.out_prefix}-raw.jsonl")
    if not (a.select_only or raw_path.exists() and raw_path.stat().st_size > 0):
        dirs = {p.name: p for p in a.images_root.glob("*/*/")} if a.images_root else \
            {p.name: p for p in DEV.glob("*/*/") if (p / "images").is_dir()}
        a.images_dir.mkdir(parents=True, exist_ok=True)
        todo = []
        for r in pages:
            img = page_image(r["page"], dirs, bool(a.images_root))
            if img is None:
                continue
            out = a.images_dir / f"{r['page']}.jpg"
            if not out.exists():
                render(img, r["boxes"], out, a.max_side)
            todo.append((r, out))
        print(f"order: {len(todo)}/{len(pages)} pages rendered -> {a.images_dir}", flush=True)
        from vllm import LLM, SamplingParams
        llm = LLM(model=a.model, max_model_len=a.max_model_len, gpu_memory_utilization=a.gpu_memory_utilization,
                  tensor_parallel_size=a.tensor_parallel_size, limit_mm_per_prompt={"image": 1, "video": 0},
                  enforce_eager=a.enforce_eager, allowed_local_media_path=str(a.images_dir.resolve()),
                  trust_remote_code=True)
        sp = SamplingParams(temperature=0.0, max_tokens=512)
        convs = [[{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"file://{out.resolve()}"}},
            {"type": "text", "text": ORDER_PROMPT.format(n=len(r["keys"]))}]}] for r, out in todo]
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = raw_path.with_suffix(".partial")
        with tmp.open("w", encoding="utf-8") as f:
            B = 256
            for k in range(0, len(convs), B):
                for (r, _), o in zip(todo[k: k + B], llm.chat(convs[k: k + B], sp)):
                    f.write(json.dumps({"page": r["page"], "answer": o.outputs[0].text}, ensure_ascii=False) + "\n")
                f.flush()
                print(f"[{min(k + B, len(convs))}/{len(convs)}] ordered", flush=True)
        tmp.rename(raw_path)

    ans = {d["page"]: d["answer"] for d in map(json.loads, raw_path.read_text(encoding="utf-8").splitlines())}
    st = Counter()
    with open(f"{a.out_prefix}-vlm.jsonl", "w", encoding="utf-8") as fv, \
            open(f"{a.out_prefix}-sel.jsonl", "w", encoding="utf-8") as fs:
        for r in pages:
            if r["page"] not in ans:
                st["no-answer"] += 1
                continue
            n = len(r["keys"])
            p = parse(ans[r["page"]], n)
            if len(p) < a.min_cover * n:
                st["low-cover"] += 1
                continue
            p += [k for k in range(n) if k not in set(p)]
            ident = list(range(n))
            if p == ident:
                st["vlm=skeleton"] += 1
            else:
                fv.write(json.dumps({"page": r["page"], "order": [r["keys"][k] for k in p]}) + "\n")
                st["vlm-reorder"] += 1
            xy = r["xy"]
            if xy != ident and tau(p, xy) > tau(p, ident):
                fs.write(json.dumps({"page": r["page"], "order": [r["keys"][k] for k in xy]}) + "\n")
                st["sel-xy"] += 1
            else:
                st["sel-skeleton"] += 1
    print(f"order decisions: {dict(st)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
