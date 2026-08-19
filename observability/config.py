"""Configuração dos testes de carga e das métricas coletadas.

Edite os valores abaixo e rode:
    poetry run locust -f observability/testes_de_carga/locustfile.py

Todo valor aceita variável de ambiente com o mesmo nome, para rodar variações sem
editar o arquivo (o tipo é convertido sozinho):
    DEGRAUS="5,10,20" DURACAO_POR_DEGRAU=5m poetry run locust -f ...

A suíte unitária em tests/ não lê nada daqui.
"""

from __future__ import annotations

import os
from pathlib import Path


RAIZ = Path(__file__).resolve().parent.parent
FIXTURES_DIR = RAIZ / "tests" / "fixtures"   # reaproveita os PDFs da suíte de testes


# ═════════════════════════════════════════════════════════════════════ ALVO ══

HOST = "http://localhost:8000"        # a API. Dentro de container: http://host.docker.internal:8000
PROMETHEUS = "http://localhost:9090"  # do profile monitoring. "" para não consultar métricas


# ══════════════════════════════════════════════════════════════════ BATERIA ══
#
#  |<- aquecimento ->|<-- subida -->|<---- DURAÇÃO: mede aqui ---->|<- descanso ->|
#
# O tempo total passa de degraus × duração: aquecimento, subida e descanso ficam de fora.

DEGRAUS = [1, 2, 5, 10, 20, 40, 80]   # uma rodada para cada número de usuários
DURACAO_POR_DEGRAU = "5m"             # tempo medido por degrau. Abaixo de 1m o p95 fica instável
DESCANSO_ENTRE_DEGRAUS = 60           # segundos de pausa entre degraus, para as filas esvaziarem
AQUECIMENTO = 60                      # segundos de carga jogados fora antes de medir. 0 para pular
USUARIOS_POR_SEGUNDO = 2              # ritmo de entrada dos usuários. A subida não entra na medição
PARAR_COM_FALHAS = 60.0               # interrompe a bateria acima deste % de falhas. 100 = nunca para


# ══════════════════════════════════════════════════ COMPORTAMENTO DO USUÁRIO ══

INTERVALO_ENTRE_REQUISICOES = (1, 3)  # pausa (mín, máx) entre requisições do mesmo usuário
DISPARO_IMEDIATO = False              # zera o intervalo: mede vazão máxima, não quantas pessoas cabem
ENVIAR_DOCUMENTOS = False             # envia documento de verdade: dispara LLM e gasta dinheiro
DOCUMENTO = FIXTURES_DIR / "tutorials" / "java-oo-3pgs.pdf"   # usado quando ENVIAR_DOCUMENTOS liga
MODO = "normal"                       # modo: detalhado, medio, normal, baixo ou ocr
ORIGEM = "load-test"                  # marca os jobs no histórico, para separar do tráfego real


# ══════════════════════════════════════════════════════════════ HEALTHCHECK ══
# Quem bate no /health é o Docker, em ritmo fixo. Por isso a quantidade é fixa e
# fica fora da conta de usuários do degrau.

MONITORES_HEALTH = 2                  # quantos monitores constantes. 0 desliga
INTERVALO_HEALTH = 5                  # segundos entre um health e outro


# ═════════════════════════════════════════════════════════════════════ REDE ══

TIMEOUT = (10, 90)                    # (conectar, esperar resposta) em segundos


# ════════════════════════════════════════════════════════════════════ ROTAS ══

ROTA_HEALTH = "/api/v1/health"
ROTA_STATS = "/api/v1/stats"
ROTA_HISTORY = "/api/v1/history?limit=20"
ROTA_JOBS = "/api/v1/jobs"


# ══════════════════════════════════════════════════ MÉTRICAS DO PROMETHEUS ══
# Lidas por observability/metricas/consultar.py e impressas como tabela.
# Métrica que o exporter não fornecer sai como "—", sem quebrar nada.
# Requer ENABLE_METRICS=true na API e o profile monitoring no ar.

METRICAS_API = {
    "Req/s": 'sum(rate(http_requests_total{job="acessilia-api"}[1m]))',
    "Erros %": (
        'sum(rate(http_requests_total{job="acessilia-api",status=~"5.."}[1m])) '
        '/ clamp_min(sum(rate(http_requests_total{job="acessilia-api"}[1m])), 0.001) * 100'
    ),
    "p95 (s)": (
        "histogram_quantile(0.95, sum by (le) "
        '(rate(http_request_duration_seconds_bucket{job="acessilia-api"}[1m])))'
    ),
}

