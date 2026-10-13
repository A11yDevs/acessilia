"""Normalização de texto para comparação e medição.

Porta de ``norm`` do Tree Differ v1 (Dr.DocBench). É o normalizador usado pelo
fusor para medir comprimento e para preencher ``DiffBlock.text``: remove tags
HTML, troca a pontuação de marcação por espaço, colapsa espaços e baixa a caixa.

Não confundir com ``sanitize_text`` (``docstruct.text.sanitize``), que limpa
vazamentos de prompt e artefatos de markdown preservando o conteúdo legível.
"""
from __future__ import annotations

import re

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MARKUP_RE = re.compile(r"[#*_`|>$\\\[\]{}]")
_WS_RE = re.compile(r"\s+")


def norm(s: str) -> str:
    """Normaliza ``s`` para comparação: sem tags/marcação, espaços colapsados, minúsculas."""
    s = _HTML_TAG_RE.sub(" ", s)
    s = _MARKUP_RE.sub(" ", s)
    return _WS_RE.sub(" ", s).strip().lower()
