"""Exceptions raised by the Toolbox clients."""

from __future__ import annotations


class ToolboxError(Exception):
    """Erro base para falhas de comunicação com a Acessilia Toolbox."""


class ToolboxProviderUnavailable(ToolboxError):
    """Provedor da Toolbox está offline ou não respondeu."""


class ToolboxTimeout(ToolboxError):
    """A requisição excedeu o timeout configurado."""


class ToolboxUnsupportedMediaType(ToolboxError):
    """Tipo de mídia não suportado pela capacidade solicitada."""


class ToolboxArtifactNotFound(ToolboxError):
    """Artefato requisitado não foi encontrado na Toolbox."""


class ToolboxContractViolation(ToolboxError):
    """Resposta da Toolbox violou o contrato esperado."""


class ToolboxCapabilityError(ToolboxError):
    """Capacidade inválida ou não disponível na Toolbox."""


class ToolboxInvalidInput(ToolboxCapabilityError):
    """The Toolbox rejected the input itself (HTTP 400, code ``invalid_input``).

    For example LaTeX that ``math.convert`` cannot parse: the request reached a
    working provider, so retrying or failing over will not help.
    """


class ToolboxAuthenticationError(ToolboxError):
    """Autenticação falhou — chave inválida ou ausente."""


class ToolboxUnavailable(ToolboxProviderUnavailable):
    """No Toolbox provider completed the request; ``causes`` holds each failure.

    When at least one cause is not exclusively a timeout or an unavailable
    instance -- for example a :class:`ToolboxContractViolation`, the bare
    :class:`ToolboxError` of an unmapped HTTP 500, or a capability/catalog
    rejection -- the message says that no provider completed the request
    instead of claiming unavailability. This does not assert that the provider
    executed the requested capability; the typed causes keep that distinction.
    Causes that are only a :class:`ToolboxTimeout` or a
    :class:`ToolboxProviderUnavailable` keep the unavailability wording (#700).
    """

    def __init__(self, causes: list[tuple[str, ToolboxError]]) -> None:
        self.causes = causes
        details = "; ".join(f"{url}: {_describe(exc)}" for url, exc in causes)
        has_non_availability_failure = any(
            not isinstance(exc, (ToolboxTimeout, ToolboxProviderUnavailable))
            for _, exc in causes
        )
        prefix = (
            "No Toolbox provider completed the request"
            if has_non_availability_failure
            else "No Toolbox endpoint available"
        )
        super().__init__(f"{prefix} ({details})")

    def __reduce__(self):
        # ``args`` holds the formatted message; rebuild from ``causes`` so the
        # error survives pickling (process pools, multiprocessing queues).
        return (type(self), (self.causes,))


class ToolboxIncompatibleEndpoint(ToolboxCapabilityError):
    """A secondary endpoint does not publish the capability as the SDK expects."""


def _describe(exc: ToolboxError) -> str:
    return f"{type(exc).__name__}: {exc}"


__all__ = [
    "ToolboxArtifactNotFound",
    "ToolboxAuthenticationError",
    "ToolboxCapabilityError",
    "ToolboxContractViolation",
    "ToolboxError",
    "ToolboxIncompatibleEndpoint",
    "ToolboxInvalidInput",
    "ToolboxProviderUnavailable",
    "ToolboxTimeout",
    "ToolboxUnavailable",
    "ToolboxUnsupportedMediaType",
]
