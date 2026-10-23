"""Helpers for reading the result of an Agno agent run."""

from __future__ import annotations

from typing import Any


class AgentRunError(RuntimeError):
    """An Agno run that ended in error (provider unreachable, rejected key, ...)."""


class RunIncompleteError(RuntimeError):
    """An Agno run that ended without completing (provider error, cancellation...).

    Carries the run's status and content so callers can classify the failure —
    a rate-limit rejection reads differently from a timeout — without parsing
    arbitrary model output.
    """

    def __init__(self, status: object, content: object) -> None:
        super().__init__(f"Agent run did not complete ({status}): {content}")
        self.status = status
        self.content = content


def run_content(output: Any) -> Any:
    """Content of an Agno run, raising when the run itself failed.

    Agno does not raise on provider errors: the run ends with
    ``status=RunStatus.error`` and the error message as ``content``. Read as
    content, "Invalid API Key" would only surface later as a JSON validation
    error, hiding the cause.
    """
    status = getattr(output, "status", None)
    # Compare by the uppercased value so both RunStatus and plain strings
    # ("error") work, without importing agno here (fakes rely on that).
    if str(getattr(status, "value", status) or "").upper() == "ERROR":
        detail = getattr(output, "content", "") or "no error message"
        raise AgentRunError(f"model run failed: {detail}")
    return getattr(output, "content", output)
