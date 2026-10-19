#!/usr/bin/env python3
"""Replay the last, model-free stage of the best Dr.DocBench submission
(hyb-v29-judge2-televm-adf-tj3-20261009, EvalAI Overall 71.01) and compare
its predictions.jsonl byte for byte with the frozen one.

usage: replay_best.py INPUTS_DIR CODE_DIR FROZEN_JSONL OUT_DIR

INPUTS_DIR (built on the cluster by collect_inputs.sh):
  v29-adf/<doc>_p<N>.drbench.md     base candidate  (runs/evalai/differ-v29-adf-20261009/predictions)
  televm-fb/<doc>_p<N>.drbench.md   Tele candidate  (runs/evalai/teleocr-up2m2-vm-fb-adf-20261009/predictions)
  judge-televm.jsonl                Qwen3-VL-32B judge, v29-adf vs Tele-vm-fb (LOOP #45, job 34458)
  judge-tele.jsonl                  earlier judge, v29-pn vs teleocr-page (LOOP #44)
  pnpos.json                        page-number position per page, or tele-raw.jsonl + dots-raw.jsonl to rebuild it
CODE_DIR: scripts/drbench/experiments/pages of the tag drbench-2026-snapshot.

Stages, as recorded in docs/drbench/experiments/LOOP.md:
  #45 page choice: Tele when judge-televm pB > 0.5; for pages judge-televm did not
      judge, Tele when judge-tele pB > 0.2; otherwise the v29-adf page.
  #51 tail-join tj3: pnpos.py, then tailjoin3.py SRC OUT POS 50 3 hdr.
  submission: build_submission_manifest.py row format, in the frozen row order.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

NEW_JUDGE_MIN = 0.5
OLD_JUDGE_MIN = 0.2
TAILJOIN_ARGS = ["50", "3", "hdr"]
EXPECTED_TELE_PAGES = 87


def _judge(path: Path) -> dict[str, float]:
    return {r["key"]: r["pB"] for r in map(json.loads, path.read_text(encoding="utf-8").splitlines())}


def main() -> int:
    inputs, code, frozen, out = map(Path, sys.argv[1:5])
    rows = [json.loads(line) for line in frozen.read_text(encoding="utf-8").splitlines()]
    keys = [f"{r['document_id']}_p{r['page']}" for r in rows]

    new, old = _judge(inputs / "judge-televm.jsonl"), _judge(inputs / "judge-tele.jsonl")
    hyb = out / "hyb-judge2"
    hyb.mkdir(parents=True, exist_ok=True)
    tele = 0
    for k in keys:
        use_tele = new[k] > NEW_JUDGE_MIN if k in new else old.get(k, 0.0) > OLD_JUDGE_MIN
        tele += use_tele
        src = inputs / ("televm-fb" if use_tele else "v29-adf") / f"{k}.drbench.md"
        shutil.copyfile(src, hyb / src.name)
    print(f"page choice: {tele} Tele pages (recorded: {EXPECTED_TELE_PAGES})", flush=True)

    pos = inputs / "pnpos.json"
    if not pos.exists():
        pos = out / "pnpos.json"
        subprocess.run([sys.executable, str(code / "pnpos.py"), str(inputs / "tele-raw.jsonl"),
                        str(inputs / "dots-raw.jsonl"), str(pos)], check=True, env={"PYTHONPATH": str(code)})
    tj3 = out / "tj3"
    subprocess.run([sys.executable, str(code / "tailjoin3.py"), str(hyb), str(tj3), str(pos), *TAILJOIN_ARGS],
                   check=True)

    replay = out / "predictions.jsonl"
    replay.write_text("".join(
        json.dumps({"subject": r["subject"], "document_id": r["document_id"], "page": r["page"],
                    "markdown": (tj3 / f"{k}.drbench.md").read_text(encoding="utf-8")}, ensure_ascii=False) + "\n"
        for r, k in zip(rows, keys)), encoding="utf-8")

    got = hashlib.sha256(replay.read_bytes()).hexdigest()
    want = hashlib.sha256(frozen.read_bytes()).hexdigest()
    if got == want:
        print(f"IDENTICAL: {replay} sha256 {got}")
        return 0
    differ = [k for k, a, b in zip(keys, map(json.loads, replay.read_text(encoding="utf-8").splitlines()), rows)
              if a["markdown"] != b["markdown"]]
    print(f"DIFFERENT: sha256 {got} != {want}; {len(differ)}/{len(rows)} pages differ, e.g. {differ[:5]}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
