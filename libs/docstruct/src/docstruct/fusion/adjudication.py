"""Protocolo de decisão do adjudicador e filtros de segurança.

Porta de ``adjudicate_v0.py``, ``adjudicate_v1.py``, ``vlm_adjudicate.py`` e
``filter_adjudications.py`` do Dr.DocBench (PR #125).

Três camadas:

- ``decide_v0`` / ``decide_v1`` — roteador por página entre Docling e MinerU,
  sem inferência nova. v0 usa "MinerU tem tabela/fórmula" como razão; v1 é
  component-aware (ambos emitem tabelas e fórmulas, então a preferência é
  explícita).
- ``decide`` — converte a transcrição exata do VLM em uma decisão do differ:
  ``select_a``/``select_b`` quando a transcrição coincide com um candidato,
  ``replace`` quando é plausível mas diferente, ``drop`` quando não é suportada.
  Respostas implausíveis devolvem ``None`` para manter a regra determinística.
- ``filter_decision`` — filtros de segurança sobre as decisões do VLM:
  ``notab`` (nunca trocar através de blocos estruturais), ``tight`` (limita o
  tamanho relativo da substituição) e ``sel`` (nunca injetar texto do VLM).

Funções puras, sem I/O e sem dependências pesadas.
"""
from __future__ import annotations

import difflib
import re
from collections import Counter
from typing import Optional

from docstruct.text.math_spans import inline_math_sources

TABLE_RE = re.compile(r"<table", re.IGNORECASE)
FORMULA_RE = re.compile(r"\$\$|\\\[|\\\(")
IMG_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MARKUP_RE = re.compile(r"[#*_`|>$\\\[\]{}()\-]")
_WS_RE = re.compile(r"\s+")

# Abaixo deste comprimento de texto útil a página é considerada quase vazia.
NEAR_EMPTY = 40

# Prefixos de blocos estruturais (tabela, imagem, fórmula).
STRUCT_PREFIXES = ("<table", "<img", "$$", "![", "<eq")

# Limiares do protocolo do adjudicador VLM.
SELECT_RATIO = 0.96
UNSUPPORTED_RATIO = 0.25
UNSUPPORTED_LEN_FRAC = 0.3
PAIR_REPLACE_LO, PAIR_REPLACE_HI = 0.5, 3.0
UNI_REPLACE_LO, UNI_REPLACE_HI = 0.4, 3.0

# Limiares do filtro ``tight``.
TIGHT_LO, TIGHT_HI = 0.6, 1.6

FILTERS = ("notab", "tight", "sel")


def useful_text(md: str) -> str:
    """Texto útil de uma página: sem header, imagens, tags e pontuação de marcação."""
    md = md.replace("# Dr.DocBench page", "")
    md = IMG_RE.sub(" ", md)
    md = _HTML_TAG_RE.sub(" ", md)
    md = _MARKUP_RE.sub(" ", md)
    return _WS_RE.sub(" ", md).strip()


def norm_text(md: str) -> str:
    """Normalização usada pela análise de concordância do ``eval_summary``."""
    md = _HTML_TAG_RE.sub(" ", md)
    md = re.sub(r"[#*_`|>$\\\[\]{}]", " ", md)
    return _WS_RE.sub(" ", md).strip().lower()


def nrm(s: Optional[str]) -> str:
    """Normalização leve usada pelo adjudicador VLM."""
    return _WS_RE.sub(" ", re.sub(r"[#*_`>|]", "", s or "")).strip().lower()


def ratio(a: str, b: str) -> float:
    """Similaridade difflib sobre ``nrm`` (usada pelo adjudicador VLM)."""
    return difflib.SequenceMatcher(None, nrm(a), nrm(b), autojunk=False).ratio()


def filter_nrm(s: Optional[str]) -> str:
    """Normalização usada pelos filtros de segurança (só colapsa espaços)."""
    return _WS_RE.sub(" ", s or "").strip()


def is_struct(md: Optional[str]) -> bool:
    """True se ``md`` é um bloco estrutural (tabela, imagem, fórmula)."""
    return (md or "").lstrip().startswith(STRUCT_PREFIXES)


def decide_v0(doc: str, min_: str) -> tuple[str, str]:
    """Roteador v0: devolve ``(escolha, razão)``.

    MinerU vence se tiver tabela ou fórmula (o pipeline Docling as achata), ou
    se o Docling estiver quase vazio. Caso contrário vence o Docling, que tem
    melhor distância de edição de texto no dev.
    """
    if TABLE_RE.search(min_):
        return "mineru", "mineru_has_table"
    if FORMULA_RE.search(min_) or inline_math_sources(min_):
        return "mineru", "mineru_has_formula"
    ld, lm = len(useful_text(doc)), len(useful_text(min_))
    if ld < NEAR_EMPTY <= lm:
        return "mineru", "docling_near_empty"
    if lm < NEAR_EMPTY <= ld:
        return "docling", "mineru_near_empty"
    return "docling", "default_docling_text"


