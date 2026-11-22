"""Per-task locale context shared by Acessilia components.

The SDK owns the context variable and its set/reset contract. The caller keeps
the policy: the core composes the request override with its server-side locale.
"""

from __future__ import annotations

import contextvars

__all__ = ["request_locale", "reset_request_locale", "set_request_locale"]

#: Per-task override for the locale that translation lookups resolve against.
#: Remote-user handlers set this before emitting user-facing text so that,
#: within a single asyncio task (and its child tasks), every lookup honours
#: that user's detected locale.
_REQUEST_LOCALE_VAR: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "acessilia_request_locale", default=None
)


def set_request_locale(locale: str) -> contextvars.Token:
    """Override the lookup locale for the current task and its child tasks.

    Args:
        locale (str): Locale identifier to force for the current task.

    Returns:
        contextvars.Token: Reset token returned by ``ContextVar.set``; pass it
        to :func:`reset_request_locale` when the override must end before the
        task does.
    """
    return _REQUEST_LOCALE_VAR.set(locale)


def reset_request_locale(token: contextvars.Token) -> None:
    """Restore the previously active per-task locale override.

    Args:
        token (contextvars.Token): Token captured by an earlier
            :func:`set_request_locale` call in the same task.
    """
    _REQUEST_LOCALE_VAR.reset(token)


def request_locale() -> str | None:
    """The per-task override, or ``None`` when the task has not set one."""
    return _REQUEST_LOCALE_VAR.get()
