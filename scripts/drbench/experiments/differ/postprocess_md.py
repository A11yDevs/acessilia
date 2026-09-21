#!/usr/bin/env python
"""Post-process an existing predictions dir into a new run (no re-inference).

Fixes applied (each is a flag, so runs stay attributable):
  --strip-placeholder-title  remove the spurious "# Dr.DocBench page" heading emitted by
                             build_canonical_document() when no heading is found.
  --demote-prose-formulas    turn $$...$$ blocks whose body is mostly running text (a paragraph
                             MinerU mislabelled as interline_equation) back into a paragraph.

Usage: postprocess_md.py --src runs/dev/<run>/predictions --out runs/dev/<new-run>/predictions [flags]
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

PLACEHOLDER_RE = re.compile(r"^# Dr\.DocBench page\s*\n+", re.MULTILINE)
DISPLAY_RE = re.compile(r"\$\$\s*(.*?)\s*\$\$", re.DOTALL)
CMD_RE = re.compile(r"\\[A-Za-z]+")
WORD_RE = re.compile(r"[A-Za-z]{3,}")
SPACED_RE = re.compile(r"\\math(?:rm|sf|it|bf)\s*\{((?:\s*[A-Za-z]\s*){3,})\}")


def is_prose_formula(body: str) -> bool:
    """Heuristic: a display formula whose body reads like a sentence."""
    if len(body) < 60:
        return False
    stripped = CMD_RE.sub(" ", body)
    words = WORD_RE.findall(stripped)
    tokens = stripped.split()
    if not tokens:
        return False
    # sentences have many alphabetic words; formulas have symbols, braces, digits
    return len(words) >= 8 and len(words) / len(tokens) > 0.5


def demote(body: str) -> str:
    # \mathrm { C e l s i u s } -> Celsius
    body = SPACED_RE.sub(lambda m: m.group(1).replace(" ", ""), body)
    return " ".join(body.split())


def process(text: str, *, strip_placeholder_title: bool, demote_prose_formulas: bool = False) -> str:
    if strip_placeholder_title:
        text = PLACEHOLDER_RE.sub("", text)
    if demote_prose_formulas:
        text = DISPLAY_RE.sub(
            lambda m: demote(m.group(1)) if is_prose_formula(m.group(1)) else m.group(0), text
        )
    return text.strip() + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--strip-placeholder-title", action="store_true")
    ap.add_argument("--demote-prose-formulas", action="store_true")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    n = changed = 0
    for p in sorted(a.src.glob("*.drbench.md")):
        src = p.read_text(encoding="utf-8")
        dst = process(src, strip_placeholder_title=a.strip_placeholder_title,
                      demote_prose_formulas=a.demote_prose_formulas)
        (a.out / p.name).write_text(dst, encoding="utf-8")
        n += 1
        changed += dst != src
    print(f"{n} files written to {a.out}; {changed} changed")
