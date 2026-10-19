"""Fixtures shared by the core test suite."""

from urllib.parse import urlsplit

import pytest

# Pages and regions are rendered by the Toolbox (pdf.render@2); this fixture
# answers those requests with real pixels behind mocked HTTP.
from tests.toolbox_render_fake import fake_toolbox_render  # noqa: F401


@pytest.fixture(autouse=True)
def _renders_stay_off_a_real_toolbox(request, monkeypatch):
    """Fail a non-e2e test that renders against a Toolbox that is not a test double.

    Without this, a test that renders and forgets ``fake_toolbox_render`` would
    call the ``TOOLBOX_BASE_URL`` of ``.env``/settings in silence. Mocked
    endpoints use the reserved ``.test`` domain (RFC 2606), as the fake does;
    ``e2e`` tests are the ones meant to reach a real Toolbox.
    """
    if request.node.get_closest_marker("e2e"):
        return
    from acessilia_sdk.toolbox.clients.pdf import ToolboxPdfClient

    render = ToolboxPdfClient.render

    async def guarded(self, *args, **kwargs):
        real = [
            endpoint.base_url
            for endpoint in self.endpoints
            if not (urlsplit(endpoint.base_url).hostname or "").endswith(".test")
        ]
        if real:
            # pytest.fail raises a BaseException, so the handlers' own
            # ``except Exception`` cannot turn it into a method failure.
            pytest.fail(
                f"pdf.render sent to {real[0]}: request the fake_toolbox_render "
                "fixture (or mock a *.test Toolbox)",
                pytrace=False,
            )
        return await render(self, *args, **kwargs)

    monkeypatch.setattr(ToolboxPdfClient, "render", guarded)
