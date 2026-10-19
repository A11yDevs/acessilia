"""Dr.DocBench (DocInsights 2026): one page per item, GT as markdown.

Local tree, as released on HuggingFace (2077AIDataFoundation/DrDocBench):

    <root>/<subject>/<document_id>/images/page_<N>.jpg
    <root>/<subject>/<document_id>/mds/<document_id>_<N>.md   (dev only)

The EvalAI test package has no ``images/`` level; both layouts are read.
Port of ``scripts/drbench/{download_gt,build_submission,page_record}.py``
(tag drbench-2026-snapshot).
"""

from __future__ import annotations

import json
import shutil
import sys
import zipfile
from pathlib import Path

from scripts.bench import toolbox
from scripts.bench.datasets.base import BenchPage

DATASET_ID = "dr-docbench"
HF_REPO = "2077AIDataFoundation/DrDocBench"


class DrDocBench:
    name = "drdocbench"

    def download(self, split: str, root: Path, limit: int | None = None) -> int:
        """Page images from the Toolbox; GT markdown from the Toolbox, else HuggingFace."""
        written = 0
        for raw in toolbox.list_items(DATASET_ID, split, limit):
            item_id = raw.get("id") or raw.get("item_id") or ""
            meta = raw.get("metadata") or {}
            document_id = meta.get("document_id") or item_id.rsplit("_p", 1)[0]
            page = int(meta.get("page") or item_id.rsplit("_p", 1)[-1])
            subject = meta.get("subject") or "UNKNOWN"
            base = root / subject / document_id
            image = base / "images" / f"page_{page}.jpg"
            md = base / "mds" / f"{document_id}_{page}.md"
            if image.exists() and (split != "dev" or md.exists()):
                continue
            item = toolbox.get_item(DATASET_ID, split, item_id)
            refs = item.get("artifacts", [])
            image_ref = next((r for r in refs if str(r.get("media_type", "")).startswith("image/")), None)
            if image_ref and not image.exists():
                _write(image, toolbox.get_artifact(DATASET_ID, split, item_id, image_ref["path"]))
            if split == "dev" and not md.exists():
                md_ref = next((r for r in refs if str(r.get("path", "")).endswith(".md")), None)
                data = toolbox.get_artifact(DATASET_ID, split, item_id, md_ref["path"]) if md_ref else None
                if data:
                    _write(md, data)
                else:
                    _hf_download(f"dev/{subject}/{document_id}/mds/{document_id}_{page}.md", md)
            written += 1
        return written

    def pages(self, root: Path) -> list[BenchPage]:
        pages = []
        for image in root.rglob("page_*.jpg"):
            doc_dir = image.parent.parent if image.parent.name == "images" else image.parent
            document_id = doc_dir.name
            page = int(image.stem.split("_")[-1])
            gt = doc_dir / "mds" / f"{document_id}_{page}.md"
            pages.append(BenchPage(
                item_id=f"{document_id}_p{page}",
                document_id=document_id,
                page=page,
                image_path=image,
                gt_path=gt if gt.exists() else None,
                meta={"subject": doc_dir.parent.name},
            ))
        return sorted(pages, key=lambda p: p.item_id)

    def build_submission(self, pages: list[BenchPage], predictions: Path, out: Path) -> Path:
        """``submission.zip`` holding ``predictions.jsonl`` (subject, document_id, page, markdown).

        Every page of the tree must have a prediction: EvalAI rejects missing pages.
        """
        missing = [p.item_id for p in pages if not (predictions / f"{p.item_id}.md").exists()]
        if missing:
            raise SystemExit(f"{len(missing)} pages without prediction, e.g. {missing[:3]}")
        lines = [
            json.dumps({
                "subject": p.meta["subject"],
                "document_id": p.document_id,
                "page": p.page,
                "markdown": (predictions / f"{p.item_id}.md").read_text(encoding="utf-8"),
            }, ensure_ascii=False)
            for p in pages
        ]
        out.mkdir(parents=True, exist_ok=True)
        zip_path = out / "submission.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("predictions.jsonl", "\n".join(lines) + "\n")
        return zip_path


    def build_official_tree(self, pages: list[BenchPage], predictions: Path, out: Path) -> int:
        """Prediction tree of the official evaluator (``tools/multipage_pdf_validation.py``),
        one-page windows: ``<out>/<subject>/<document_id>_page_<N>-<N>.md``."""
        if out.exists():
            shutil.rmtree(out)
        n = 0
        for p in pages:
            src = predictions / f"{p.item_id}.md"
            if src.exists():
                dst = out / p.meta["subject"] / f"{p.document_id}_page_{p.page}-{p.page}.md"
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst)
                n += 1
        return n


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _hf_download(repo_path: str, dest: Path) -> None:
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("[WARN] huggingface_hub not installed; GT not downloaded", file=sys.stderr)
        return
    try:
        _write(dest, Path(hf_hub_download(HF_REPO, repo_path, repo_type="dataset")).read_bytes())
    except Exception as e:  # noqa: BLE001 - report and continue with the next page
        print(f"[WARN] HF download failed for {repo_path}: {e}", file=sys.stderr)
