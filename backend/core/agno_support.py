from __future__ import annotations

from importlib.util import find_spec
from typing import Any, Callable, Sequence

from backend.i18n import t
from backend.log_messages import LOG_AGNO_NOT_INSTALLED


def agno_available() -> bool:
    """Report whether the optional Agno AI-agent stack can be imported.

    Returns:
        bool: True when a package findable as the ``agno`` top-level module exists in the environment, False otherwise; callers use this to skip the deterministic no-LLM path.
    """
    return find_spec("agno") is not None


def build_agent(
    *,
    name: str,
    instructions: Sequence[str],
    tools: Sequence[Callable[..., Any]],
    model: Any | None = None,
) -> Any | None:
    """Build an Agno agent without forcing an LLM call in the deterministic path.

    Args:
        name (str): Display name assigned to the created agent.
        instructions (Sequence[str]): Static instruction lines the agent is told to follow.
        tools (Sequence[Callable[..., Any]]): Callable tools bundled into an Agno toolkit for the agent.
        model (Any | None): Optional preconfigured Agno model instance; when None the agent is constructed without an explicit model. Defaults to None.

    Returns:
        Any | None: The configured Agno agent instance, or None when the Agno stack is not installed so the deterministic path can proceed instead.
    """
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
    """Import and return the Agno workflow classes, raising a localized error when Agno is missing.

    Returns:
        tuple[Any, Any, Any, Any]: The Agno ``Workflow``, ``Step``, ``StepInput`` and ``StepOutput`` classes in that order.

    Raises:
        RuntimeError: When the Agno package cannot be imported, carrying the localized "Agno is not installed" message resolved through ``backend.i18n.t()`` for the active locale.
    """
    if not agno_available():
        raise RuntimeError(t(LOG_AGNO_NOT_INSTALLED))
    from agno.workflow import Step, StepInput, StepOutput, Workflow

    return Workflow, Step, StepInput, StepOutput
