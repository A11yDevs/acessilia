#!/usr/bin/env python
"""Re-render Dr.DocBench predictions from saved toolbox payloads (no inference).

Input : a dir of <item_id>.provider.json (written by run_pipeline --save-raw or
        replay_mineru_manifests.py)
Output: <item_id>.drbench.md + <item_id>.blocks.json in --out, using the current
        scripts.drbench.run_pipeline mapping (provider_payload_to_canonical).

Run with the ACESSILIA venv from repos/acessilia:
  .venv/bin/python /raid/.../scripts/rerender_from_payloads.py --src runs/dev/mineru-raw \
      --out runs/dev/mineru-v2-20260916/predictions
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ACC = Path("/raid/user_marcospaulo/drdocbench/repos/acessilia")
sys.path.insert(0, str(ACC))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)

    from scripts.drbench.markdown_converter import canonical_to_drbench_md
    from scripts.drbench.run_pipeline import provider_blocks, provider_payload_to_canonical

    n = fail = 0
    for p in sorted(a.src.glob("*.provider.json")):
        iid = p.name[: -len(".provider.json")]
        try:
            result = json.load(p.open())
            md = canonical_to_drbench_md(provider_payload_to_canonical(result))
            (a.out / f"{iid}.drbench.md").write_text(md, encoding="utf-8")
            (a.out / f"{iid}.blocks.json").write_text(
                json.dumps(provider_blocks(result), ensure_ascii=False), encoding="utf-8"
            )
            n += 1
        except Exception as exc:  # noqa: BLE001 - report and continue
            fail += 1
            print(f"[FAIL] {iid}: {exc!r}", file=sys.stderr)
    print(f"rendered {n} pages -> {a.out} (failed {fail})")
    return 0 if n and not fail else 1


if __name__ == "__main__":
    raise SystemExit(main())
