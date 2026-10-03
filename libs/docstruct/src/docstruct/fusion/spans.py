"""Map provider charspans conservatively into a specific source-block Markdown.

Offsets count Unicode code points, with an exclusive end. Snapshots remain
scoped to their source block when fusion subsequently changes or joins Markdown.
"""
from copy import deepcopy
from typing import Any


def map_charspans(source: dict[str, Any], markdown: str) -> dict[str, Any]:
    """Verify known cleanup and exact containment; never repair provider spans."""
    result = deepcopy(source)
    result.update(markdown=markdown, markdown_scope="source_block",
                  offset_unit="unicode_codepoint", spans=[])
    text = source.get("text")
    if not isinstance(text, str):
        text = ""
    tokens: list[tuple[int, int, str]] = []
    i = 0
    while i < len(text):
        start, char = i, text[i]
        i += 1
        if char == "\r":
            if i < len(text) and text[i] == "\n":
                i += 1
            char = "\n"
        if not source.get("preserve_controls") and ord(char) in (*range(9), 11, 12, *range(14, 32)):
            continue
        tokens.append((start, i, char))
    # Same whitespace trimming as the existing manifest/Markdown conversion.
    left, right = 0, len(tokens)
    while left < right and tokens[left][2].isspace():
        left += 1
    while right > left and tokens[right-1][2].isspace():
        right -= 1
    tokens = tokens[left:right]
    cleaned = "".join(t[2] for t in tokens)
    offset = markdown.find(cleaned) if cleaned else -1
    unique = offset >= 0 and markdown.find(cleaned, offset+1) < 0
    for span in source.get("charspans") or []:
        record: dict[str, Any] = {"source_span": deepcopy(span), "markdown_span": None}
        if span is None:
            status = "missing_span"
        elif (not isinstance(span, (tuple, list)) or len(span) != 2
              or any(type(v) is not int for v in span)
              or not 0 <= span[0] <= span[1] <= len(text)):
            status = "invalid_span"
        elif source.get("field") != "text":
            status = "unknown_scope"
        elif span[0] == span[1]:
            status = "empty_span"
        elif not unique:
            status = "unmapped_text"
        else:
            positions = [n for n, (start, end, _) in enumerate(tokens)
                         if start < span[1] and end > span[0]]
            if not positions:
                status = "removed"
            elif tokens[positions[0]][0] < span[0] or tokens[positions[-1]][1] > span[1]:
                status = "unmapped_boundary"
            else:
                status = "mapped"
                record["markdown_span"] = [offset+positions[0], offset+positions[-1]+1]
        record["status"] = status
        result["spans"].append(record)
    return result
