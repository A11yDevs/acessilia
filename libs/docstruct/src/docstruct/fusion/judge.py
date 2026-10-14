"""Regra pura do juiz pareado por VLM.

Porta da decisão de ``vlm_page_judge.py`` e do LOOP #45 do Dr.DocBench (PR #125).

O juiz vê a imagem da página e duas transcrições candidatas (A, B) e diz qual é
mais fiel. As duas ordens são perguntadas (debiasing de posição) e ``p(B melhor)``
é a média das duas probabilidades do primeiro token.

A regra aceita (LOOP #45) é: adota a candidata nova quando ``p_new > 0.5``; caso
contrário, adota a antiga quando ``p_old > 0.2``. Só páginas onde A e B divergem
(ratio < ``max_ratio``, ambas não vazias) são julgadas.

Funções puras, sem I/O e sem dependências pesadas.
"""
from __future__ import annotations

import math

from docstruct.fusion.page_select import page_norm, ratio

# Limiar padrão para considerar a candidata nova melhor.
DEFAULT_NEW_THR = 0.5

# Limiar padrão para manter a candidata antiga quando a nova não vence.
DEFAULT_OLD_THR = 0.2

# Acima deste ratio as duas candidatas são consideradas iguais: não vale julgar.
DEFAULT_MAX_RATIO = 0.97


def debias(p_b_ab: float, p_a_ba: float) -> float:
    """Probabilidade de B ser melhor, corrigida do viés de posição.

    ``p_b_ab`` é P(B) na ordem (A, B) e ``p_a_ba`` é P(A) na ordem (B, A).
    A média das duas ordens cancela a preferência do modelo pela posição.
    """
    return (p_b_ab + 1 - p_a_ba) / 2


def p2_from_logprobs(logprobs: dict[str, float]) -> float:
    """P("2") normalizada entre "1" e "2" a partir das logprobs do primeiro token.

    Devolve ``0.5`` quando nenhum dos dois tokens aparece.
    """
    d = {k.strip(): math.exp(v) for k, v in logprobs.items()}
    p1, q2 = d.get("1", 0.0), d.get("2", 0.0)
    return q2 / (p1 + q2) if p1 + q2 > 0 else 0.5


def decide_pair(
    p_new: float,
    p_old: float,
    new_thr: float = DEFAULT_NEW_THR,
    old_thr: float = DEFAULT_OLD_THR,
) -> bool:
    """True se a candidata nova deve substituir a antiga.

    Regra do LOOP #45: adota a nova quando ``p_new > new_thr``; caso contrário
    consulta o juiz antigo e adota a nova quando ``p_old > old_thr``. Se nenhum
    dos dois convence, mantém a antiga.
    """
    return p_new > new_thr or p_old > old_thr


def should_judge(a_text: str, b_text: str, max_ratio: float = DEFAULT_MAX_RATIO) -> bool:
    """True se as duas candidatas divergem o bastante para valer julgar.

    Exige ambas não vazias e ratio de similaridade abaixo de ``max_ratio``.
    """
    na, nb = page_norm(a_text), page_norm(b_text)
    if not na or not nb:
        return False
    return ratio(na, nb) < max_ratio
