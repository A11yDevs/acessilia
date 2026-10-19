"""Disciplina de holdout: split por documento e critério de aceite.

Porta da disciplina do loop do Dr.DocBench (PR #125).

O split é **por documento**, não por página: páginas do mesmo documento são
correlacionadas, então dividi-las entre tune e holdout vazaria informação. O
split é determinístico (``md5(doc_id) % 3 == 0`` → holdout, 1/3 das páginas).

O critério de aceite exige ganho no tune **e** ausência de perda no holdout, e
nenhuma métrica pode cair além de uma tolerância. Isso existe porque o gap
dev→test observado é de ~8 pontos e o TEDS não transferiu (dev +5.9 → test
+0.2): um ganho no dev não é um resultado.

Funções puras, sem I/O e sem dependências pesadas.
"""
from __future__ import annotations

import hashlib
import math
import statistics
from dataclasses import dataclass

# Fração do split que vai para o holdout (1/3).
HOLDOUT_MODULUS = 3
HOLDOUT_REMAINDER = 0

# Critério de aceite.
MIN_TUNE_GAIN = 0.10  # Δtune mínimo para considerar o ganho real
MIN_HOLDOUT_GAIN = 0.0  # Δhold não pode ser negativo
MAX_METRIC_LOSS = 0.3  # nenhuma métrica pode cair mais que isto

# Métricas que compõem o Overall do loop.
LOOP_METRICS = ("text", "reading_order", "teds")


def document_id(window: str) -> str:
    """Id do documento a partir do id de janela (``<doc>_page_<N>``)."""
    return window.split("_page_")[0]


def partition(window: str) -> str:
    """``"hold"`` ou ``"tune"`` para uma janela, pelo md5 do id do documento."""
    digest = int(hashlib.md5(document_id(window).encode()).hexdigest(), 16)
    return "hold" if digest % HOLDOUT_MODULUS == HOLDOUT_REMAINDER else "tune"


def score(windows: dict[str, dict], subset: str, metrics: tuple[str, ...] = LOOP_METRICS) -> dict:
    """Média por métrica e o ``evalai`` (média das métricas) em um subconjunto.

    ``subset`` é ``"tune"``, ``"hold"`` ou ``"all"``. Métricas ausentes
    (``None``) não entram na média; uma métrica sem nenhum valor no subconjunto
    fica ``nan`` e não entra no ``evalai``, que só é ``nan`` sem nenhuma.
    """
    out: dict[str, float] = {}
    for metric in metrics:
        values = [
            w[metric]
            for key, w in windows.items()
            if (subset == "all" or partition(key) == subset) and w.get(metric) is not None
        ]
        out[metric] = statistics.mean(values) if values else float("nan")
    present = [out[m] for m in metrics if not math.isnan(out[m])]
    out["evalai"] = statistics.mean(present) if present else float("nan")
    return out


@dataclass(frozen=True)
class Verdict:
    """Resultado do critério de aceite."""

    accepted: bool
    reason: str
    tune_delta: float
    holdout_delta: float
    metric_deltas: dict[str, float]


def evaluate_candidate(
    base: dict[str, dict],
    candidate: dict[str, dict],
    metrics: tuple[str, ...] = LOOP_METRICS,
    min_tune_gain: float = MIN_TUNE_GAIN,
    min_holdout_gain: float = MIN_HOLDOUT_GAIN,
    max_metric_loss: float = MAX_METRIC_LOSS,
) -> Verdict:
    """Aplica o critério de aceite a um candidato contra a base.

    Aceita quando: Δtune ≥ ``min_tune_gain``, Δhold ≥ ``min_holdout_gain`` e
    nenhuma métrica cai mais que ``max_metric_loss`` em nenhum dos dois
    subconjuntos.
    """
    tune_base, tune_cand = score(base, "tune", metrics), score(candidate, "tune", metrics)
    hold_base, hold_cand = score(base, "hold", metrics), score(candidate, "hold", metrics)
    tune_delta = tune_cand["evalai"] - tune_base["evalai"]
    hold_delta = hold_cand["evalai"] - hold_base["evalai"]
    metric_deltas = {f"tune_{m}": tune_cand[m] - tune_base[m] for m in metrics}
    metric_deltas.update({f"hold_{m}": hold_cand[m] - hold_base[m] for m in metrics})

    # nan não perde nem ganha de nada: sem páginas pontuáveis em um dos
    # subconjuntos o critério não tem como ser verificado.
    if math.isnan(tune_delta) or math.isnan(hold_delta):
        return Verdict(
            False, "sem páginas pontuáveis em tune ou hold",
            tune_delta, hold_delta, metric_deltas,
        )
    if tune_delta < min_tune_gain:
        return Verdict(
            False, f"Δtune {tune_delta:+.2f} < {min_tune_gain:+.2f}",
            tune_delta, hold_delta, metric_deltas,
        )
    if hold_delta < min_holdout_gain:
        return Verdict(
            False, f"Δhold {hold_delta:+.2f} < {min_holdout_gain:+.2f}",
            tune_delta, hold_delta, metric_deltas,
        )
    comparable = [kv for kv in metric_deltas.items() if not math.isnan(kv[1])]
    worst = min(comparable, key=lambda kv: kv[1])
    if worst[1] < -max_metric_loss:
        return Verdict(
            False, f"{worst[0]} {worst[1]:+.2f} < -{max_metric_loss:.2f}",
            tune_delta, hold_delta, metric_deltas,
        )
    return Verdict(True, "aceito", tune_delta, hold_delta, metric_deltas)
