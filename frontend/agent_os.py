#!/usr/bin/env python3
"""AgentOS – Vitrine dos agentes do Acessília no painel do Agno (os.agno.com).

Este arquivo é INDEPENDENTE do pipeline de acessibilidade (run.py). Ele apenas
expõe os agentes de IA (visão e dados) como instâncias "de pé" para você
conversar com eles pelo painel do AgentOS, monitorar sessões, memória e traces.

Ele NÃO executa o pipeline completo (split de PDF -> classificação de regiões ->
visão/dados -> editor). Esse fluxo continua no run.py.

Como usar:
    1. Configure o .env (mesma key de LLM do projeto: OpenRouter ou Ollama).
    2. Rode:   python agent_os.py
       O runtime sobe em http://localhost:7777
    3. Abra https://os.agno.com , faça login, clique em "Add new OS",
       escolha Environment: Local, Endpoint URL: http://localhost:7777,
       dê um nome e clique em CONNECT.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media import Image  # noqa: F401  (disponível para testes multimodais no painel)
from agno.os import AgentOS

from backend.config.settings import settings
from backend.ai.models.ai_client import get_agno_model
from backend.tools.prompt_tools import load_region_prompt, load_system_prompt

# Banco de sessões/memória do AgentOS (fica no diretório de dados do projeto).
_db = SqliteDb(db_file=str(settings.data_dir / "agentos.db"))


def _build_data_instructions() -> str:
    """Instruções do agente de dados a partir dos prompts de tabela/fórmula."""
    partes = [
        load_region_prompt("regiao_tabela"),
        load_region_prompt("regiao_formula"),
    ]
    partes = [p for p in partes if p]
    if partes:
        return "\n\n---\n\n".join(partes)
    return (
        "Converta tabelas e fórmulas matemáticas de imagens em texto estruturado "
        "acessível (Markdown para tabelas, LaTeX para fórmulas)."
    )


vision_agent = Agent(
    name="VisionAgent",
    model=get_agno_model(),
    instructions=load_system_prompt("medio"),
    db=_db,
    markdown=True,
    telemetry=False,
    description="Gera audiodescrições acessíveis de imagens e páginas escaneadas.",
)

data_agent = Agent(
    name="DataAgent",
    model=get_agno_model(),
    instructions=_build_data_instructions(),
    db=_db,
    markdown=True,
    telemetry=False,
    description="Converte tabelas e fórmulas matemáticas em texto estruturado.",
)

agent_os = AgentOS(
    name="Acessilia OS",
    description="Vitrine dos agentes de acessibilidade do Acessília.",
    agents=[vision_agent, data_agent],
    telemetry=False,
)

# Objeto FastAPI exposto para o uvicorn (ex.: uvicorn agent_os:app).
app = agent_os.get_app()


if __name__ == "__main__":
    # Passar o caminho como string ("agent_os:app") habilita reload em dev.
    agent_os.serve(app="frontend.agent_os:app", host="localhost", port=7777, reload=True)
