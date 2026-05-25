from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

from pipeline.sanitizer import sanitize_block_text
from pipeline.sanitizer import sanitize_text
from pipeline.structure_parser import parse_text_to_blocks


def build_canonical_document(
    source_text: str | dict[str, Any],
    *,
    title: str = "Documento acessível",
    language: str = "pt-BR",
    verbosity: str = "detailed",
    audience: list[str] | None = None,
    source_name: str = "",
    source_path: str = "",
    metadata: dict[str, Any] | None = None,
    technical_warnings: list[str] | None = None,
) -> dict[str, Any]:
    if isinstance(source_text, dict):
        source_payload: dict[str, Any] = source_text
    else:
        source_payload = {}
    raw_text = source_payload.get("text", source_text)
    cleaned = sanitize_text(str(raw_text))
    parsed_blocks = _parse_structured_blocks(source_payload, cleaned)
    sections = _build_sections(parsed_blocks)
    source_type = Path(source_path).suffix.lower() if source_path else ""
    source_metadata = {
        "page_count": source_payload.get("page_count"),
        "mode": source_payload.get("mode"),
        "pages": source_payload.get("pages", []),
    }
    return {
        "schema_version": "1.0.0",
        "id": f"doc-{uuid4().hex[:12]}",
        "title": title or _infer_title(parsed_blocks) or "Documento acessível",
        "language": language,
        "verbosity": verbosity,
        "audience": audience or ["reader"],
        "metadata": {**(metadata or {}), **source_metadata},
        "source": {
            "name": source_name,
            "path": source_path,
            "type": source_type,
        },
        "accessibility": {
            "navigation": True,
            "semantic_headings": True,
            "internal_links": True,
        },
        "technical_warnings": technical_warnings or [],
        "audit": {
            "generated_by": "canonical_builder",
            "input_length": len(source_text),
            "block_count": len(parsed_blocks),
        },
        "sections": sections,
    }


def _infer_title(blocks: list[dict[str, Any]]) -> str:
    for block in blocks:
        if block.get("type") == "heading" and block.get("level") == 1:
            return block.get("text", "")
    return ""


def _parse_structured_blocks(
    source_payload: dict[str, Any],
    cleaned_text: str,
) -> list[dict[str, Any]]:
    pages = source_payload.get("pages", [])
    page_blocks: list[dict[str, Any]] = []
    if isinstance(pages, list):
        for page in pages:
            blocks = page.get("blocks", []) if isinstance(page, dict) else []
            if blocks:
                page_blocks.extend(blocks)

    if page_blocks:
        return _attach_ids(_sanitize_structured_blocks(page_blocks))

    return parse_text_to_blocks(cleaned_text)


def sanitize_canonical_document(
    document: dict[str, Any],
) -> dict[str, Any]:
    sanitized = deepcopy(document)
    sections = sanitized.get("sections", [])
    if isinstance(sections, list):
        sanitized["sections"] = _sanitize_sections(sections)
    return sanitized


def _sanitize_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized_sections: list[dict[str, Any]] = []
    for section in sections:
        clean_section = deepcopy(section)
        blocks = clean_section.get("blocks", [])
        if isinstance(blocks, list):
            clean_section["blocks"] = _sanitize_structured_blocks(blocks)
        children = clean_section.get("children", [])
        if isinstance(children, list):
            clean_section["children"] = _sanitize_sections(children)
        sanitized_sections.append(clean_section)
    return sanitized_sections


def _sanitize_structured_blocks(
    blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    sanitized_blocks: list[dict[str, Any]] = []
    for block in blocks:
        clean = deepcopy(block)
        block_type = clean.get("type")

        if isinstance(clean.get("text"), str) and block_type != "code":
            clean["text"] = sanitize_block_text(
                clean["text"],
                block_type=block_type,
            )

        if isinstance(clean.get("title"), str):
            clean["title"] = sanitize_block_text(clean["title"])
        if isinstance(clean.get("alt_text"), str):
            clean["alt_text"] = sanitize_block_text(clean["alt_text"])
        if isinstance(clean.get("long_description"), str):
            clean["long_description"] = sanitize_block_text(
                clean["long_description"]
            )

        if block_type == "list" and isinstance(clean.get("items"), list):
            clean["items"] = [
                sanitize_block_text(str(item))
                for item in clean["items"]
            ]

        if block_type == "table" and isinstance(clean.get("rows"), list):
            rows: list[list[str]] = []
            for row in clean["rows"]:
                if not isinstance(row, list):
                    continue
                rows.append(
                    [sanitize_block_text(str(cell)) for cell in row]
                )
            clean["rows"] = rows

        children = clean.get("children")
        if isinstance(children, list):
            clean["children"] = _sanitize_structured_blocks(children)

        sanitized_blocks.append(clean)
    return sanitized_blocks


def _make_id(prefix: str, text: str, counter: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if not slug:
        slug = prefix
    return f"{prefix}-{slug[:40]}-{counter}"


def _attach_ids(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, int] = {}
    for index, block in enumerate(blocks, start=1):
        base_id = block.get("id") or _make_id(
            block["type"],
            block.get("text", ""),
            index,
        )
        count = seen.get(base_id, 0) + 1
        seen[base_id] = count
        block["id"] = base_id if count == 1 else f"{base_id}-{count}"
    return blocks


def _build_sections(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    root: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    generated_count = 0

    def new_section(heading: dict[str, Any]) -> dict[str, Any]:
        nonlocal generated_count
        generated_count += 1
        return {
            "id": heading.get("id", f"section-{generated_count}"),
            "title": heading.get("text", ""),
            "level": heading.get("level", 1),
            "source_location": deepcopy(
                heading.get("source_location", {})
            ),
            "metadata": deepcopy(heading.get("metadata", {})),
            "blocks": [],
            "children": [],
        }

    for block in blocks:
        if block.get("type") == "heading":
            section = new_section(block)
            level = block.get("level", 1)
            while stack and stack[-1]["level"] >= level:
                stack.pop()
            if stack:
                stack[-1]["children"].append(section)
            else:
                root.append(section)
            stack.append(section)
            continue

        if stack:
            stack[-1]["blocks"].append(block)
        else:
            generated_count += 1
            root.append(
                {
                    "id": block.get("id", f"sectionless-{generated_count}"),
                    "title": "",
                    "level": 1,
                    "source_location": deepcopy(
                        block.get("source_location", {})
                    ),
                    "metadata": {},
                    "blocks": [block],
                    "children": [],
                }
            )

    return root
