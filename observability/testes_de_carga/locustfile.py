"""Cenário de carga contra a API REST.

Rodar (a API precisa estar no ar):
    poetry run locust -f observability/testes_de_carga/locustfile.py

Os parâmetros ficam em observability/config.py. A bateria de degraus é aplicada
pela classe Degraus abaixo, então não é preciso passar --users nem --spawn-rate.

O tempo medido aqui é do lado cliente, com rede. A latência interna aparece no
Prometheus; os dois números não batem exatamente e não deveriam bater.
"""

from __future__ import annotations

import sys
from pathlib import Path

from locust import HttpUser, LoadTestShape, between, constant, events, task


# A raiz do repositório precisa estar no path: o locust executa este arquivo direto.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from observability import config  # noqa: E402


@events.init.add_listener
def _mostrar_config(environment, **_):
    print(f"[carga] {config.resumo()}")


class UsuarioLeitura(HttpUser):
    """Usuário comum. Só bate nas rotas de leitura, a menos que ENVIAR_DOCUMENTOS ligue."""

    host = config.HOST
    wait_time = between(*config.INTERVALO_ENTRE_REQUISICOES)

    @task(3)
    def health(self):
        self.client.get(config.ROTA_HEALTH, name="health", timeout=config.TIMEOUT)

    @task(2)
    def stats(self):
        self.client.get(config.ROTA_STATS, name="stats", timeout=config.TIMEOUT)

    @task(1)
    def history(self):
        self.client.get(config.ROTA_HISTORY, name="history", timeout=config.TIMEOUT)

    @task
    def enviar_documento(self):
        """Cada envio dispara LLM e custa tokens; por isso é opt-in."""
        if not config.ENVIAR_DOCUMENTOS or not config.DOCUMENTO.exists():
            return

        with config.DOCUMENTO.open("rb") as arquivo:
            resposta = self.client.post(
                config.ROTA_JOBS,
                files={"document_file": (config.DOCUMENTO.name, arquivo, "application/pdf")},
                data={"mode": config.MODO, "source": config.ORIGEM},
                name="submit job",
                timeout=config.TIMEOUT,
            )

        if resposta.status_code != 202:
            return

        task_id = resposta.json().get("task_id")
        if task_id:
            # Uma consulta só: acompanhar até concluir levaria minutos e distorceria
            # a vazão medida.
            self.client.get(
                f"{config.ROTA_JOBS}/{task_id}", name="job status", timeout=config.TIMEOUT
            )


class MonitorHealth(HttpUser):
    """O healthcheck do Docker, em ritmo fixo.

    Quantidade fixa e independente do degrau, porque na produção esse tráfego não
    cresce junto com o número de usuários.
    """

    host = config.HOST
    fixed_count = config.MONITORES_HEALTH
    wait_time = constant(config.INTERVALO_HEALTH)

    @task
    def health(self):
        self.client.get(config.ROTA_HEALTH, name="health (monitor)", timeout=config.TIMEOUT)


class Degraus(LoadTestShape):
    """Executa DEGRAUS em sequência, medindo cada um por DURACAO_POR_DEGRAU.

    Antes da bateria roda o aquecimento, cujas requisições são descartadas: sem isso
    o primeiro degrau pagaria o custo de sistema frio (conexões, caches, imports) e
    viraria uma linha de base ruim.

    Entre degraus há uma janela com zero usuários, para as filas esvaziarem e um
    degrau não contaminar a medição do seguinte.
    """

    def __init__(self):
        super().__init__()
        self._duracao = config.segundos(config.DURACAO_POR_DEGRAU)
        self._ciclo = self._duracao + config.DESCANSO_ENTRE_DEGRAUS
        self._aquecimento = max(0, int(config.AQUECIMENTO))
        self._zerou_aquecimento = False
        self._classes = [UsuarioLeitura]
        if config.MONITORES_HEALTH > 0:
            self._classes.append(MonitorHealth)

    def tick(self):
        decorrido = self.get_run_time()

        if decorrido < self._aquecimento:
            return self._alvo(config.DEGRAUS[0])

        if not self._zerou_aquecimento:
            # Descarta o que o aquecimento produziu para o primeiro degrau começar limpo.
            if self._aquecimento:
                self.runner.stats.reset_all()
            self._zerou_aquecimento = True

        na_bateria = decorrido - self._aquecimento
        indice = int(na_bateria // self._ciclo)

        if indice >= len(config.DEGRAUS) or self._falhas_demais():
            return None

        if na_bateria % self._ciclo >= self._duracao:
            return self._alvo(0)  # descanso

        return self._alvo(config.DEGRAUS[indice])

    def _alvo(self, usuarios: int):
        """Monitores de health entram por cima do degrau, não descontam dele."""
        total = usuarios + (config.MONITORES_HEALTH if usuarios else 0)
        return (total, config.USUARIOS_POR_SEGUNDO, self._classes)

    def _falhas_demais(self) -> bool:
        estatisticas = self.runner.stats.total
        if not estatisticas.num_requests:
            return False
        return estatisticas.num_failures / estatisticas.num_requests * 100 > config.PARAR_COM_FALHAS
