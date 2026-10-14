"""Compatibility helpers for section titles also stored as legacy heading blocks."""
from typing import Any


def explicit_section_title(section: dict[str, Any]) -> dict[str, Any] | None:
    blocks = section.get("blocks", [])
    if not section.get("title") or not blocks:
        return None
    first = blocks[0]
    if (
        first.get("type") == "heading"
        and first.get("title", first.get("text", "")) == section["title"]
        and first.get("level", 1) == section.get("level", 1)
    ):
        return first
    return None


def section_body_blocks(section: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = section.get("blocks", [])
    return blocks[1:] if explicit_section_title(section) is not None else blocks


def section_title_alias(section: dict[str, Any]) -> str:
    first = explicit_section_title(section)
    if first is not None and first.get("id") != section.get("id"):
        return first.get("id", "")
    return ""
