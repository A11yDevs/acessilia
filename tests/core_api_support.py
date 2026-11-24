"""Helpers shared by the end-to-end tests against a deployed Core API.

``CORE_BASE_URL`` turns the deployed-core suites on. ``CORE_JOB_TIMEOUT``
(seconds, default 600) bounds each processing wait; a test that legitimately
needs longer passes its own timeout to :func:`poll` and marks itself with a
larger ``pytest.mark.timeout``.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator

import httpx
import pytest

CORE_BASE_URL = os.getenv("CORE_BASE_URL", "").strip().rstrip("/")
JOB_TIMEOUT = float(os.getenv("CORE_JOB_TIMEOUT", "600"))


def require_core() -> str:
    """The configured core URL, or a skip when the suite is not enabled."""
    if not CORE_BASE_URL:
        pytest.skip("CORE_BASE_URL not configured")
    return CORE_BASE_URL


@pytest.fixture(scope="module")
def core_client() -> Iterator[httpx.Client]:
    """A client for the configured core; an unhealthy one is a failure.

    ``CORE_BASE_URL`` is the switch that turns the deployed-core suites on, so
    only its absence skips. Once an environment is configured, a connection
    error or an unhealthy ``/health`` is exactly what these tests exist to
    report.
    """
    base = require_core()
    with httpx.Client(base_url=base, timeout=60.0) as http:
        try:
            response = http.get("/health")
        except httpx.HTTPError as exc:
            pytest.fail(f"Core API is not reachable at {base}: {exc!r}")
        assert response.status_code == 200, (
            f"Core API health returned {response.status_code} at {base}: {response.text}"
        )
        yield http


def upload(
    client: httpx.Client,
    content: bytes,
    filename: str,
    *,
    media_type: str = "application/octet-stream",
    data: dict[str, str] | None = None,
) -> httpx.Response:
    """Upload, waiting out the API's per-IP upload rate limit.

    ``POST /jobs`` allows five requests a minute. A clean run of
    ``test_core_api_e2e`` makes four; a developer running it twice in a row, or
    another client on the same address, can exhaust the window. Waiting for the
    documented window keeps the suites from reporting a false product failure.
    """
    response: httpx.Response | None = None
    for attempt in range(3):
        response = client.post(
            "/jobs",
            files={"document_file": (filename, content, media_type)},
            data=data or {"email": ""},
        )
        if response.status_code != 429 or attempt == 2:
            return response
        retry_after = response.headers.get("Retry-After", "")
        delay = int(retry_after) if retry_after.isdigit() else 61
        time.sleep(min(max(delay, 1), 90))
    assert response is not None
    return response


def cancel_job(client: httpx.Client, task_id: str, token: str) -> None:
    """Best-effort cancellation of a job the suite stopped waiting for.

    A ``202`` already put real work on the server, and a stuck extraction can
    hold the only worker slot (#339). The request is short and never replaces
    the error that ended the wait; the suite does not wait for ``cancelled``.
    """
    try:
        client.post(
            f"/jobs/{task_id}/cancel",
            headers={"X-Job-Token": token},
            timeout=10.0,
        )
    except httpx.HTTPError:
        pass


def poll(
    client: httpx.Client,
    task_id: str,
    token: str,
    *,
    timeout: float | None = None,
) -> dict:
    """Wait for a terminal job state; cancel it if the wait does not end.

    A deadline, a failed status request or an interrupted test all leave the
    job running on the server, so the cleanup runs for every exit that did not
    observe a terminal state.
    """
    limit = JOB_TIMEOUT if timeout is None else timeout
    headers = {"X-Job-Token": token}
    deadline = time.monotonic() + limit
    last: dict = {}
    terminal = False
    try:
        while time.monotonic() < deadline:
            response = client.get(f"/jobs/{task_id}", headers=headers)
            assert response.status_code == 200, response.text
            last = response.json()
            if last.get("status") in {"done", "error", "cancelled"}:
                terminal = True
                return last
            time.sleep(2)
        pytest.fail(f"Job {task_id} did not finish in {limit:.0f}s: {last}")
    finally:
        if not terminal:
            cancel_job(client, task_id, token)


def download_token(status: dict) -> str:
    """The token in a finished job's ``download_url``."""
    url = status.get("download_url") or ""
    assert url, f"finished job has no download_url: {status}"
    return url.rsplit("/download/", 1)[-1]
