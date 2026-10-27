"""Fixtures shared by the core test suite."""

from urllib.parse import urlsplit

import pytest

# Pages and regions are rendered by the Toolbox (pdf.render@2); this fixture
# answers those requests with real pixels behind mocked HTTP.
from tests.toolbox_render_fake import fake_toolbox_render  # noqa: F401


@pytest.fixture(autouse=True)
def _vision_cache_stays_out_of_tests(monkeypatch):
    """Keep region-description cache hits out of the test suite.

    The cache is keyed on the image bytes, and several tests script identical
    inputs with different answers; a shared cache directory would leak one
    test's answer into another. Tests that exercise the cache re-enable it and
    point ``backend.services.cache.CACHE_DIR`` at their own ``tmp_path``.
    """
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "vision_region_cache_enabled", False)


@pytest.fixture(autouse=True)
def _vision_retry_pass_without_wait(monkeypatch):
    """Run the vision retry pass without its wait, so a failing test stays fast."""
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "vision_retry_pass_delay_seconds", 0)


@pytest.fixture(autouse=True)
def _renders_stay_off_a_real_toolbox(request, monkeypatch):
    """Fail a non-e2e test that renders or validates against a real Toolbox.

    Without this, a test that renders and forgets ``fake_toolbox_render``, or
    a worker test whose PDF/UA reaches the veraPDF audit, would call the
    ``TOOLBOX_BASE_URL`` of ``.env``/settings in silence. Mocked endpoints use
    the reserved ``.test`` domain (RFC 2606), as the fake does; ``e2e`` tests
    are the ones meant to reach a real Toolbox.
    """
    if request.node.get_closest_marker("e2e"):
        return
    from acessilia_sdk.toolbox.clients.pdf import ToolboxPdfClient
    from acessilia_sdk.toolbox.clients.pdf_validate import ToolboxPdfValidateClient

    def guard(client_cls, method, capability, hint):
        original = getattr(client_cls, method)

        async def guarded(self, *args, **kwargs):
            real = [
                endpoint.base_url
                for endpoint in self.endpoints
                if not (urlsplit(endpoint.base_url).hostname or "").endswith(".test")
            ]
            if real:
                # pytest.fail raises a BaseException, so the handlers' own
                # ``except Exception`` cannot turn it into a method failure.
                pytest.fail(f"{capability} sent to {real[0]}: {hint}", pytrace=False)
            return await original(self, *args, **kwargs)

        monkeypatch.setattr(client_cls, method, guarded)

    guard(
        ToolboxPdfClient, "render", "pdf.render",
        "request the fake_toolbox_render fixture (or mock a *.test Toolbox)",
    )
    guard(
        ToolboxPdfValidateClient, "validate", "pdf.validate.pdf_ua",
        "patch backend.api.worker.audit_pdf_ua (or mock a *.test Toolbox)",
    )


#: A veraPDF report for a PDF/UA that meets every rule.
COMPLIANT_PDF_UA_REPORT = {
    "compliant": True,
    "profile": "ua1",
    "profile_name": "PDF/UA-1 validation profile",
    "statement": "PDF file is compliant with Validation Profile requirements.",
    "summary": {"passed_rules": 106, "failed_rules": 0, "passed_checks": 37, "failed_checks": 0},
    "failures": [],
}


@pytest.fixture
def fake_pdf_ua_audit(monkeypatch):
    """The worker's veraPDF audit, answered with a compliant report; returns the audited paths."""
    audited = []

    async def audit(pdf_path, **_kwargs):
        audited.append(pdf_path)
        return COMPLIANT_PDF_UA_REPORT

    monkeypatch.setattr("backend.api.worker.audit_pdf_ua", audit)
    return audited
