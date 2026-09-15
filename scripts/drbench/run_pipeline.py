#!/usr/bin/env python
"""Dr.DocBench MVP pipeline runner.

Fetches page images from the Toolbox ``dr-docbench`` dataset, transforms them
via toolbox capabilities (document.structure.extract, math.recognize,
text.postprocess), converts the provider payload into the Acessilia canonical
tree, and writes ``<item_id>.drbench.md`` predictions from the canonical form.

Usage:
    python -m scripts.drbench.run_pipeline --split dev --sample 10
    python -m scripts.drbench.run_pipeline --item <doc_uuid>_p3
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from scripts.drbench.markdown_converter import canonical_to_drbench_md
from scripts.drbench.page_record import DrBenchPage, parse_items_metadata

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))


def _run_coro_sync(coro):
    """Run a coroutine from sync context, inside or outside an event loop.

    Notebooks (IPython) already run an event loop, where ``asyncio.run()``
    raises RuntimeError; there we execute the coroutine on a dedicated loop
    in a worker thread instead.
    """
    import asyncio
    import threading

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict = {}
    target_done = threading.Event()

    def _runner():
        loop = asyncio.new_event_loop()
        try:
            result["value"] = loop.run_until_complete(coro)
        except BaseException as e:  # noqa: BLE001 - propagate to caller
            result["error"] = e
        finally:
            loop.close()
            target_done.set()

    threading.Thread(target=_runner, daemon=True).start()
    target_done.wait()
    if "error" in result:
        raise result["error"]
    return result["value"]


def provider_payload_to_canonical(result: dict) -> dict:
    """Normalize a toolbox capability response into a canonical document.

    Reuses the same bridge the main pipeline uses for toolbox structure
    results; falls back to treating the payload as pre-structured blocks.
    """
    from backend.pipeline.canonical_builder import (
        build_canonical_document,
        sanitize_canonical_document,
    )

    if "sections" in result and result.get("schema_version"):
        # Already canonical — just sanitize.
        return sanitize_canonical_document(result)

    text = _extract_text_from_provider(result)
    document = build_canonical_document(
        {"text": text, "pages": result.get("pages", [])},
        title=result.get("title") or "Dr.DocBench page",
        language=result.get("language") or "en",
        verbosity="detailed",
    )
    return sanitize_canonical_document(document)


def _extract_text_from_provider(result: dict) -> str:
    """Best-effort plain text extraction from a toolbox structure payload.

    Supports two payload shapes:
    - Processing manifest (document.elements): flat element list with type /
      text / reading_order, sorted by reading order.
    - DoclingDocument (document.texts): legacy label/text shape.
    """
    doc = result.get("document", result)

    # Shape 1: processing manifest with flat `elements`.
    elements = doc.get("elements")
    if elements:
        parts = []
        ordered = sorted(
            elements, key=lambda e: e.get("reading_order") or 0
        )
        for e in ordered:
            text = (e.get("text") or "").strip()
            if not text:
                continue
            etype = str(e.get("type", "")).lower()
            level = int(e.get("hierarchy_level") or 1)
            if etype in ("heading", "title") or etype == "section_header":
                parts.append(f"{'#' * max(1, min(level, 6))} {text}")
            else:
                parts.append(text)
        for table in doc.get("tables") or []:
            from scripts.drbench._legacy_tables import docling_table_to_markdown
            parts.append(docling_table_to_markdown(table))
        return "\n\n".join(parts)

    # Shape 2: legacy DoclingDocument with `texts`.
    texts = doc.get("texts") or []
    parts = []
    for t in texts:
        label = str(t.get("label", "")).lower()
        text = (t.get("text") or "").strip()
        if not text:
            continue
        if "section" in label or label == "title":
            level = int(t.get("level", 1) or 1)
            parts.append(f"{'#' * max(1, min(level, 6))} {text}")
        else:
            parts.append(text)
    for table in doc.get("tables") or []:
        from scripts.drbench._legacy_tables import docling_table_to_markdown
        parts.append(docling_table_to_markdown(table))
    return "\n\n".join(parts)


def run_page(
    page: DrBenchPage,
    *,
    provider: str | None = None,
    out_dir: Path,
) -> Path | None:
    """Run the transformation pipeline for a single page."""
    import asyncio

    from backend.tools.toolbox_client import ToolboxClient, ToolboxError

    async def _execute() -> tuple[dict | None, float]:
        client = ToolboxClient(provider=provider)
        start = time.perf_counter()
        try:
            result = await client.extract_structure(file_path=page.image_path)
            elapsed = time.perf_counter() - start
            return result, elapsed
        except ToolboxError as e:
            print(f"[FAIL] {page.item_id}: {e}", file=sys.stderr)
            return None, time.perf_counter() - start
        finally:
            await client.close()

    result, elapsed = _run_coro_sync(_execute())
    if result is None:
        return None

    canonical = provider_payload_to_canonical(result)
    markdown = canonical_to_drbench_md(canonical)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / page.markdown_filename
    out_path.write_text(markdown, encoding="utf-8")
    print(f"[OK] {page.item_id} ({elapsed:.1f}s) -> {out_path.name}")
    return out_path


def discover_local_pages(images_root: Path) -> list[DrBenchPage]:
    """Discover pages from a local image tree (participant package or HF dump).

    Layout: <root>/<subject>/<document_id>/page_<N>.jpg (or .../images/page_<N>.jpg)
    """
    pages: list[DrBenchPage] = []
    for jpg in sorted(images_root.rglob("page_*.jpg")):
        doc_dir = jpg.parent
        if doc_dir.name == "images":
            doc_dir = doc_dir.parent
        item_id = f"{doc_dir.name}_p{jpg.stem.split('_')[-1]}"
        try:
            page = DrBenchPage.from_item_id(
                item_id, subject=doc_dir.parent.name
            )
        except ValueError:
            continue
        page.image_path = jpg
        pages.append(page)
    return pages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dr.DocBench pipeline runner")
    parser.add_argument("--split", default="dev", choices=["dev", "test"])
    parser.add_argument("--sample", type=int, default=10)
    parser.add_argument("--item", help="run a single item id (e.g. <uuid>_p3)")
    parser.add_argument("--provider", help="optional toolbox provider override")
    parser.add_argument(
        "--images-root", type=Path, default=None,
        help="local image tree to process instead of the Toolbox dataset "
             "(layout: <root>/<subject>/<doc_id>/images/page_<N>.jpg); "
             "e.g. var/drbench/evalai/drdocbench-evaluation-v4/images")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=REPO_ROOT / "var" / "drbench" / "predictions",
    )
    args = parser.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)

    if args.images_root is not None:
        pages = discover_local_pages(args.images_root)
        if args.item:
            pages = [p for p in pages if p.item_id == args.item]
        if args.sample and len(pages) > args.sample:
            pages = pages[: args.sample]
        if not pages:
            print(f"No pages found under {args.images_root}", file=sys.stderr)
            return 1
    else:
        from backend.tools.toolbox_dataset_tools import (
            download_drbench_page,
            toolbox_get_drbench_item,
            toolbox_list_drbench_items,
        )

        if args.item:
            item = toolbox_get_drbench_item(args.item, split=args.split)
            if item is None:
                print(f"Item {args.item} not found", file=sys.stderr)
                return 1
            items = [item]
        else:
            items = toolbox_list_drbench_items(args.split, limit=args.sample)
            if not items:
                print(
                    "No items returned — is the Toolbox running on the "
                    "expected port?",
                    file=sys.stderr,
                )
                return 1
            items = items[: args.sample]

        pages = parse_items_metadata(items)
        for page in pages:
            image_path = download_drbench_page(page.item_id, split=args.split)
            page.image_path = image_path

    ok = 0
    for page in pages:
        if page.image_path is None:
            continue
        if run_page(page, provider=args.provider, out_dir=args.out_dir):
            ok += 1

    print(f"\nDone: {ok}/{len(pages)} pages processed -> {args.out_dir}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
