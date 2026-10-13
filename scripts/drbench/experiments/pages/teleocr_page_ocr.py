#!/usr/bin/env python3
"""Two-stage whole-page parse with TeleOCR (ex NaviDC-OCR, Qwen2.5-VL 1.2B; vLLM) -> <doc>_p<N>.drbench.md, another
independent tree source. Re-implements the public TeleOCR pipeline (github caipeng328/TeleOCR) on our vLLM:
  1. layout: page resized to 1036x1036, "Analyze the image layout." -> lines <box:x1 y1 x2 y2><label:type><angle>
     (coords 0..1000, reading order);
  2. each block cropped from the full-resolution page (rotated by its angle) and recognised with the per-type prompt
     (tables come back as OTSL -> HTML).
Running header / footer / page number are rendered last (GT convention). Raw outputs go to <out>-raw.jsonl;
--from-raw re-renders without a GPU.

  teleocr_page_ocr.py --images-root R --out OUT [--only-gt R] [--limit N]
  teleocr_page_ocr.py --from-raw RAW.jsonl --out OUT
"""
import argparse
import html
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vlm_page_ocr import pages  # noqa: E402

SYSTEM = "You are a helpful assistant."
LAYOUT = "\nAnalyze the image layout."
PROMPTS = {
    "text": "\nPlease output the text content from the image.",
    "table": "\nThis is the image of a table. Please output the table in OTSL format.",
    "equation": "\nPlease write out the expression of the formula in the image using LaTeX format.",
    "code": "\nThe image contains a code snippet, please output the parsing result.",
}
SKIP = {"image", "list", "equation_block", "char", "seal"}  # not recognised (pictures; containers of other blocks)
HF = {"header", "footer", "page_number", "aside_text"}
LINE = re.compile(r"^<box:([\d\s]+)><label:(\w+)><([^>]+)>$")
ANGLE = {"up": 0, "right": 90, "down": 180, "left": 270}


def parse_layout(t: str):
    out = []
    for line in t.split("\n"):
        m = LINE.match(line.strip())
        if not m:
            continue
        nums = list(map(int, m.group(1).split()))
        if len(nums) < 4 or len(nums) % 2 or any(c < 0 or c > 1000 for c in nums):
            continue
        xs, ys = nums[0::2], nums[1::2]
        ang = next((v for k, v in ANGLE.items() if k in m.group(3)), 0)
        out.append({"type": m.group(2).lower(), "bbox": [min(xs) / 1000, min(ys) / 1000, max(xs) / 1000, max(ys) / 1000],
                    "angle": ang})
    return out


def otsl2html(t: str) -> str:
    rows, cur = [], []
    for tok, txt in re.findall(r"<(fcel|ecel|lcel|ucel|xcel|nl)>([^<]*)", t):
        if tok == "nl":
            rows.append(cur)
            cur = []
        else:
            cur.append((tok, txt.strip()))
    if cur:
        rows.append(cur)
    if not rows:
        return t
    W = max(len(r) for r in rows)
    g = [r + [("ecel", "")] * (W - len(r)) for r in rows]
    s = ["<table>"]
    for i, r in enumerate(g):
        s.append("<tr>")
        for j, (tok, txt) in enumerate(r):
            if tok not in ("fcel", "ecel"):
                continue
            cs = 1
            while j + cs < W and g[i][j + cs][0] in ("lcel", "xcel"):
                cs += 1
            rs = 1
            while i + rs < len(g) and g[i + rs][j][0] in ("ucel", "xcel"):
                rs += 1
            at = (f' rowspan="{rs}"' if rs > 1 else "") + (f' colspan="{cs}"' if cs > 1 else "")
            s.append(f"<td{at}>{html.escape(txt, quote=False)}</td>")
        s.append("</tr>")
    s.append("</table>")
    return "".join(s)


def render(blocks) -> str:
    body, tail = [], []
    for b in blocks:
        c, t = b["type"], (b.get("text") or "").strip()
        if c in SKIP or not t:
            continue
        if c == "table":
            t = otsl2html(t) if "<fcel>" in t or "<ecel>" in t else t
        elif c == "equation":
            t = t.strip("$").strip()
            t = f"$$\n{t}\n$$"
        elif c == "title" and not t.startswith("#"):
            t = "# " + t
        (tail if c in HF else body).append(t)
    return "\n\n\n\n\n".join(body + tail) + "\n"


