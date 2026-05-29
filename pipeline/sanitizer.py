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


def sanitize_block_text(text: str, block_type: str | None = None) -> str:
    if not text:
        return ""
    if block_type == "code":
        return text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = sanitize_text(text)
    cleaned = re.sub(r"(?<!`)`([^`]+)`(?!`)", r"\1", cleaned)
    cleaned = re.sub(r"\*\*(.+?)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"\1", cleaned)
    cleaned = re.sub(r"__([^_]+)__", r"\1", cleaned)
    cleaned = re.sub(r"(?m)^\s*#{1,6}\s+", "", cleaned)
    cleaned = re.sub(r"(?m)^\s*[-*+]\s+", "", cleaned)
    cleaned = re.sub(r"(?m)^\s*(?:\d+\.\s+|\d+\)\s+|\(\d+\)\s+)", "", cleaned)
    cleaned = re.sub(r"(?m)^\s*```+\s*$", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def contains_prompt_leak(text: str) -> bool:
    return any(re.search(pattern, text) for pattern in PROMPT_LEAK_PATTERNS)


def contains_markdown_artifacts(text: str) -> bool:
    return any(re.search(pattern, text) for pattern in MARKDOWN_ARTIFACT_PATTERNS)
