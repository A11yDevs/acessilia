"""Cancel one running Toolbox operation (ADR-0019)."""

from __future__ import annotations

import asyncio
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
    stopped computing.  ``not_found`` means every configured endpoint answered
    that it does not know the operation, which can happen after a restart or
    when the id was never registered.  ``failed`` means at least one endpoint
    did not answer conclusively, so the operation may still be running there.
    """

    operation_id: str
    state: str
    cancel_requested: bool
    endpoint: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class _EndpointOutcome:
    """What one endpoint answered, or why it answered nothing conclusive."""

    endpoint: str
    state: str
    cancel_requested: bool = False
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
        """Ask *every* configured endpoint to cancel ``operation_id``.

        A failover may have left the same logical operation running on another
        deployment, and the endpoints share no operation registry, so stopping
        at the first endpoint that answers would report ``finished`` while a
        copy keeps computing elsewhere.  Every endpoint is therefore asked,
        concurrently and within one short wall-clock budget; the answers are
        aggregated before returning.

        Cancellation is idempotent, so repeating the request on several
        endpoints is safe.  A 404 is not a failure, but only an answer: the
        aggregate is ``not_found`` when *every* endpoint answered 404.  An
        attempt without a conclusive answer (timeout, 5xx, malformed response)
        makes the aggregate ``failed``, because that endpoint may be the one
        still running the operation.  Network and HTTP failures are returned,
        never raised, because a cancellation failure must not turn a user
        cancel into a job error.
        """
        if not operation_id or not task_id:
            raise ValueError("operation_id and task_id are required")
        path = f"/v1/operations/{quote(operation_id, safe='')}:cancel"
        if timeout_seconds <= 0:
            return _aggregate(
                operation_id,
                [
                    _EndpointOutcome(
                        endpoint.base_url,
                        "failed",
                        error="cancel budget exhausted before this endpoint",
                    )
                    for endpoint in self.endpoints
                ],
            )
        answers = await asyncio.gather(
            *(
                self._cancel_on(
                    http, endpoint.base_url, path, task_id, timeout_seconds
                )
                for endpoint, http in zip(self.endpoints, self._clients)
            ),
            return_exceptions=True,
        )
        outcomes = [
            answer
            if isinstance(answer, _EndpointOutcome)
            else _EndpointOutcome(
                endpoint.base_url,
                "failed",
                error=f"{type(answer).__name__}: {answer}",
            )
            for endpoint, answer in zip(self.endpoints, answers)
        ]
        return _aggregate(operation_id, outcomes)

    async def _cancel_on(
        self,
        http: httpx.AsyncClient,
        base_url: str,
        path: str,
        task_id: str,
        timeout_seconds: float,
    ) -> _EndpointOutcome:
        """Cancel on one endpoint, mapping every failure to an outcome."""
        try:
            response = await http.post(
                path,
                headers={TASK_ID_HEADER: task_id},
                timeout=httpx.Timeout(timeout_seconds),
            )
        except httpx.TimeoutException as exc:
            return _EndpointOutcome(base_url, "failed", error=f"timeout: {exc}")
        except httpx.RequestError as exc:
            return _EndpointOutcome(base_url, "failed", error=f"unavailable: {exc}")

        if response.status_code == 404:
            return _EndpointOutcome(base_url, "not_found")
        try:
            raise_for_error(response, "operations.cancel")
        except ToolboxError as exc:
            return _EndpointOutcome(
                base_url, "failed", error=f"{type(exc).__name__}: {exc}"
            )
        try:
            payload = response.json()
        except ValueError:
            return _EndpointOutcome(base_url, "failed", error="response is not valid JSON")
        state = str(payload.get("state", "")) if isinstance(payload, dict) else ""
        if state not in _TERMINAL_STATES:
            return _EndpointOutcome(
                base_url, "failed", error=f"unknown cancellation state: {state!r}"
            )
        return _EndpointOutcome(
            base_url,
            state,
            cancel_requested=bool(payload.get("cancel_requested", False)),
        )


def _aggregate(
    operation_id: str, outcomes: list[_EndpointOutcome]
) -> OperationCancelResult:
    """Collapse the per-endpoint answers into the result the caller records.

    An inconclusive answer dominates: it may come from the deployment that is
    still running the operation, so neither ``finished`` nor ``not_found`` may
    hide it.  An acknowledged cancel is reported next, then a confirmed
    cancellation, then a finished operation, and ``not_found`` only when every
    endpoint answered 404.
    """
    failed = [outcome for outcome in outcomes if outcome.state == "failed"]
    acknowledged = any(outcome.cancel_requested for outcome in outcomes)
    if failed:
        return OperationCancelResult(
            operation_id=operation_id,
            state="failed",
            cancel_requested=acknowledged,
            endpoint=failed[0].endpoint,
            error="; ".join(
                f"{outcome.endpoint}: {outcome.error}" for outcome in failed
            ),
        )
    for state in ("cancel_requested", "cancelled", "finished"):
        matching = [outcome for outcome in outcomes if outcome.state == state]
        if matching:
            return OperationCancelResult(
                operation_id=operation_id,
                state=state,
                cancel_requested=acknowledged or state == "cancelled",
                endpoint=matching[0].endpoint,
            )
    return OperationCancelResult(
        operation_id=operation_id,
        state="not_found",
        cancel_requested=False,
    )


__all__ = ["OperationCancelResult", "ToolboxOperationClient"]
