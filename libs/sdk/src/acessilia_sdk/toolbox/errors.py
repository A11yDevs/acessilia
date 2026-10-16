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


__all__ = [
    "ToolboxArtifactNotFound",
    "ToolboxAuthenticationError",
    "ToolboxCapabilityError",
    "ToolboxContractViolation",
    "ToolboxError",
    "ToolboxProviderUnavailable",
    "ToolboxTimeout",
    "ToolboxUnsupportedMediaType",
]