METRICAS_PIPELINE = {
    "Fila": "acessilia_queue_size",
    "Jobs ativos": "sum(acessilia_jobs_active)",
    "Jobs acumulados": "sum(acessilia_jobs_total)",
    "Erros pipeline acumulados": "sum(acessilia_pipeline_errors_total)",
    "Duração média (s)": (
        "sum(acessilia_conversion_duration_seconds_sum) "
        "/ clamp_min(sum(acessilia_conversion_duration_seconds_count), 1)"
    ),
    "Exportações acumuladas": "sum(acessilia_exports_total)",
}

METRICAS_LLM = {
    "Chamadas LLM acumuladas": "sum(acessilia_llm_calls_total)",
    "Falhas LLM acumuladas": "sum(acessilia_llm_failures_total)",
    "Duração LLM média (s)": (
        "sum(acessilia_llm_duration_seconds_sum) "
        "/ clamp_min(sum(acessilia_llm_duration_seconds_count), 1)"
    ),
}

METRICAS_MAQUINA = {  # node-exporter
    "CPU %": '100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[1m])) * 100)',
    "RAM %": "avg((1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100)",
    # Tempo em que tarefas ficaram esperando CPU. Sinal mais direto de saturação que
    # "CPU em 80%": 80% sem ninguém na fila é saudável, 50% com fila não é.
    "PSI CPU": "avg(rate(node_pressure_cpu_waiting_seconds_total[1m]))",
}


# ─────────────────────────────────────────────────────────────────────────────
# Daqui para baixo é encanamento; não precisa mexer para configurar nada.
# ─────────────────────────────────────────────────────────────────────────────


def segundos(valor: str | int | float) -> int:
    """Converte '10m' ou '300s' em segundos."""
    if isinstance(valor, (int, float)):
        return int(valor)
    texto = valor.strip().lower()
    if texto.endswith("m"):
        return int(float(texto[:-1]) * 60)
    if texto.endswith("s"):
        return int(float(texto[:-1]))
    return int(float(texto))


def _converter(bruto: str, referencia):
    """Converte o texto vindo do ambiente para o tipo do valor configurado acima.

    O próprio valor escrito no arquivo serve de referência de tipo, então
    DEGRAUS="5,10" vira lista de int e AQUECIMENTO=30 vira int, sem precisar
    declarar o tipo em lugar nenhum.
    """
    if isinstance(referencia, bool):
        return bruto.lower() in ("1", "true", "sim", "yes", "on")
    if isinstance(referencia, Path):
        return Path(bruto).expanduser()
    if isinstance(referencia, list):
        return [int(x) for x in bruto.split(",") if x.strip()]
    if isinstance(referencia, tuple):
        partes = [float(x) for x in bruto.split(",")]
        return (partes[0], partes[-1])
    if isinstance(referencia, int):
        return int(float(bruto))
    if isinstance(referencia, float):
        return float(bruto)
    return bruto


def _aplicar_variaveis_de_ambiente(escopo: dict) -> None:
    """Sobrescreve as constantes com o que vier do ambiente.

    Fica aqui embaixo, e não repetido em cada linha, para o topo do arquivo ser só
    a configuração. Valor inválido é ignorado: um teste de carga não deve morrer
    por causa de um typo numa variável.
    """
    for nome, valor in list(escopo.items()):
        if not nome.isupper() or isinstance(valor, dict):
            continue
        bruto = os.environ.get(nome, "").strip()
        if not bruto:
            continue
        try:
            escopo[nome] = _converter(bruto, valor)
        except (ValueError, TypeError):
            pass


_aplicar_variaveis_de_ambiente(globals())

# Depois do ambiente, para que DISPARO_IMEDIATO=true também zere o intervalo.
if DISPARO_IMEDIATO:
    INTERVALO_ENTRE_REQUISICOES = (0.0, 0.0)


def resumo() -> str:
    """Uma linha para o log e o cabeçalho do relatório."""
    if DISPARO_IMEDIATO:
        ritmo = "disparo imediato (vazão máxima)"
    else:
        minimo, maximo = INTERVALO_ENTRE_REQUISICOES
        ritmo = f"intervalo de {minimo:g} a {maximo:g}s"
    documentos = "ENVIANDO documentos (gasta LLM)" if ENVIAR_DOCUMENTOS else "somente leitura"
    aquecimento = f"{AQUECIMENTO}s de aquecimento; " if AQUECIMENTO else ""
    return (
        f"{len(DEGRAUS)} degraus {DEGRAUS} de {DURACAO_POR_DEGRAU} cada; "
        f"{aquecimento}{ritmo}; {documentos}; "
        f"{MONITORES_HEALTH} monitores de health; alvo {HOST}"
    )
