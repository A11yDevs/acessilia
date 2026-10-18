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


class ToolboxAuthenticationError(ToolboxError):
    """Autenticação falhou — chave inválida ou ausente."""


class ToolboxUnavailable(ToolboxProviderUnavailable):
    """No Toolbox endpoint could serve the request; ``causes`` holds each failure."""

    def __init__(self, causes: list[tuple[str, ToolboxError]]) -> None:
        self.causes = causes
        details = "; ".join(f"{url}: {_describe(exc)}" for url, exc in causes)
        super().__init__(f"No Toolbox endpoint available ({details})")

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
    "ToolboxProviderUnavailable",
    "ToolboxTimeout",
    "ToolboxUnavailable",
    "ToolboxUnsupportedMediaType",
]
