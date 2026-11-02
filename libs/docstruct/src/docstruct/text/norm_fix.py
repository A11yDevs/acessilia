"""Limpezas determinísticas de texto que custam distância de edição.

Porta de ``norm_fix`` e ``LIGATURES`` do Tree Differ v2 (PR #125, Dr.DocBench).

Corrige ligaduras tipográficas, hífens suaves, NBSP, hifenização de fim de linha
e espaços duplicados. Tabelas e fórmulas são deixadas intactas: nelas a
pontuação e o espaçamento são conteúdo, não formatação.

Função pura, sem I/O e sem dependências pesadas.
"""
from __future__ import annotations

import re

LIGATURES = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "ft", "ﬆ": "st"}

# Prefixos de markdown cujo conteúdo não deve ser tocado.
_PROTECTED_PREFIXES = ("<table", "$$", "\\[", "|")

# Hifenização de fim de linha entre letras (inclui acentuadas).
_LINE_END_HYPHEN_RE = re.compile(r"([A-Za-zÀ-ÿ])-\n([a-zà-ÿ])")
_DUP_SPACE_RE = re.compile(r"[ \t]{2,}")


def norm_fix(md: str) -> str:
    """Aplica as limpezas determinísticas a ``md``.

    Tabelas e fórmulas (``<table``, ``$$``, ``\\[``, ``|``) são devolvidas sem
    alteração.
    """
    if md.lstrip().startswith(_PROTECTED_PREFIXES):
        return md
    for k, v in LIGATURES.items():
        md = md.replace(k, v)
    md = md.replace("\u00ad", "").replace("\u00a0", " ")
    md = _LINE_END_HYPHEN_RE.sub(r"\1\2", md)
    md = _DUP_SPACE_RE.sub(" ", md)
    return md
