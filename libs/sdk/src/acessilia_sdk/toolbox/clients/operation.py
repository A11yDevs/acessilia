"""Cancel one running Toolbox operation (ADR-0019)."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

import httpx

from acessilia_sdk.toolbox.client import ToolboxCapabilityClient
from acessilia_sdk.toolbox.errors import ToolboxError
from acessilia_sdk.toolbox.operation import TASK_ID_HEADER
from acessilia_sdk.toolbox.transport import raise_for_error

_TERMINAL_STATES = {"cancel_requested", "cancelled", "finished", "failed"}


@dataclass(frozen=True)
class OperationCancelResult:
    """Outcome of a bounded cancel request.

    ``cancel_requested`` is an acknowledgment, not proof that a provider
    stopped computing.  ``not_found`` means this replica (or every configured
    endpoint) does not know the operation, which can happen after a restart or
    when a load balancer routes to another replica.
    """

    operation_id: str
    state: str
    cancel_requested: bool
    endpoint: str | None = None
    error: str | None = None


class ToolboxOperationClient(ToolboxCapabilityClient):
    """Request cancellation of an operation without retrying indefinitely."""

    async def cancel(
        self,
        operation_id: str,
        *,
        task_id: str,
        timeout_seconds: float = 2.0,
    ) -> OperationCancelResult:
        """Ask each endpoint to cancel ``operation_id`` for ``task_id``.

        Cancellation is idempotent, so trying independent endpoints is safe;
        the first endpoint that knows the operation answers.  A 404 is not a
        failure of the request, but the final answer if no endpoint knows it.
        Network and HTTP failures are returned, never raised, because a
        cancellation failure must not turn a user cancel into a job error.
        """
        if not operation_id or not task_id:
            raise ValueError("operation_id and task_id are required")
        path = f"/v1/operations/{quote(operation_id, safe='')}:cancel"
        last_endpoint: str | None = None
        last_error: str | None = None
        last_state = "not_found"
        for endpoint, http in zip(self.endpoints, self._clients):
            last_endpoint = endpoint.base_url
            try:
                response = await http.post(
                    path,
                    headers={TASK_ID_HEADER: task_id},
                    timeout=httpx.Timeout(timeout_seconds),
                )
            except httpx.TimeoutException as exc:
                last_error = f"timeout: {exc}"
                last_state = "failed"
                continue
            except httpx.RequestError as exc:
                last_error = f"unavailable: {exc}"
                last_state = "failed"
                continue

            if response.status_code == 404:
                last_state = "not_found"
                continue
            try:
                raise_for_error(response, "operations.cancel")
            except ToolboxError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                last_state = "failed"
                continue
            try:
                payload = response.json()
            except ValueError:
                last_error = "response is not valid JSON"
                last_state = "failed"
                continue
            state = str(payload.get("state", "")) if isinstance(payload, dict) else ""
            if state not in _TERMINAL_STATES:
                last_error = f"unknown cancellation state: {state!r}"
                last_state = "failed"
                continue
            return OperationCancelResult(
                operation_id=operation_id,
                state=state,
                cancel_requested=bool(payload.get("cancel_requested", False)),
                endpoint=endpoint.base_url,
            )
        return OperationCancelResult(
            operation_id=operation_id,
            state=last_state,
            cancel_requested=False,
            endpoint=last_endpoint,
            error=last_error,
        )


__all__ = ["OperationCancelResult", "ToolboxOperationClient"]
