#!/usr/bin/env python3
"""AgentOS - Showcase of the Acessilia agents in the Agno panel (os.agno.com).

This file is INDEPENDENT of the accessibility pipeline (run.py). It only exposes
the AI agents (vision and data) as live instances so that you can converse with
them through the AgentOS panel and monitor sessions, memory, and traces.

It does NOT execute the complete pipeline (PDF split -> region classification ->
vision/data -> editor). That flow remains in run.py.

How to use:
    1. Configure the .env (same LLM key as the project: OpenRouter or Ollama).
    2. Run:   python agent_os.py
        The runtime starts on http://localhost:7777
    3. Open https://os.agno.com, sign in, click "Add new OS",
        choose Environment: Local, Endpoint URL: http://localhost:7777,
        give it a name, and click CONNECT.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media import Image  # noqa: F401  (available for multimodal tests in the panel)
from agno.os import AgentOS

from backend.ai.models.ai_client import get_agno_model
from backend.config.settings import settings
from backend.i18n import t
from backend.tools.prompt_tools import load_region_prompt, load_system_prompt
from frontend.web.messages import (
    WEB_AGENT_DATA_DESCRIPTION,
    WEB_AGENT_DATA_INSTRUCTIONS_FALLBACK,
    WEB_AGENT_OS_DESCRIPTION,
    WEB_AGENT_VISION_DESCRIPTION,
)

# Session/memory database of the AgentOS (kept in the project data directory).
_db_file = settings.data_dir / "agentos.db"
_db = SqliteDb(db_file=str(_db_file))
if _db_file.exists():
    try:
        from agno.db.migrations.manager import MigrationManager

        MigrationManager(_db).up()
    except Exception:
        pass


def _build_data_instructions() -> str:
    """Build the data-agent instructions from the table/formula region prompts.

    Returns:
        str: The joined table and formula region prompts, or the localized
        fallback instruction string when no region prompts are configured.
    """
    parts = [
        load_region_prompt("regiao_tabela"),
        load_region_prompt("regiao_formula"),
    ]
    parts = [p for p in parts if p]
    if parts:
        return "\n\n---\n\n".join(parts)
    return t(WEB_AGENT_DATA_INSTRUCTIONS_FALLBACK)


vision_agent = Agent(
    name="VisionAgent",
    model=get_agno_model(),
    instructions=load_system_prompt("medio"),
    db=_db,
    markdown=True,
    telemetry=False,
    description=t(WEB_AGENT_VISION_DESCRIPTION),
)

data_agent = Agent(
    name="DataAgent",
    model=get_agno_model(),
    instructions=_build_data_instructions(),
    db=_db,
    markdown=True,
    telemetry=False,
    description=t(WEB_AGENT_DATA_DESCRIPTION),
)

agent_os = AgentOS(
    name="Acessilia OS",
    description=t(WEB_AGENT_OS_DESCRIPTION),
    agents=[vision_agent, data_agent],
    telemetry=False,
)

# FastAPI object exposed for uvicorn (e.g., uvicorn agent_os:app).
app = agent_os.get_app()


if __name__ == "__main__":
    # Passing the path as a string ("agent_os:app") enables dev reload.
    agent_os.serve(app="frontend.agent_os:app", host="localhost", port=7777, reload=True)