def crop(img, b, pad=0.0):
    from PIL import Image
    W, H = img.size
    x1, y1, x2, y2 = b["bbox"]
    if pad:  # widen the box by pad * page height on every side (tight boxes clip glyph edges)
        d = pad
        x1, y1, x2, y2 = max(0, x1 - d * H / W), max(0, y1 - d), min(1, x2 + d * H / W), min(1, y2 + d)
    c = img.crop((int(x1 * W), int(y1 * H), max(int(x2 * W), int(x1 * W) + 1), max(int(y2 * H), int(y1 * H) + 1)))
    if b["angle"] in (90, 180, 270):
        c = c.rotate(b["angle"], expand=True)
    if max(c.size) / min(c.size) > 50:  # pad extreme aspect ratios
        w, h = c.size
        nw, nh = (w, math.ceil(w / 50)) if w > h else (math.ceil(h / 50), h)
        n = Image.new("RGB", (nw, nh), (255, 255, 255))
        n.paste(c, ((nw - w) // 2, (nh - h) // 2))
        c = n
    if min(c.size) < 28:
        s = 28 / min(c.size)
        c = c.resize((math.ceil(c.width * s), math.ceil(c.height * s)), Image.Resampling.BICUBIC)
    return c


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images-root", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--only-gt", type=Path)
    ap.add_argument("--from-raw", type=Path)
    ap.add_argument("--keys", type=Path, help="only these <doc>_p<N> pages")
    ap.add_argument("--model", default="XingChen-AGI/TeleOCR")
    ap.add_argument("--revision", default=None, help="HF revision (commit/tag) to pin the model weights")
    ap.add_argument("--max-tokens", type=int, default=4096)
    ap.add_argument("--max-model-len", type=int, default=16384)
    ap.add_argument("--gpu-memory-utilization", type=float, default=0.85)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--batch", type=int, default=32, help="pages per layout+recognition round")
    ap.add_argument("--pad", type=float, default=0.0, help="crop margin, fraction of page height")
    ap.add_argument("--ngram", type=int, default=0, help="ban repeated N-grams (official client: no_repeat_ngram_size 100)")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    if a.from_raw:
        n = 0
        for r in map(json.loads, a.from_raw.open(encoding="utf-8")):
            (a.out / f"{r['doc']}_p{r['page']}.drbench.md").write_text(render(r["blocks"]), encoding="utf-8")
            n += 1
        print(f"rendered {n}")
        return 0

    keys = set(a.keys.read_text().split()) if a.keys else None
    todo = []
    for doc, n, img in pages(a.images_root):
        if keys is not None and f"{doc}_p{n}" not in keys:
            continue
        if a.only_gt and not list(a.only_gt.glob(f"*/{doc}/mds/{doc}_{n}.md")):
            continue
        if not (a.out / f"{doc}_p{n}.drbench.md").exists():
            todo.append((doc, n, img))
    if a.limit:
        todo = todo[: a.limit]
    print(f"pages to do: {len(todo)}", flush=True)
    if not todo:
        return 0
    import os
    os.environ["VLLM_ENABLE_V1_MULTIPROCESSING"] = "0"  # the patch below must live in the engine process
    from PIL import Image
    from vllm import LLM, SamplingParams
    import vllm.model_executor.models.qwen2_5_vl as q25

    # TeleOCR = Qwen2.5-VL vision + Qwen3-style LM (head_dim 128, q/k norm); its vLLM plugin only swaps this
    _init = q25.init_vllm_registered_model
    q25.init_vllm_registered_model = lambda **kw: _init(**{**kw, "architectures": ["Qwen3ForCausalLM"]},
                                                       hf_config=kw["vllm_config"].model_config.hf_config.get_text_config())
    from vllm.model_executor.models.deepseek_ocr import NGramPerReqLogitsProcessor
    llm = LLM(model=a.model, revision=a.revision, max_model_len=a.max_model_len, gpu_memory_utilization=a.gpu_memory_utilization,
              limit_mm_per_prompt={"image": 1, "video": 0}, enforce_eager=True,
              **({"logits_processors": [NGramPerReqLogitsProcessor]} if a.ngram else {}))
    ng = dict(extra_args=dict(ngram_size=a.ngram, window_size=a.max_model_len)) if a.ngram else {}
    sp_lay = SamplingParams(temperature=0.0, max_tokens=a.max_tokens, **ng)
    sp_txt = SamplingParams(temperature=0.0, max_tokens=a.max_tokens, presence_penalty=1.0, frequency_penalty=0.05, **ng)
    sp_tab = SamplingParams(temperature=0.0, max_tokens=a.max_tokens, presence_penalty=1.0, frequency_penalty=0.005, **ng)

    def conv(im, p):
        return [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": [{"type": "image_pil", "image_pil": im}, {"type": "text", "text": p}]}]

    raw = (a.out.parent / f"{a.out.name}-raw.jsonl").open("a", encoding="utf-8")
    for k in range(0, len(todo), a.batch):
        chunk = todo[k: k + a.batch]
        ims = [Image.open(img).convert("RGB") for _, _, img in chunk]
        outs = llm.chat([conv(im.resize((1036, 1036), Image.Resampling.BICUBIC), LAYOUT) for im in ims], sp_lay,
                        use_tqdm=False)
        lays = [parse_layout(o.outputs[0].text) for o in outs]
        lfin = [o.outputs[0].finish_reason for o in outs]
        jobs, sps, idx = [], [], []
        for pi, (im, bl) in enumerate(zip(ims, lays)):
            for bi, b in enumerate(bl):
                if b["type"] in SKIP:
                    continue
                p = PROMPTS.get(b["type"], PROMPTS["text"])
                jobs.append(conv(crop(im, b, a.pad), p))
                sps.append(sp_tab if b["type"] == "table" else sp_txt)
                idx.append((pi, bi))
        if jobs:
            for (pi, bi), o in zip(idx, llm.chat(jobs, sps, use_tqdm=False)):
                lays[pi][bi]["text"] = o.outputs[0].text
                lays[pi][bi]["finish"] = o.outputs[0].finish_reason
        for (doc, n, _), bl, f in zip(chunk, lays, lfin):
            raw.write(json.dumps({"doc": doc, "page": n, "layout_finish": f, "blocks": bl}, ensure_ascii=False) + "\n")
            (a.out / f"{doc}_p{n}.drbench.md").write_text(render(bl), encoding="utf-8")
        raw.flush()
        print(f"[{min(k + a.batch, len(todo))}/{len(todo)}] done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
