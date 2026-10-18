"""Toolbox instances a client can reach, and the rule for failing over between them.

Availability comes primarily from stateless Toolbox replicas behind one load
balancer, never from running an operation locally. Several endpoints are for
*independent* Toolbox deployments: a client tries them in order and moves to
the next one only when the current instance could not serve the request at all
(timeout, network error, 503/504), or, for a secondary endpoint, when its
catalogue does not publish the capability as expected. Any other failure (4xx,
contract violation) is the same on every instance, so it is raised at once.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

from acessilia_sdk.toolbox.errors import (
    ToolboxError,
    ToolboxProviderUnavailable,
    ToolboxTimeout,
)

#: Failures after which the next endpoint is tried.
FAILOVER_ERRORS: tuple[type[ToolboxError], ...] = (
    ToolboxTimeout,
    ToolboxProviderUnavailable,
)


@dataclass(frozen=True)
class ToolboxEndpoint:
    """One Toolbox instance: its base URL and, optionally, its own API key.

    Without an ``api_key`` the endpoint uses the client's key.
    """

    base_url: str
    api_key: str | None = None

    def __post_init__(self) -> None:
        normalized = self.base_url.strip().rstrip("/")
        if not normalized:
            raise ValueError("Toolbox endpoint needs a non-empty base_url")
        # A typo here would otherwise surface as a network error and be taken
        # for an outage, consuming the failover.
        parts = urlsplit(normalized)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError(
                f"Toolbox base_url must be an absolute http(s) URL, got {self.base_url!r}"
            )
        object.__setattr__(self, "base_url", normalized)


def parse_endpoints(
    base_urls: str | Sequence[str], *, api_key: str | None = None
) -> tuple[ToolboxEndpoint, ...]:
    """Endpoints from a comma-separated string or a sequence of URLs.

    Blank entries are skipped; at least one URL is required.
    """
    raw = base_urls.split(",") if isinstance(base_urls, str) else base_urls
    endpoints = tuple(
        ToolboxEndpoint(url, api_key) for url in raw if url and url.strip()
    )
    if not endpoints:
        raise ValueError("At least one Toolbox base URL is required")
    return endpoints


__all__ = ["FAILOVER_ERRORS", "ToolboxEndpoint", "parse_endpoints"]
