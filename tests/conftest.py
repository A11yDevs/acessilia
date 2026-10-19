"""Fixtures shared by the core test suite."""

# Pages and regions are rendered by the Toolbox (pdf.render@2); this fixture
# answers those requests with real pixels behind mocked HTTP.
from tests.toolbox_render_fake import fake_toolbox_render  # noqa: F401
