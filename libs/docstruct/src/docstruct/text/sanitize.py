"""Text sanitization: prompt-leak and markdown artifact removal.

Ported from backend/pipeline/sanitizer.py (behavior-preserving).
"""
from __future__ import annotations

import re

PROMPT_LEAK_PATTERNS = [
    r"(?i)chain of thought",
    r"(?i)think step by step",
    r"(?i)system prompt",
    r"(?i)instru[cç][aã]o(?:es)? internas?",
    r"(?i)cadeia de pensamento",
    r"(?i)ignore previous instructions",
    r"(?i)assistant note",
]

# Lookahead for a letter: what a list marker introduces, unlike a number or
# a formula, which a leading "-" belongs to.
BEFORE_WORD = r"(?=[^\W\d_])"

MARKDOWN_ARTIFACT_PATTERNS = [
    r"(?m)^(#{1,6})\s+",
    r"(?m)^(\s*[-*+]\s+)",
    r"(?m)^(\s*\d+\.\s+)",
    r"\*\*.+\*\*",
]


def sanitize_text(text: str) -> str:
    if not text:
        return ""
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f]", "", cleaned)
    cleaned = re.sub(
        r"(?im)^\s*\[(?:in[ií]cio|fim) da audiodescri[cç][aã]o\]\s*$",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"(?im)^\s*(?:prompt|system|developer)\s*:\s*.*$",
        "",
        cleaned,
    )
    for pattern in PROMPT_LEAK_PATTERNS:
        cleaned = re.sub(pattern, "[conteudo removido]", cleaned)
    return cleaned.strip()


def normalize_prose_tabs(text: str) -> str:
    """Collapse whitespace runs containing a TAB, preserving all other text.

    Only horizontal spaces adjoining TABs are included; line breaks and runs
    of ordinary spaces without a TAB keep their original form. This does not
    strip Markdown or numbering from already-canonical title metadata.
    """
    return re.sub(
        r"[ \t]+",
        lambda match: " " if "\t" in match.group(0) else match.group(0),
        text,
    )


def sanitize_block_text(text: str, block_type: str | None = None) -> str:
    if not text:
        return ""
    if block_type == "code":
        return text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = sanitize_text(text)
    # Extraction providers can use TABs as word separators in prose (#338).
    # Code returns above so indentation remains intact.
    cleaned = normalize_prose_tabs(cleaned)
    cleaned = re.sub(r"(?<!`)`([^`]+)`(?!`)", r"\1", cleaned)
    cleaned = re.sub(r"\*\*(.+?)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"\1", cleaned)
    cleaned = re.sub(r"__([^_]+)__", r"\1", cleaned)
    cleaned = re.sub(r"(?m)^\s*#{1,6}\s+", "", cleaned)
    # A leading "- " or "1. " is a list marker only before a word; before a
    # number or formula it is data ("- 0,08" is negative, "- \frac" too) (#260).
    cleaned = re.sub(rf"(?m)^[ \t]*[-*+][ \t]+{BEFORE_WORD}", "", cleaned)
    cleaned = re.sub(
        rf"(?m)^[ \t]*(?:\d+\.|\d+\)|\(\d+\))[ \t]+{BEFORE_WORD}", "", cleaned
    )
    cleaned = re.sub(r"(?m)^\s*```+\s*$", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def contains_prompt_leak(text: str) -> bool:
    return any(re.search(pattern, text) for pattern in PROMPT_LEAK_PATTERNS)


def contains_markdown_artifacts(text: str) -> bool:
    return any(re.search(pattern, text) for pattern in MARKDOWN_ARTIFACT_PATTERNS)
