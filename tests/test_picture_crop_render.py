"""A large standalone picture is cropped within the Toolbox's render limit.

The picture crop used to be rendered at 160 dpi without a ``max_side``. A
standalone image becomes a page sized in pixels, so a 4087x3072 photo asked
for ~54 MP, over the Toolbox's 20 MP limit: the crop failed, the picture was
left undescribed and a job whose only obligation was ``describe-image``
ended in error.
"""

from __future__ import annotations

from PIL import Image

from backend.agents.pddl_orchestrator import _PICTURE_MAX_SIDE, _extract_picture_bytes
from backend.core.manifest.models import BoundingBox, ManifestElement, Provenance


def _picture(width: int, height: int) -> ManifestElement:
    return ManifestElement(
        id="pic-1",
        type="picture",
        raw_label="picture",
        reading_order=1,
        hierarchy_level=1,
        page_number=1,
        provenance=[
            Provenance(
                page_number=1,
                bbox=BoundingBox(
                    left=0,
                    top=height,
                    right=width,
                    bottom=0,
                    coord_origin="BOTTOMLEFT",
                ),
            )
        ],
    )


def test_a_large_standalone_image_is_rendered_below_the_pixel_limit(
    fake_toolbox_render, tmp_path
):
    width, height = 4087, 3072
    source = tmp_path / "photo.jpg"
    Image.new("RGB", (width, height), "white").save(source, "JPEG")

    image, page = _extract_picture_bytes(
        source, _picture(width, height), 1, media_type="image/jpeg"
    )

    assert page == 1
    assert image is not None
    assert image.startswith(b"\x89PNG")
    assert fake_toolbox_render.parameters[-1]["max_side"] == _PICTURE_MAX_SIDE
