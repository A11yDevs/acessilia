"""PDF/UA audit of the exported PDF through the Toolbox ``pdf.validate.pdf_ua``.

veraPDF runs only on the Toolbox (docs/adr/0003): there is no local fallback.
With ``TOOLBOX_PDF_VALIDATE_ENABLED=false`` the audit is skipped, and a Toolbox
failure propagates so the caller decides how to report it. The summary is what
the result e-mail shows; the full report is packaged with the files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.i18n import t
from backend.log_messages import (
    EMAIL_AUDIT_COMPLIANT,
    EMAIL_AUDIT_MORE_RULES,
    EMAIL_AUDIT_NON_COMPLIANT,
    EMAIL_AUDIT_RULE,
    LOG_PDF_UA_AUDIT_FINISHED,
    LOG_PDF_UA_AUDIT_SKIPPED_DISABLED,
)
from backend.tools.logger import logger

#: Validation profile the exported PDF is audited against.
AUDIT_PROFILE = "ua1"

#: How the e-mail names each validation profile.
PROFILE_LABELS = {"ua1": "PDF/UA-1", "ua2": "PDF/UA-2"}


async def audit_pdf_ua(pdf_path: Path, *, client: Any | None = None) -> dict[str, Any] | None:
    """Validates ``pdf_path`` against PDF/UA-1 with veraPDF on the Toolbox.

    Args:
        pdf_path (Path): The exported PDF/UA.
        client (ToolboxPdfValidateClient | None): Optional client to reuse; when None one is created and closed here.

    Returns:
        dict | None: The ``artifact/pdf-validation-report@1`` document, or None when TOOLBOX_PDF_VALIDATE_ENABLED is false.

    Raises:
        acessilia_sdk.toolbox.errors.ToolboxError: When the Toolbox cannot validate the file.
    """
    from backend.config.settings import settings

    if not settings.toolbox_pdf_validate_enabled:
        logger.info(t(LOG_PDF_UA_AUDIT_SKIPPED_DISABLED))
        return None

    from acessilia_sdk.toolbox.clients import ToolboxPdfValidateClient

    from backend.tools.toolbox_client import make_toolbox_client

    owned_client = client is None
    validate_client = client or make_toolbox_client(ToolboxPdfValidateClient)
    try:
        report = await validate_client.validate(
            file_path=pdf_path,
            profile=AUDIT_PROFILE,
            use_remote_cache=settings.toolbox_use_remote_cache,
        )
    finally:
        if owned_client:
            await validate_client.close()
    logger.info(
        t(LOG_PDF_UA_AUDIT_FINISHED).format(
            compliant=report["compliant"],
            rules=len(report.get("failures") or []),
        )
    )
    return report


def summarize_audit(report: dict[str, Any], *, max_rules: int) -> list[str]:
    """The e-mail lines for a validation report: the verdict, then failed rules.

    Rules are listed by failing objects, most first, up to ``max_rules``; a
    final line counts the rest, which the packaged report carries. Rule
    descriptions are veraPDF's, in English.
    """
    profile = PROFILE_LABELS.get(str(report.get("profile")), str(report.get("profile") or ""))
    failures = sorted(
        report.get("failures") or [],
        key=lambda rule: -int(rule.get("failed_checks") or 0),
    )
    if report.get("compliant"):
        return [t(EMAIL_AUDIT_COMPLIANT).format(profile=profile)]
    lines = [
        t(EMAIL_AUDIT_NON_COMPLIANT).format(
            profile=profile,
            rules=len(failures),
            checks=sum(int(rule.get("failed_checks") or 0) for rule in failures),
        )
    ]
    lines.extend(
        t(EMAIL_AUDIT_RULE).format(
            specification=rule.get("specification", ""),
            clause=rule.get("clause", ""),
            test=rule.get("test_number", ""),
            description=" ".join(str(rule.get("description", "")).split()),
            checks=int(rule.get("failed_checks") or 0),
        )
        for rule in failures[: max(max_rules, 0)]
    )
    if len(failures) > max_rules:
        lines.append(t(EMAIL_AUDIT_MORE_RULES).format(count=len(failures) - max_rules))
    return lines
