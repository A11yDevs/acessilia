"""Lê as métricas do Prometheus e imprime como tabela.

Rodar durante ou logo após a carga:
    poetry run python observability/metricas/consultar.py

As consultas ficam em observability/config.py. Precisa da API com ENABLE_METRICS=true e do
profile monitoring no ar; métrica que o exporter não fornecer sai como "—".
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from observability import config  # noqa: E402


def consultar(cliente: httpx.Client, expressao: str) -> str:
    """Executa uma query instantânea e devolve o valor já formatado."""
    try:
        resposta = cliente.get("/api/v1/query", params={"query": expressao})
        resposta.raise_for_status()
        resultado = resposta.json()["data"]["result"]
    except Exception:
        # Exporter ausente ou Prometheus fora do ar não interrompem o relatório:
        # a linha vira "—" e as outras métricas continuam sendo lidas.
        return "—"

    if not resultado:
        return "—"

    valor = float(resultado[0]["value"][1])
    return f"{valor:,.2f}".replace(",", " ")


def tabela(cliente: httpx.Client, titulo: str, consultas: dict[str, str]) -> None:
    if not consultas:
        return

    largura = max(len(nome) for nome in consultas)
    print(f"\n{titulo}")
    print("-" * (largura + 14))
    for nome, expressao in consultas.items():
        print(f"{nome:<{largura}}  {consultar(cliente, expressao):>10}")


def main() -> int:
    if not config.PROMETHEUS:
        print("PROMETHEUS vazio em observability/config.py; nada a consultar.")
        return 0

    print(config.resumo())

    try:
        with httpx.Client(base_url=config.PROMETHEUS, timeout=10) as cliente:
            tabela(cliente, "API", config.METRICAS_API)
            tabela(cliente, "Pipeline", config.METRICAS_PIPELINE)
            tabela(cliente, "LLM", config.METRICAS_LLM)
            tabela(cliente, "Máquina", config.METRICAS_MAQUINA)
    except httpx.HTTPError as erro:
        print(f"Prometheus inacessível em {config.PROMETHEUS}: {erro}")
        return 1

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
