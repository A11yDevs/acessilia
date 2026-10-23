"""Client for ``pdf.validate.pdf_ua``: a PDF checked against PDF/UA by veraPDF.

The Toolbox runs a pinned veraPDF release in its own sidecar. A non-compliant
PDF is a successful result: the ``document`` (``artifact/pdf-validation-report@1``)
says whether the file is ``compliant`` and lists each failed rule with its
ISO 14289 clause and the first failing contexts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from acessilia_sdk.toolbox.client import ToolboxCapabilityClient
from acessilia_sdk.toolbox.errors import ToolboxContractViolation

CAPABILITY = "pdf.validate.pdf_ua"

#: Validation profiles the capability accepts: PDF/UA-1 (ISO 14289-1) and
#: PDF/UA-2 (ISO 14289-2).
PROFILES = ("ua1", "ua2")


class ToolboxPdfValidateClient(ToolboxCapabilityClient):
    """PDF/UA validation."""

    provider_key = "toolbox_pdf_validate_provider"
    timeout_key = "toolbox_pdf_validate_timeout_seconds"

    async def validate(
        self,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        profile: str = "ua1",
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """``POST /v1/capabilities/pdf.validate.pdf_ua:execute``.

        Returns the response's ``document`` (``artifact/pdf-validation-report@1``):
        ``compliant``, ``profile``, ``profile_name``, ``summary`` and ``failures``.
        """
        if profile not in PROFILES:
            raise ValueError(f"profile must be one of {list(PROFILES)}, got {profile!r}")
        result = await self._execute(
            CAPABILITY,
            file_path=file_path,
            artifact_id=artifact_id,
            parameters={"profile": profile},
            no_cache=use_remote_cache is False,
        )
        document = result.get("document")
        if not isinstance(document, dict) or not isinstance(document.get("compliant"), bool):
            raise ToolboxContractViolation(
                f"{CAPABILITY} response has no validation report in 'document'"
            )
        return document


__all__ = ["CAPABILITY", "PROFILES", "ToolboxPdfValidateClient"]
