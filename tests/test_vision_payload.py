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
