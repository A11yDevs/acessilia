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

    Manifest payloads (``document.elements``) are mapped element-by-element to
    canonical blocks, so block types come from the provider's layout model
    rather than from the heuristic line parser (which mis-typed prose that
    contains inline math as ``math`` blocks). Other shapes fall back to the
    flattened-text path.
    """
    from backend.pipeline.canonical_builder import (
        build_canonical_document,
        sanitize_canonical_document,
    )

    if "sections" in result and result.get("schema_version"):
        # Already canonical — just sanitize.
        return sanitize_canonical_document(result)

    doc = result.get("document", result)
    blocks = elements_to_canonical_blocks(doc.get("elements") or [])
    if blocks:
        payload: dict = {"text": "", "pages": [{"blocks": blocks}]}
    else:
        payload = {"text": _extract_text_from_provider(result), "pages": result.get("pages", [])}
    document = build_canonical_document(
        payload,
        title=_PLACEHOLDER_TITLE,
        language=result.get("language") or "en",
        verbosity="detailed",
    )
    if document.get("title") == _PLACEHOLDER_TITLE:
        # No heading on the page: do not emit a synthetic "# ..." line.
        document["title"] = ""
    return sanitize_canonical_document(document)


_PLACEHOLDER_TITLE = "Dr.DocBench page"


def _strip_display_delims(latex: str) -> str:
    s = latex.strip()
    if s.startswith("$$") and s.endswith("$$") and len(s) > 4:
        s = s[2:-2]
    elif s.startswith("\\[") and s.endswith("\\]"):
        s = s[2:-2]
    return s.strip()


def elements_to_canonical_blocks(elements: list[dict]) -> list[dict]:
    """Map manifest elements (reading order) to canonical blocks.

    heading/title -> heading; formula -> math; table -> table (raw ``html``
    kept for the renderer); code -> code; picture -> dropped; everything else
    with text (paragraph, caption, footnote, page_header/footer, list_item…)
    -> paragraph.
    """
    blocks: list[dict] = []
    for e in sorted(elements, key=lambda e: e.get("reading_order") or 0):
        etype = str(e.get("type", "")).lower()
        text = (e.get("text") or "").strip()
        if etype == "table":
            html = _element_markdown(e)
            if html and _looks_like_html_table(html):
                blocks.append({"type": "table", "html": html})
            elif text:
                blocks.append({"type": "paragraph", "text": text})
            continue
        if not text or etype == "picture":
            continue
        if etype == "formula":
            latex = _strip_display_delims(text)
            if latex:
                blocks.append({"type": "math", "text": latex})
        elif etype in ("heading", "title", "section_header"):
            level = int(e.get("hierarchy_level") or 1)
            blocks.append({"type": "heading", "level": max(1, min(level, 6)), "text": text})
        elif etype == "code":
            blocks.append({"type": "code", "text": text})
        else:
            blocks.append({"type": "paragraph", "text": text})
    return blocks


def _looks_like_html_table(text: str) -> bool:
    return "<table" in text.lower() and "</table>" in text.lower()


def table_ast_to_html(table_ast: dict) -> str | None:
    """Render a toolbox ``table_ast`` (header/body/footer rows of cells) as HTML."""
    import html as _html

    def row_html(row: dict, header: bool) -> str:
        cells = []
        for c in row.get("cells") or []:
            if not isinstance(c, dict):
                continue
            tag = "th" if header or c.get("header") else "td"
            attrs = "".join(
                f' {k}="{int(c[k])}"' for k in ("rowspan", "colspan")
                if isinstance(c.get(k), int) and c[k] > 1
            )
            cells.append(f"<{tag}{attrs}>{_html.escape(str(c.get('text', '')))}</{tag}>")
        return f"<tr>{''.join(cells)}</tr>" if cells else ""

    rows = [row_html(r, True) for r in table_ast.get("header") or []]
    rows += [row_html(r, False) for r in table_ast.get("body") or []]
    rows += [row_html(r, False) for r in table_ast.get("footer") or []]
    rows = [r for r in rows if r]
    return f"<table>{''.join(rows)}</table>" if rows else None


def _element_markdown(e: dict) -> str | None:
    """Render one manifest element as Dr.DocBench markdown (None = skip)."""
    text = (e.get("text") or "").strip()
    etype = str(e.get("type", "")).lower()
    if etype == "table":
        if text and _looks_like_html_table(text):
            return text
        ast = (e.get("metadata") or {}).get("table_ast")
        if isinstance(ast, dict):
            html = table_ast_to_html(ast)
            if html:
                return html
        return text or None
    if not text:
        return None
    if etype == "formula":
        if text.startswith("$"):
            return text
        return f"$${text}$$"
    if etype in ("heading", "title", "section_header"):
        level = int(e.get("hierarchy_level") or 1)
        return f"{'#' * max(1, min(level, 6))} {text}"
    return text


def _extract_text_from_provider(result: dict) -> str:
    """Best-effort markdown extraction from a toolbox structure payload.

    Supports two payload shapes:
    - Processing manifest (document.elements): flat element list with type /
      text / metadata / reading_order, sorted by reading order. Tables become
      HTML (from ``metadata.table_ast`` when the provider gives no HTML text)
      and formulas are wrapped in ``$$``.
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
            md = _element_markdown(e)
            if md:
                parts.append(md)
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


