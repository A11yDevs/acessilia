"""Bind the application's execution dependency for one pipeline run.

Like the CoreConfig bridge, legacy service/scripts may omit the dependency
until ADR-0016's boundary migration is complete. Explicit callers pass the
runner to PddlAccessibilityOrchestrator; core agents never read service settings.
"""

from functools import wraps

from backend.core.agents.model_calls import current_model_calls, model_call_scope


def with_model_calls(method):
    @wraps(method)
    async def execute(self, *args, **kwargs):
        runner = getattr(self, "model_calls", None)
        if runner is None:
            try:
                runner = current_model_calls()
            except RuntimeError:
                from backend.services.model_calls import get_model_calls
                runner = get_model_calls()
        with model_call_scope(runner):
            return await method(self, *args, **kwargs)
    return execute
