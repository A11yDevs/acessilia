"""Image recovery uses the rendering contract, including raster inputs."""

from io import BytesIO

import pytest
from PIL import Image

from backend.tools.vision_payload import downscale_image


@pytest.mark.asyncio
@pytest.mark.parametrize("format_name", ["PNG", "JPEG"])
async def test_context_recovery_resizes_raster_images_on_the_toolbox(format_name, fake_toolbox_render):
    source = BytesIO()
    Image.new("RGB", (400, 240), "white").save(source, format=format_name)

    result = await downscale_image(source.getvalue())

    with Image.open(BytesIO(result)) as image:
        assert image.size == (200, 120)
    assert fake_toolbox_render.parameters == [{"page_number": 1, "dpi": 150, "max_side": 200}]


@pytest.mark.asyncio
async def test_invalid_or_unshrinkable_images_do_not_call_the_toolbox(fake_toolbox_render):
    source = BytesIO()
    Image.new("RGB", (1, 1), "white").save(source, format="PNG")

    assert await downscale_image(b"not an image") is None
    assert await downscale_image(source.getvalue()) is None
    assert fake_toolbox_render.requests == []


@pytest.mark.asyncio
async def test_a_toolbox_failure_returns_none_and_closes_the_client(monkeypatch):
    from acessilia_sdk.toolbox import ToolboxProviderUnavailable

    from backend.tools import vision_payload

    closed = []

    class FailingClient:
        async def render(self, **_kwargs):
            raise ToolboxProviderUnavailable("pdf.render is down")

        async def close(self):
            closed.append(True)

    monkeypatch.setattr(vision_payload, "make_toolbox_client", lambda _cls: FailingClient())
    source = BytesIO()
    Image.new("RGB", (400, 240), "white").save(source, format="PNG")

    assert await downscale_image(source.getvalue()) is None
    assert closed == [True]


@pytest.mark.asyncio
async def test_a_client_that_cannot_be_built_returns_none(monkeypatch):
    from backend.tools import vision_payload

    def invalid_configuration(_cls):
        raise ValueError("Toolbox base_url must be an absolute http(s) URL")

    monkeypatch.setattr(vision_payload, "make_toolbox_client", invalid_configuration)
    source = BytesIO()
    Image.new("RGB", (400, 240), "white").save(source, format="PNG")

    assert await downscale_image(source.getvalue()) is None