def provider_blocks(result: dict) -> list[dict]:
    """Flatten a toolbox structure payload into reading-ordered blocks with bbox.

    This is the persisted "canonical tree" consumed by block-level adjudication
    (Tree Differ). Coordinates are in the provider's page space; ``page_size``
    is stored on each block so consumers can normalise.
    """
    doc = result.get("document", result)
    sizes: dict[int, tuple[float | None, float | None]] = {}
    pages = doc.get("pages") or result.get("pages") or []
    if isinstance(pages, dict):
        pages = list(pages.values())
    for p in pages:
        if not isinstance(p, dict):
            continue
        no = p.get("page_number", p.get("page_no"))
        size = p.get("size") or p
        if no is not None:
            sizes[int(no)] = (size.get("width"), size.get("height"))

    blocks: list[dict] = []
    for e in sorted(doc.get("elements") or [], key=lambda e: e.get("reading_order") or 0):
        prov = (e.get("provenance") or [{}])[0]
        bbox = prov.get("bbox") or {}
        page_no = prov.get("page_number") or e.get("page_number")
        w, h = sizes.get(int(page_no), (None, None)) if page_no is not None else (None, None)
        blocks.append({
            "id": e.get("id"),
            "type": str(e.get("type", "unknown")).lower(),
            "raw_label": e.get("raw_label"),
            "reading_order": e.get("reading_order"),
            "level": e.get("hierarchy_level"),
            "text": e.get("text"),
            "markdown": _element_markdown(e),
            "bbox": [bbox.get("left"), bbox.get("top"), bbox.get("right"), bbox.get("bottom")]
            if bbox else None,
            "coord_origin": bbox.get("coord_origin") if bbox else None,
            "page": page_no,
            "page_size": [w, h],
        })
    return blocks


def run_page(
    page: DrBenchPage,
    *,
    provider: str | None = None,
    out_dir: Path,
    save_raw: bool = False,
) -> Path | None:
    """Run the transformation pipeline for a single page."""
    import asyncio
    import json

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
    stem = out_path.name[: -len(".drbench.md")] if out_path.name.endswith(".drbench.md") else out_path.stem
    (out_dir / f"{stem}.blocks.json").write_text(
        json.dumps(provider_blocks(result), ensure_ascii=False), encoding="utf-8"
    )
    if save_raw:
        (out_dir / f"{stem}.provider.json").write_text(
            json.dumps(result, ensure_ascii=False), encoding="utf-8"
        )
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
    parser.add_argument(
        "--save-raw", action="store_true",
        help="also write the raw toolbox payload as <item>.provider.json")
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
        if run_page(page, provider=args.provider, out_dir=args.out_dir,
                    save_raw=args.save_raw):
            ok += 1

    print(f"\nDone: {ok}/{len(pages)} pages processed -> {args.out_dir}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
