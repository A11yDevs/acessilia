"""Especialista de tabela: geração-comparação-adjudicação.

Porta de ``vlm_tables.py`` do Dr.DocBench (PR #125).

Para cada bloco de tabela da fila de adjudicação, o VLM regenera a tabela como
HTML a partir do recorte (1 greedy + N amostras), usando as tabelas dos
providers como dicas. Os candidatos são {tabela Docling, tabela MinerU,
gerações do VLM}; o **medoide** por similaridade pareada é selecionado
(auto-consistência): se o vencedor é um provider, a decisão é
``select_a``/``select_b``; se é uma geração do VLM, é ``replace`` com o HTML.

A similaridade (TEDS no script) é **injetada** pelo chamador, para que a
biblioteca continue sem dependências pesadas e sem o repositório do benchmark.

Funções puras, sem I/O.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Callable, Optional

TABLE_RE = re.compile(r"<table[\s\S]*?</table>", re.I)
_FENCE_RE = re.compile(r"```[a-z]*")
_TABLE_OPEN_RE = re.compile(r"<table[^>]*>")
_TH_RE = re.compile(r"<(/?)th\b")
_DROP_TAG_RE = re.compile(r"</?(thead|tbody|tfoot|eq|span|div|p|br)\b[^>]*>")
_CELL_OPEN_RE = re.compile(r"<(td|tr)\b([^>]*)>")
_SPAN_ATTR_RE = re.compile(r'(colspan|rowspan)\s*=\s*"?(\d+)"?')

# Similaridade acima da qual a geração greedy é considerada igual a um provider.
GREEDY_CLOSE = 0.98


def extract_table(t: str) -> str:
    """Extrai o primeiro ``<table>...</table>`` de ``t`` (removendo cercas de código)."""
    t = _FENCE_RE.sub("", t or "")
    m = TABLE_RE.search(t)
    return m.group(0) if m else ""


def norm_table(t: str) -> str:
    """Normaliza uma tabela no estilo do avaliador.

    Remove atributos da tag ``<table>``, converte ``<th>`` em ``<td>``, remove
    tags não estruturais e mantém apenas ``colspan``/``rowspan`` nas células.
    """
    t = _TABLE_OPEN_RE.sub("<table>", t)
    t = _TH_RE.sub(r"<\1td", t)
    t = _DROP_TAG_RE.sub("", t)

    def _cell(m: re.Match) -> str:
        attrs = "".join(
            f' {k}="{v}"' for k, v in _SPAN_ATTR_RE.findall(m.group(2))
        )
        return f"<{m.group(1)}{attrs}>"

    return _CELL_OPEN_RE.sub(_cell, t)


def is_valid_table(t: str) -> bool:
    """True se ``t`` tem ao menos uma linha e uma célula."""
    return bool(t) and t.count("<tr") >= 1 and ("<td" in t or "<th" in t)


def build_candidates(
    record: dict,
    greedy: str = "",
    samples: Optional[list[str]] = None,
    max_chars: int = 0,
) -> list[tuple[str, str]]:
    """Monta a lista de candidatos ``(nome, html)`` para um registro de tabela.

    ``a``/``b`` são as tabelas dos providers (só quando o ``kind`` é ``table`` e
    o HTML é válido); ``v0`` é a geração greedy e ``v1..`` as amostras. Gerações
    acima de ``max_chars`` (quando > 0) são descartadas.
    """
    cands: list[tuple[str, str]] = []
    if record.get("kind_d") == "table":
        html = extract_table(record.get("md_d"))
        if is_valid_table(html):
            cands.append(("a", html))
    if record.get("kind_m") == "table":
        html = extract_table(record.get("md_m"))
        if is_valid_table(html):
            cands.append(("b", html))
    gens = [extract_table(g) for g in [greedy] + list(samples or [])]
    for k, g in enumerate(gens):
        if is_valid_table(g) and (max_chars <= 0 or len(g) <= max_chars):
            cands.append((f"v{k}", g))
    return cands


def medoid_index(
    candidates: list[tuple[str, str]],
    similarity: Callable[[str, str], float],
) -> int:
    """Índice do medoide: maior soma de similaridades pareadas.

    Empate vai para o menor índice, o que prefere os providers (determinísticos)
    e depois a geração greedy.
    """
    n = len(candidates)
    if n == 0:
        raise ValueError("medoid_index requires at least one candidate")
    normed = [norm_table(h) for _, h in candidates]
    tot = [0.0] * n
    for x in range(n):
        for y in range(x + 1, n):
            s = similarity(normed[x], normed[y])
            tot[x] += s
            tot[y] += s
    return max(range(n), key=lambda k: (round(tot[k], 6), -k))


def pairwise_similarity(
    candidates: list[tuple[str, str]],
    similarity: Callable[[str, str], float],
) -> dict[tuple[int, int], float]:
    """Similaridade pareada entre todos os candidatos (chave ordenada)."""
    normed = [norm_table(h) for _, h in candidates]
    out: dict[tuple[int, int], float] = {}
    for x in range(len(normed)):
        for y in range(x + 1, len(normed)):
            out[(x, y)] = similarity(normed[x], normed[y])
    return out


def select_table(
    record: dict,
    greedy: str,
    samples: Optional[list[str]],
    similarity: Callable[[str, str], float],
    max_chars: int = 0,
) -> tuple[Optional[dict], Counter]:
    """Seleciona a decisão do medoide para um registro de tabela.

    Devolve ``(decisão, stats)``. A decisão é ``{"action": "select_a"|"select_b"}``
    ou ``{"action": "replace", "text": html}``; ``None`` quando não há candidatos.
    """
    stats: Counter = Counter()
    cands = build_candidates(record, greedy, samples, max_chars)
    if not cands:
        stats["no-cand"] += 1
        return None, stats
    best = medoid_index(cands, similarity)
    name = cands[best][0]
    stats[f"medoid-{name[0]}"] += 1
    if name in ("a", "b"):
        return {"action": f"select_{name}"}, stats
    return {"action": "replace", "text": cands[best][1]}, stats


def select_greedy(
    record: dict,
    greedy: str,
    samples: Optional[list[str]],
    similarity: Callable[[str, str], float],
    max_chars: int = 0,
) -> tuple[Optional[dict], Counter]:
    """Seleciona a decisão da geração greedy.

    Usa a greedy a menos que ela seja ~idêntica a uma tabela de provider
    (similaridade >= ``GREEDY_CLOSE``), caso em que apenas seleciona o provider.
    """
    stats: Counter = Counter()
    cands = build_candidates(record, greedy, samples, max_chars)
    names = [n for n, _ in cands]
    if "v0" not in names:
        stats["no-greedy"] += 1
        return None, stats
    g = names.index("v0")
    sim = pairwise_similarity(cands, similarity)
    close = [
        (sim.get((min(g, k), max(g, k)), 0.0), names[k])
        for k in range(len(cands))
        if names[k] in ("a", "b")
    ]
    s, pn = max(close) if close else (0.0, "")
    if s >= GREEDY_CLOSE:
        stats["greedy-select"] += 1
        return {"action": f"select_{pn}"}, stats
    stats["greedy-replace"] += 1
    return {"action": "replace", "text": cands[g][1]}, stats
