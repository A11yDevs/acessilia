#!/usr/bin/env python3
"""Fusão via lib docstruct sobre payloads blocks.json (experimento de integração).

Porta do fluxo do ``tree_differ_v2.py`` usando a biblioteca pura
``docstruct.fusion`` (merge_blocks + FusionPolicy preset) em vez do script de
referência. Produz ``<id>.drbench.md`` no mesmo formato, para avaliação com o
protocolo oficial md2md.

Objetivo: verificar que a lib reproduz o comportamento do script — mesmos
outputs (diff vazio) ou score compatível no dev-986 (≈ 75.9 do v12-rh3-pc4).

Usage:
  python -m scripts.drbench.experiments.differ.lib_fuse \
      --docling runs/dev-full/docling-lib/predictions \
      --mineru runs/dev-full/mineru-lib/predictions \
      --out runs/dev-full/lib-fuse-v12/predictions --policy v12
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

from docstruct.fusion import merge_blocks
from docstruct.fusion.types import DiffBlock
from docstruct.policy import FusionPolicy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tree_differ_v2 import doc_id_of, load_blocks, running_texts  # noqa: E402


def policy_by_name(name: str) -> FusionPolicy:
    if name == "v12":
        return FusionPolicy.drbench_v12()
    if name == "v13":
        return FusionPolicy.drbench_v13()
    if name == "default":
        return FusionPolicy()
    raise SystemExit(f"unknown policy: {name} (use v12|v13|default)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docling", type=Path, required=True)
    ap.add_argument("--mineru", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--policy", default="v12", help="v12|v13|default")
    ap.add_argument("--min-len", type=int, default=0)
    ap.add_argument("--garbage-frac", type=float, default=0.0)
    ap.add_argument("--decor-wins", action="store_true", default=True)
    ap.add_argument("--no-decor-wins", dest="decor_wins", action="store_false")
    ap.add_argument("--drop-docling", default="group+unknown")
    ap.add_argument("--drop-mineru", default="")
    a = ap.parse_args()

    policy = policy_by_name(a.policy)
    drop_d = frozenset(
        t.strip().lower() for t in a.drop_docling.replace(",", "+").split("+") if t.strip()
    )
    drop_m = frozenset(
        t.strip().lower() for t in a.drop_mineru.replace(",", "+").split("+") if t.strip()
    )

    ids = sorted(
        {p.name for p in a.docling.glob("*.drbench.md")}
        & {p.name for p in a.mineru.glob("*.drbench.md")}
    )
    running: dict[str, frozenset[str]] = {}
    if policy.running_heads:
        running = running_texts(ids, a.docling, a.mineru, drop_d, drop_m, min_pages=3)
        print(
            f"running heads: {sum(len(v) for v in running.values())} texts "
            f"in {sum(1 for v in running.values() if v)} docs"
        )

    a.out.mkdir(parents=True, exist_ok=True)
    rows, tot = [], Counter()
    for name in ids:
        stem = name.removesuffix(".drbench.md")
        D = load_blocks(a.docling / f"{stem}.blocks.json", drop_d)
        m_pics: list = []
        M = load_blocks(a.mineru / f"{stem}.blocks.json", drop_m, m_pics)
        if D is None or M is None:
            tot["fallback-no-blocks"] += 1
            # Sem blocks.json não há porta para a lib: copia o provider com
            # mais texto (comportamento degradado, contabilizado).
            doc_md = (a.docling / name).read_text(encoding="utf-8")
            min_md = (a.mineru / name).read_text(encoding="utf-8")
            (a.out / name).write_text(
                doc_md if len(doc_md) >= len(min_md) else min_md, encoding="utf-8"
            )
            continue

        d_blocks = [_row_to_diff(b) for b in D]
        m_blocks = [_row_to_diff(b) for b in M]
        out, stats = merge_blocks(
            d_blocks,
            m_blocks,
            policy,
            min_len=a.min_len,
            garbage_frac=a.garbage_frac,
            m_pics=m_pics,
            running=running.get(doc_id_of(stem), frozenset()),
            decor_wins=a.decor_wins,
        )
        if not out:
            # Fallback do script de referência: quando a fusão não produz
            # nada (ex.: suppress removeu tudo numa página picture-only),
            # usa o markdown mais longo via split_blocks.
            from tree_differ_v2 import norm, split_blocks

            doc_md = (a.docling / name).read_text(encoding="utf-8")
            min_md = (a.mineru / name).read_text(encoding="utf-8")
            out = split_blocks(
                doc_md if len(norm(doc_md)) >= len(norm(min_md)) else min_md
            )
            stats["fallback-longer"] += 1
        (a.out / name).write_text("\n\n".join(out) + "\n", encoding="utf-8")
        tot.update(stats)
        rows.append({"item": stem, "n_docling": len(D), "n_mineru": len(M), "n_out": len(out), **dict(stats)})

    keys = ["item", "n_docling", "n_mineru", "n_out"] + sorted(tot)
    with (a.out / "decisions.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, restval=0)
        w.writeheader()
        w.writerows(rows)
    print(f"pages={len(ids)} policy={a.policy} min_len={a.min_len}")
    for k, v in sorted(tot.items()):
        print(f"  {k}: {v}")
    return 0


def _row_to_diff(b: dict) -> DiffBlock:
    """Linha do blocks.json (formato tree_differ_v2) → lib DiffBlock.

    ``load_blocks`` já normaliza o bbox ao quadrado unitário (com flip
    BOTTOMLEFT) e classifica o kind — exatamente o contrato do DiffBlock.
    """
    return DiffBlock(
        md=b["md"],
        kind=b["kind"],
        box=b["box"],
        text=b["text"],
        type=b.get("type", "text"),
    )


if __name__ == "__main__":
    raise SystemExit(main())
