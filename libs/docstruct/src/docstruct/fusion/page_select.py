"""Seleção e fusão de páginas inteiras entre fontes.

Porta de ``page_fuse.py``, ``vlm_page_select.py`` e ``page_swap.py`` do
Dr.DocBench (PR #125).

Três decisões, todas GT-free (funcionam em dev e test):

- ``fuse`` — funde a transcrição VLM de página inteira (B) com a saída do
  differ (A) no nível de bloco. ``order``/``head`` mantêm a ordem e a marcação
  de heading de A (que carrega as convenções de cauda decor e de ordem de
  leitura do GT) tomando o texto de B; ``swap`` troca o texto de cada bloco de A
  cujo melhor par em B seja suficientemente similar.
- ``select_by_agreement`` — quando Docling e MinerU discordam muito na página, o
  differ tem pouco em que se apoiar; aí vale a página VLM.
- ``swap_low_agreement_pages`` — páginas onde Docling e MinerU mais discordam
  são as difíceis, onde a fusão herda OCR ruim; nelas a fonte alternativa
  substitui a página fundida.

A similaridade usa o ratio LCS normalizado (equivalente exato a
``rapidfuzz.fuzz.ratio``), implementado aqui para manter ``dependencies = []``.

Funções puras, sem I/O e sem dependências pesadas.
"""
from __future__ import annotations

import difflib
import re

# Marcação removida antes da comparação (tags HTML, cifrões, comandos LaTeX, markdown).
TAG_RE = re.compile(r"<[^>]+>|\$+|\\[a-z]+|[#*_`|]")
_NON_WORD_RE = re.compile(r"[^\w]+")
_BLANK_LINE_RE = re.compile(r"\n\s*\n")
_HEADING_RE = re.compile(r"^\s*#+\s*")
# Conjunto de caracteres removido por ``page_swap.nrm`` (não inclui ``$`` nem ``\``).
_SWAP_STRIP_RE = re.compile(r"[#*_`>|<>/-]")
_WS_RE = re.compile(r"\s+")

MODES = ("order", "head", "swap")


def page_norm(t: str) -> str:
    """Normaliza texto de página para comparação: sem marcação, só palavras, minúsculas."""
    return " ".join(_NON_WORD_RE.sub(" ", TAG_RE.sub(" ", t).lower()).split())


def swap_norm(s: str) -> str:
    """Normalização usada pela decisão de troca de página (``page_swap.nrm``)."""
    return _WS_RE.sub(" ", _SWAP_STRIP_RE.sub("", s)).strip().lower()


def blocks(t: str) -> list[str]:
    """Divide ``t`` em blocos separados por linha em branco."""
    return [b.strip("\n") for b in _BLANK_LINE_RE.split(t) if b.strip()]


def _lcs_len(a: str, b: str) -> int:
    if not a or not b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    prev = [0] * (len(b) + 1)
    for ca in a:
        cur = [0] * (len(b) + 1)
        for j, cb in enumerate(b, 1):
            cur[j] = prev[j - 1] + 1 if ca == cb else max(prev[j], cur[j - 1])
        prev = cur
    return prev[-1]


