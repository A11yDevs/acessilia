"""Guarda contra loops de geração (repetição degenerada) e páginas em branco.

Porta de ``rep_guard.py`` do Dr.DocBench (PR #125).

Fontes MinerU/VLM às vezes degeneram em repetição ("5 5 5 5 ..." ou uma frase
repetida dez vezes em uma página em branco). ``collapse`` corta um n-grama
repetido ``k >= reps`` vezes até o maior run consecutivo que as fontes de
referência (Docling ou a página VLM) exibem, preservando repetições legítimas.

``is_blank_page`` detecta a página em branco: Docling sem texto e a VLM dizendo
que não há texto (sua saída é só comentário).

Funções puras, sem I/O e sem dependências pesadas.
"""
from __future__ import annotations

import re

# Comentário da VLM dizendo que a página não tem texto (branca / só figura).
COMMENT_RE = re.compile(
    r"^\(?\s*(there is no (visible )?(text|content)|no (visible )?text|there is nothing (to|visible)|"
    r"there is no visible content|the image (provided )?(appears|contains|shows|displays)|"
    r"this (image|page) (appears|contains|shows))",
    re.I,
)
COMMENT2_RE = re.compile(r"\b(nothing|no (visible )?(text|content))\b.{0,40}\btranscrib", re.I)

# Prefixos de markdown cujo conteúdo não deve ser tocado.
_PROTECTED_PREFIXES = ("<table", "$$", "<")

_TAG_RE = re.compile(r"<[^>]+>")
_NON_WORD_RE = re.compile(r"[^\w]+")
_BLOCK_SPLIT_RE = re.compile(r"(\n\s*\n)")
_WS_SPLIT_RE = re.compile(r"(\s+)")


def token_norm(t: str) -> str:
    """Normaliza um token para comparação: sem tags, só palavras, minúsculas."""
    return " ".join(_NON_WORD_RE.sub(" ", _TAG_RE.sub(" ", t).lower()).split())


def strip_comment(t: str) -> str:
    """Remove blocos que são só comentário da VLM sobre a ausência de texto."""
    return "\n\n\n\n\n".join(
        b
        for b in re.split(r"\n\s*\n", t)
        if b.strip() and not COMMENT_RE.match(b.strip()) and not COMMENT2_RE.search(b)
    )


def max_run(ref: list, g: tuple) -> int:
    """Maior número de repetições consecutivas do n-grama ``g`` em ``ref``."""
    n, best = len(g), 0
    i = 0
    while i + n <= len(ref):
        if tuple(ref[i : i + n]) == g:
            k = 1
            while tuple(ref[i + k * n : i + (k + 1) * n]) == g:
                k += 1
            best = max(best, k)
            i += k * n
        else:
            i += 1
    return best


def collapse(block: str, refs: list, reps: int, max_n: int) -> tuple[str, int]:
    """Corta repetições degeneradas de ``block`` até o run visto em ``refs``.

    ``refs`` é uma lista de listas de tokens normalizados (as fontes de
    referência). Devolve ``(texto, tokens_cortados)``. O espaçamento original é
    preservado.
    """
    parts = _WS_SPLIT_RE.split(block)
    toks = parts[0::2]
    seps = parts[1::2] + [""]
    key = [token_norm(t) for t in toks]
    out: list[str] = []
    i, cut = 0, 0
    while i < len(toks):
        done = False
        if key[i]:
            for n in range(1, max_n + 1):
                g = tuple(key[i : i + n])
                if len(g) < n or not all(g):
                    break
                k = 1
                while tuple(key[i + k * n : i + (k + 1) * n]) == g:
                    k += 1
                if k >= reps:
                    keep = max([1] + [max_run(r, g) for r in refs])
                    if keep < k:
                        out += [
                            t + s
                            for t, s in zip(toks[i : i + keep * n], seps[i : i + keep * n])
                        ]
                        cut += (k - keep) * n
                        i += k * n
                        done = True
                        break
        if not done:
            out.append(toks[i] + seps[i])
            i += 1
    return "".join(out), cut


def is_blank_page(a_text: str, docling_text: str, vlm_text: str) -> bool:
    """True se a página é branca: Docling sem texto e a VLM só com comentário."""
    return (
        bool(token_norm(a_text))
        and not token_norm(docling_text)
        and bool(vlm_text.strip())
        and not strip_comment(vlm_text).strip()
    )


def guard_page(
    a_text: str,
    docling_text: str,
    vlm_text: str,
    reps: int = 5,
    max_n: int = 12,
    blank: bool = False,
) -> tuple[str, int, bool]:
    """Aplica o guarda a uma página.

    Devolve ``(texto, tokens_cortados, era_branca)``. Com ``blank=True``, uma
    página branca é esvaziada. Tabelas e fórmulas são deixadas intactas.
    """
    if blank and is_blank_page(a_text, docling_text, vlm_text):
        return "\n", 0, True
    refs = [token_norm(docling_text).split(), token_norm(vlm_text).split()]
    out: list[str] = []
    cut = 0
    for b in _BLOCK_SPLIT_RE.split(a_text):
        if b.strip() and not b.lstrip().startswith(_PROTECTED_PREFIXES):
            b, c = collapse(b, refs, reps, max_n)
            cut += c
        out.append(b)
    return "".join(out), cut, False
