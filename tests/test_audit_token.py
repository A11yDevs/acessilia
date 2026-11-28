"""The audit token is a separate privilege from operations and observability."""

from __future__ import annotations

import pytest

from backend.config.settings import Settings


def test_audit_and_operations_tokens_must_differ() -> None:
    with pytest.raises(ValueError, match="AUDIT_API_TOKEN"):
        Settings(audit_api_token="same", operations_api_token="same")


def test_audit_and_observability_tokens_must_differ() -> None:
    with pytest.raises(ValueError, match="AUDIT_API_TOKEN"):
        Settings(audit_api_token="same", observability_api_token="same")


def test_distinct_privileged_tokens_are_accepted() -> None:
    configured = Settings(
        audit_api_token="audit",
        operations_api_token="operations",
        observability_api_token="observability",
    )

    assert configured.audit_api_token == "audit"