def ratio(a: str, b: str) -> float:
    """Similaridade LCS normalizada em ``[0, 1]`` (igual a ``rapidfuzz.fuzz.ratio``/100)."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return 2 * _lcs_len(a, b) / (len(a) + len(b))


def page_agreement(a: str, b: str) -> float:
    """Concordância entre duas páginas (ratio difflib sobre ``swap_norm``)."""
    return difflib.SequenceMatcher(None, swap_norm(a), swap_norm(b), autojunk=False).ratio()


def _swap(a_blocks: list[str], b_blocks: list[str], sim: float, tables: bool) -> list[str]:
    nb = [page_norm(x) for x in b_blocks]
    out: list[str] = []
    for x in a_blocks:
        is_tab = x.lstrip().startswith("<table")
        if is_tab and not tables:
            out.append(x)
            continue
        nx = page_norm(x)
        best, bj = 0.0, -1
        for j, y in enumerate(nb):
            if nx and y and is_tab == b_blocks[j].lstrip().startswith("<table"):
                s = ratio(nx, y)
                if s > best:
                    best, bj = s, j
        if best < sim:
            out.append(x)
            continue
        y = _HEADING_RE.sub("", b_blocks[bj]).strip()
        h = _HEADING_RE.match(x)
        out.append((h[0] if h else "") + y)
    return out


def fuse(ta: str, tb: str, mode: str, sim: float, tables: bool = False) -> str:
    """Funde as páginas ``ta`` (A) e ``tb`` (B) no ``mode`` dado.

    Devolve ``ta`` inalterado quando ``tb`` não tem blocos. ``mode`` é
    ``"order"``, ``"head"`` ou ``"swap"``.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    a_blocks, b_blocks = blocks(ta), blocks(tb)
    if not b_blocks:
        return ta
    if mode == "swap":
        return "\n\n\n\n\n".join(_swap(a_blocks, b_blocks, sim, tables)) + "\n"
    na = [page_norm(x) for x in a_blocks]
    keys: list[tuple[float, int]] = []
    out: list[str] = []
    last = -1.0
    for j, b in enumerate(b_blocks):
        nb = page_norm(b)
        best, bi = 0.0, -1
        for i, x in enumerate(na):
            if not x or not nb:
                continue
            s = ratio(nb, x)
            if s > best:
                best, bi = s, i
        if best >= sim:
            k = float(bi)
            if mode == "head":
                hb, ha = b.lstrip().startswith("#"), a_blocks[bi].lstrip().startswith("#")
                if hb and not ha:
                    b = _HEADING_RE.sub("", b)
                elif ha and not hb and "\n" not in b:
                    b = a_blocks[bi][: len(a_blocks[bi]) - len(a_blocks[bi].lstrip("#"))].strip() + " " + b
        else:
            k = last + 1e-3
        last = k
        keys.append((k, j))
        out.append(b)
    order = [j for _, j in sorted(keys)]
    return "\n\n\n\n\n".join(out[j] for j in order) + "\n"


def select_by_agreement(
    a_text: str,
    vlm_text: str,
    docling_text: str,
    mineru_text: str,
    finish: str | None,
    dm: float = 0.6,
    ab: float = 0.0,
    sim: float = 0.6,
) -> tuple[str, bool]:
    """Decide se a página VLM substitui a saída do differ.

    Só considera a VLM quando ela tem texto, a geração terminou (``finish ==
    "stop"``) e a concordância Docling/MinerU está abaixo de ``dm``. Nesse caso
    toma a página VLM fundida em modo ``order`` se ela for mais longa que A ou
    se concordar com a VLM em ``ab`` (``ab > 0``).

    Devolve ``(texto, trocou)``.
    """
    tv = vlm_text
    if not tv.strip() or finish != "stop":
        return a_text, False
    tb = fuse(a_text, tv, "order", sim)
    d, m = page_norm(docling_text), page_norm(mineru_text)
    dm_ratio = ratio(d, m) if d and m else 0.0
    na, nb = page_norm(a_text), page_norm(tb)
    agree = ab > 0 and bool(na) and ratio(na, page_norm(tv)) >= ab
    if dm_ratio < dm and (len(nb) > len(na) or agree):
        return tb, True
    return a_text, False


def swap_low_agreement_pages(
    base_text: str,
    alt_text: str | None,
    docling_text: str,
    mineru_text: str,
    agree_thr: float = 0.45,
    min_alt_frac: float = 0.3,
) -> tuple[str, bool]:
    """Decide se a fonte alternativa substitui a página fundida.

    Troca quando a concordância Docling/MinerU está abaixo de ``agree_thr`` e a
    alternativa tem pelo menos ``min_alt_frac`` do comprimento normalizado da
    página base. Devolve ``(texto, trocou)``.
    """
    if alt_text is None:
        return base_text, False
    if page_agreement(docling_text, mineru_text) >= agree_thr:
        return base_text, False
    if len(swap_norm(alt_text)) >= min_alt_frac * len(swap_norm(base_text)):
        return alt_text, True
    return base_text, False
