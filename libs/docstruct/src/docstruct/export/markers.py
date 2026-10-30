"""Object markers: a paragraph before and after each transformed object.

A reader who listens to the document cannot see where a described picture, a
table read off an image or a recognized formula starts and ends. With markers
on, each such block is enclosed by two paragraphs, ``[label]`` and
``[/label]``, so every format (HTML, TXT and its audio, DOCX, PDF/UA) carries
them from one pass over the canonical document. Pure functions, no I/O.
"""
from __future__ import annotations

import copy
import itertools
from collections.abc import Iterator, Mapping
from typing import Any


def wrap_object_markers(
    document: dict[str, Any], labels: Mapping[str, str]
) -> dict[str, Any]:
    """A copy of ``document`` with each block whose type is in ``labels`` enclosed.

    ``labels`` maps a block type to the word its markers carry ("image" →
    "imagem" gives "[imagem]" … "[/imagem]"); types left out are not marked.
    The markers take their ids from the block's; a block without one gets a
    numbered "object-N", so the marked document keeps its ids unique.
    """
    marked = copy.deepcopy(document)
    unnamed = itertools.count(1)
    for section in marked.get("sections", []):
        _wrap_section(section, labels, unnamed)
    return marked


def _wrap_section(
    section: dict[str, Any], labels: Mapping[str, str], unnamed: Iterator[int]
) -> None:
    blocks = []
    for block in section.get("blocks", []):
        label = labels.get(block.get("type", ""))
        if not label:
            blocks.append(block)
            continue
        identifier = block.get("id") or f"object-{next(unnamed)}"
        blocks.append(_marker(f"{identifier}-marker-open", f"[{label}]"))
        blocks.append(block)
        blocks.append(_marker(f"{identifier}-marker-close", f"[/{label}]"))
    section["blocks"] = blocks
    for child in section.get("children", []):
        _wrap_section(child, labels, unnamed)


def _marker(identifier: str, text: str) -> dict[str, Any]:
    return {"id": identifier, "type": "paragraph", "text": text, "metadata": {"object_marker": True}}


__all__ = ["wrap_object_markers"]
