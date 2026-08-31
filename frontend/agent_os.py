#!/usr/bin/env python3
"""Runtime Agno que expõe os agentes do Acessília por HTTP.

Este arquivo é INDEPENDENTE do pipeline de acessibilidade (run.py). Ele apenas
expõe os agentes de IA (visão e dados) para o console local de observabilidade.

Ele NÃO executa o pipeline completo (split de PDF -> classificação de regiões ->
visão/dados -> editor). Esse fluxo continua no run.py.

Como usar:
    1. Configure o .env (mesma key de LLM do projeto: OpenRouter ou Ollama).
    2. Rode:   python -m frontend.agent_os
       O runtime sobe em http://localhost:7777
    3. Abra http://localhost:8010/agno.
"""

import os

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media import Image  # noqa: F401  (disponível para testes multimodais no painel)
from agno.os import AgentOS

from backend.observability import setup_tracing
from backend.config.settings import settings
from backend.ai.models.ai_client import get_agno_model
from backend.tools.prompt_tools import load_region_prompt, load_system_prompt

# Banco de sessões/memória do AgentOS (fica no diretório de dados do projeto).
_db = SqliteDb(db_file=str(settings.data_dir / "agentos.db"))

# A instrumentação é externa ao Agno e continua opcional pelas flags do projeto.
setup_tracing()


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


@app.middleware("http")
async def propagate_trace_context(request, call_next):
    """Mantém o trace recebido pelo proxy nos spans internos dos agentes."""
    try:
        from opentelemetry.context import attach, detach
        from opentelemetry.propagate import extract
    except ImportError:
        return await call_next(request)

    token = attach(extract(request.headers))
    try:
        return await call_next(request)
    finally:
        detach(token)


if __name__ == "__main__":
    # Passar o caminho como string ("agent_os:app") habilita reload em dev.
    host = os.getenv("AGNO_OS_HOST", "localhost")
    port = int(os.getenv("AGNO_OS_PORT", "7777"))
    reload_enabled = os.getenv("AGNO_OS_RELOAD", "false").lower() == "true"
    agent_os.serve(
        app="frontend.agent_os:app",
        host=host,
        port=port,
        reload=reload_enabled,
    )
