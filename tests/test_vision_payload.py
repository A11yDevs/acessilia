"""Image recovery uses the rendering contract, including raster inputs."""

from io import BytesIO

import pytest
from acessilia_core.toolbox.vision_payload import downscale_image
from PIL import Image

from tests.core_config_support import toolbox_config


@pytest.mark.asyncio
@pytest.mark.parametrize("format_name", ["PNG", "JPEG"])
async def test_context_recovery_resizes_raster_images_on_the_toolbox(format_name, fake_toolbox_render):
    source = BytesIO()
    Image.new("RGB", (400, 240), "white").save(source, format=format_name)

    result = await downscale_image(source.getvalue(), toolbox=toolbox_config())

    with Image.open(BytesIO(result)) as image:
        assert image.size == (200, 120)
    assert fake_toolbox_render.parameters == [{"page_number": 1, "dpi": 150, "max_side": 200}]


@pytest.mark.asyncio
async def test_invalid_or_unshrinkable_images_do_not_call_the_toolbox(fake_toolbox_render):
    source = BytesIO()
    Image.new("RGB", (1, 1), "white").save(source, format="PNG")

    assert await downscale_image(b"not an image", toolbox=toolbox_config()) is None
    assert await downscale_image(source.getvalue(), toolbox=toolbox_config()) is None
    assert fake_toolbox_render.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_scale", [0, -0.5, float("nan"), float("inf"), True])
async def test_non_positive_or_invalid_scale_returns_none_without_building_client(
    monkeypatch, bad_scale
):
    from acessilia_core.toolbox import vision_payload

    built = []
    monkeypatch.setattr(
        vision_payload, "make_toolbox_client", lambda *_a, **_kw: built.append(True)
    )
    source = BytesIO()
    Image.new("RGB", (400, 240), "white").save(source, format="PNG")

    assert await downscale_image(source.getvalue(), scale=bad_scale, toolbox=toolbox_config()) is None
    assert built == []


@pytest.mark.asyncio
async def test_a_toolbox_failure_returns_none_and_closes_the_client(monkeypatch):
    from acessilia_core.toolbox import vision_payload
    from acessilia_sdk.toolbox import ToolboxProviderUnavailable

    closed = []

    class FailingClient:
        async def render(self, **_kwargs):
            raise ToolboxProviderUnavailable("pdf.render is down")

        async def close(self):
            closed.append(True)

    monkeypatch.setattr(vision_payload, "make_toolbox_client", lambda _cls, _toolbox: FailingClient())
    source = BytesIO()
    Image.new("RGB", (400, 240), "white").save(source, format="PNG")

    assert await downscale_image(source.getvalue(), toolbox=toolbox_config()) is None
    assert closed == [True]


@pytest.mark.asyncio
async def test_a_client_that_cannot_be_built_returns_none(monkeypatch):
    from acessilia_core.toolbox import vision_payload

    def invalid_configuration(_cls, _toolbox):
        raise ValueError("Toolbox base_url must be an absolute http(s) URL")

    monkeypatch.setattr(vision_payload, "make_toolbox_client", invalid_configuration)
    source = BytesIO()
    Image.new("RGB", (400, 240), "white").save(source, format="PNG")

    assert await downscale_image(source.getvalue(), toolbox=toolbox_config()) is None
