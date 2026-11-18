"""Set the server-side locale in a test, as the service's process setup does.

The core reads no environment (ADR-0016, step 5), so a test no longer sets
``LOCALE`` in the environment: it configures the server locale directly.
"""

from __future__ import annotations

import pytest


def use_server_locale(monkeypatch: pytest.MonkeyPatch, locale: str | None) -> None:
    """Make ``locale`` the server-side locale for this test (``None``: not configured)."""
    from acessilia_core import i18n

    monkeypatch.setattr(i18n, "_SERVER_LOCALE", locale)