def decide_v1(
    doc: str,
    min_: str,
    table_pref: str = "mineru",
    formula_pref: str = "mineru",
    text_pref: str = "docling",
) -> tuple[str, str]:
    """Roteador v1 component-aware: devolve ``(escolha, razão)``.

    Ordem: quase vazio, tabela (só um lado, ou preferência quando ambos),
    fórmula (idem), e por fim a preferência de texto.
    """
    ld, lm = len(useful_text(doc)), len(useful_text(min_))
    if ld < NEAR_EMPTY <= lm:
        return "mineru", "docling_near_empty"
    if lm < NEAR_EMPTY <= ld:
        return "docling", "mineru_near_empty"
    td, tm = bool(TABLE_RE.search(doc)), bool(TABLE_RE.search(min_))
    if td != tm:
        return ("docling", "only_docling_table") if td else ("mineru", "only_mineru_table")
    if td and tm:
        return table_pref, f"both_table->{table_pref}"
    fd = bool(FORMULA_RE.search(doc) or inline_math_sources(doc))
    fm = bool(FORMULA_RE.search(min_) or inline_math_sources(min_))
    if fd != fm:
        return ("docling", "only_docling_formula") if fd else ("mineru", "only_mineru_formula")
    if fd and fm:
        return formula_pref, f"both_formula->{formula_pref}"
    return text_pref, f"default_{text_pref}"


def clean_transcription(t: str) -> str:
    """Remove cercas de código e trata ``<EMPTY>`` como transcrição vazia."""
    t = re.sub(r"^```[a-z]*\n?|```$", "", (t or "").strip()).strip()
    return "" if t == "<EMPTY>" else t


def decide(r: dict, t: str, stats: Counter) -> Optional[dict]:
    """Converte a transcrição ``t`` em uma decisão do differ.

    ``r`` é um registro da fila de adjudicação (``i``/``j`` >= 0 = par casado,
    caso contrário bloco unilateral). Devolve ``None`` quando a resposta é
    implausível, para que a regra determinística do differ permaneça.
    """
    a, b = r.get("md_d") or "", r.get("md_m") or ""
    if r["i"] >= 0 and r["j"] >= 0:  # par casado
        if not t:
            stats["pair-empty"] += 1
            return None
        ra, rb = ratio(t, a), ratio(t, b)
        if max(ra, rb) >= SELECT_RATIO:
            stats["pair-select"] += 1
            return {"action": "select_a" if ra >= rb else "select_b"}
        lm = max(len(nrm(a)), len(nrm(b)))
        if lm and PAIR_REPLACE_LO * lm <= len(nrm(t)) <= PAIR_REPLACE_HI * lm:
            stats["pair-replace"] += 1
            return {"action": "replace", "text": t}
        stats["pair-implausible"] += 1
        return None
    cand = a or b  # bloco unilateral (só um provider)
    if not t:
        stats["uni-drop-empty"] += 1
        return {"action": "drop"}
    rc = ratio(t, cand)
    if rc >= SELECT_RATIO:
        stats["uni-keep"] += 1
        return None
    if rc <= UNSUPPORTED_RATIO and len(nrm(t)) < UNSUPPORTED_LEN_FRAC * len(nrm(cand)):
        stats["uni-drop-unsupported"] += 1
        return {"action": "drop"}
    if UNI_REPLACE_LO * len(nrm(cand)) <= len(nrm(t)) <= UNI_REPLACE_HI * len(nrm(cand)):
        stats["uni-replace"] += 1
        return {"action": "replace", "text": t}
    stats["uni-implausible"] += 1
    return None


def filter_decision(x: dict, record: dict, kind: str) -> bool:
    """True se a decisão ``x`` sobrevive ao filtro de segurança ``kind``.

    ``record`` é o registro correspondente da fila (com ``md_d``/``md_m``).
    ``kind`` é ``"notab"``, ``"tight"`` ou ``"sel"``.
    """
    if kind not in FILTERS:
        raise ValueError(f"kind must be one of {FILTERS}, got {kind!r}")
    cands = [record.get("md_d"), record.get("md_m")]
    anystruct = any(is_struct(c) for c in cands if c)
    if x["action"] == "replace":
        if anystruct:
            return False
        if kind == "sel":
            return False
        if kind == "tight":
            cand = max((filter_nrm(c) for c in cands if c), key=len, default="")
            rt = len(filter_nrm(x.get("text"))) / max(1, len(cand))
            return TIGHT_LO <= rt <= TIGHT_HI
        return True
    if anystruct and x["action"].startswith("select") and is_struct(cands[0]) != is_struct(cands[1]):
        return False
    return True
