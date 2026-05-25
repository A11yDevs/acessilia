from __future__ import annotations

from pathlib import Path
from typing import Any

from pipeline.verbosity_manager import filter_blocks_for_profile


def render_txt(document: dict[str, Any], output_path: Path, profile_name: str = "txt") -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for section in document.get("sections", []):
        lines.extend(_render_section(section, profile_name))
    output_path.write_text(
        "\n".join([line for line in lines if line is not None]).strip(),
        encoding="utf-8",
    )
    return output_path


def _render_section(section: dict[str, Any], profile_name: str) -> list[str]:
    lines: list[str] = []
    if section.get("title"):
        lines.append(section["title"])
    for block in filter_blocks_for_profile(section.get("blocks", []), profile_name):
        lines.extend(_render_block(block))
    for child in section.get("children", []):
        lines.extend(_render_section(child, profile_name))
    return lines


def _render_block(block: dict[str, Any]) -> list[str]:
    block_type = block.get("type")
    if block_type == "heading":
        return [block.get("title", block.get("text", ""))]
    if block_type == "paragraph":
        return [block.get("text", "")]
    if block_type == "code":
        return [block.get("text", "")]
    if block_type == "list":
        prefix = "1." if block.get("ordered") else "-"
        return [f"{prefix} {item}" for item in block.get("items", [])]
    if block_type == "table":
        return [" | ".join(str(cell) for cell in row) for row in block.get("rows", [])]
    if block_type == "image":
        return [block.get("alt_text") or block.get("text", "")]
    if block_type == "math":
        return [block.get("text", "")]
    if block_type in {"details", "note", "warning", "quote"}:
        return [block.get("text", "")]
    return [block.get("text", "")]