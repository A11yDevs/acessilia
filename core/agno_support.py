from __future__ import annotations

from importlib.util import find_spec
from typing import Any, Callable, Sequence


def agno_available() -> bool:
    return find_spec("agno") is not None


def build_agent(
    *,
    name: str,
    instructions: Sequence[str],
    tools: Sequence[Callable[..., Any]],
    model: Any | None = None,
) -> Any | None:
    """Cria um Agent Agno sem obrigar uma chamada a LLM no caminho determinístico."""
    if not agno_available():
        return None
    from agno.agent import Agent
    from agno.tools import Toolkit

    toolkit = Toolkit(name=f"{name.lower().replace(' ', '-')}-tools", tools=tools)
    options: dict[str, Any] = {
        "name": name,
        "instructions": list(instructions),
        "tools": [toolkit],
        "markdown": False,
        "telemetry": False,
    }
    if model is not None:
        options["model"] = model
    return Agent(
        **options,
    )


def require_workflow_classes() -> tuple[Any, Any, Any, Any]:
    if not agno_available():
        raise RuntimeError(
            "Agno não está instalado. Execute `poetry install` antes de usar "
            "o workflow Executor."
        )
    from agno.workflow import Step, StepInput, StepOutput, Workflow

    return Workflow, Step, StepInput, StepOutput
