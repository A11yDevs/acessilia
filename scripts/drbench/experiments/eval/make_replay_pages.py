#!/usr/bin/env python3
"""Gera o ``pages.json`` de um spec de replay a partir do dataset do Dr.DocBench.

O replay exige uma seleção explícita de páginas (``pages.json``) com os campos
``id``, ``subject``, ``document_id``, ``page``, ``batch`` e ``image`` (relativo a
``data/hf``). Este script produz essa seleção a partir de uma raiz de imagens,
para que os specs versionados em ``eval/specs/`` sejam reproduzíveis.

Uso:
  python make_replay_pages.py --images-root <WS>/data/hf/dev --out dev986-pages.json
  python make_replay_pages.py --images-root <WS>/data/evalai/drdocbench-evaluation-v4/images \\
      --out test509-pages.json --split evalai
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

PAGE_RE = re.compile(r"page_(\d+)\.(?:jpg|jpeg|png)$", re.I)


def collect(images_root: Path, split: str) -> list[dict]:
    """Coleta as páginas de ``images_root`` no formato do replay.

    Espera o layout ``<SUBJECT>/<document_id>/images/page_<N>.jpg`` (dev) ou
    ``<document_id>/images/page_<N>.jpg`` (evalai).
    """
    pages: list[dict] = []
    for image in sorted(images_root.rglob("page_*.*")):
        match = PAGE_RE.search(image.name)
        if not match:
            continue
        page_no = int(match.group(1))
        doc_dir = image.parent.parent
        document_id = doc_dir.name
        subject = doc_dir.parent.name if doc_dir.parent != images_root else ""
        if not document_id:
            continue
        pages.append({
            "id": f"{document_id}_p{page_no}",
            "subject": subject or "UNKNOWN",
            "document_id": document_id,
            "page": page_no,
            "batch": 1,
            "image": f"{split}/{subject}/{document_id}/images/{image.name}"
            if subject
            else f"{split}/{document_id}/images/{image.name}",
        })
    return pages


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images-root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--split", default="dev", help="prefixo do caminho relativo a data/hf")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    pages = collect(args.images_root, args.split)
    if args.limit:
        pages = pages[: args.limit]
    if not pages:
        raise SystemExit(f"nenhuma página encontrada em {args.images_root}")

    # validate_pages exige ids únicos e campos válidos.
    from scripts.drbench.experiments.eval.frozen_inputs import validate_pages

    validate_pages(pages)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(pages, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(pages)} páginas -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
