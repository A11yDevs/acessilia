"""Algoritmo Húngaro (Kuhn-Munkres) puro, O(n³), com potenciais.

Substitui ``scipy.optimize.linear_sum_assignment`` para manter a lib com
zero dependências. Matrizes de custo de fusão são pequenas (blocos por
página < 100), então o custo de não usar scipy é desprezível.
"""
from __future__ import annotations

from typing import Sequence


def linear_sum_assignment(cost: Sequence[Sequence[float]]) -> list[tuple[int, int]]:
    """Atribuição bipartida de custo mínimo.

    Retorna pares (linha, coluna) otimais. Matrizes retangulares são
    tratadas por padding implícito (linhas/colunas extras de custo 0 não
    aparecem no resultado — apenas pares válidos são retornados).
    """
    n = len(cost)
    m = len(cost[0]) if n else 0
    if n == 0 or m == 0:
        return []

    size = max(n, m)
    INF = float("inf")
    # padding com 0-custo (não afeta ótimo de custo mínimo)
    a = [
        [cost[i][j] if i < n and j < m else 0.0 for j in range(size)]
        for i in range(size)
    ]

    u = [0.0] * (size + 1)
    v = [0.0] * (size + 1)
    p = [0] * (size + 1)   # p[j] = linha atribuída à coluna j (1-based)
    way = [0] * (size + 1)

    for i in range(1, size + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (size + 1)
        used = [False] * (size + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = INF
            j1 = -1
            for j in range(1, size + 1):
                if not used[j]:
                    cur = a[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j] = cur
                        way[j] = j0
                    if minv[j] < delta:
                        delta = minv[j]
                        j1 = j
            for j in range(size + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1

    result = []
    for j in range(1, size + 1):
        i = p[j] - 1
        if i < n and j - 1 < m:
            result.append((i, j - 1))
    return result
