"""Image optimisation for redazione uploads (backend/app/services/images.py)."""

from io import BytesIO

import pytest
from PIL import Image

from backend.app.services.images import ImageRejected, optimize


def _jpeg(size, *, exif: bytes | None = None, quality=95) -> bytes:
    image = Image.new("RGB", size)
    pixels = image.load()
    for x in range(0, size[0], 5):
        for y in range(0, size[1], 5):
            pixels[x, y] = (x % 256, y % 256, (x + y) % 256)
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=quality, **({"exif": exif} if exif else {}))
    return buffer.getvalue()


def test_a_big_photo_is_resized_and_compressed_without_growing():
    original = _jpeg((3200, 2400))
    result = optimize(original, "photo")
    assert result.content_type == "image/webp"
    assert (result.width, result.height) == (1800, 1350)
    assert len(result.data) < len(original) / 3


def test_camera_orientation_is_applied_and_metadata_dropped():
    exif = Image.Exif()
    exif[0x0112] = 6  # rotated 90°: the camera saved it sideways
    exif[0x8825] = {2: (45.0, 28.0, 0.0)}  # a GPS position that must not be published
    result = optimize(_jpeg((400, 200), exif=exif.tobytes()), "photo")
    with Image.open(BytesIO(result.data)) as image:
        assert image.size == (200, 400)
        assert not image.info.get("exif")


def test_a_logo_keeps_its_transparency():
    logo = Image.new("RGBA", (1000, 1000), (0, 0, 0, 0))
    logo.paste((20, 60, 140, 255), (200, 200, 800, 800))
    buffer = BytesIO()
    logo.save(buffer, format="PNG")
    result = optimize(buffer.getvalue(), "logo")
    with Image.open(BytesIO(result.data)) as image:
        assert max(image.size) == 640
        assert image.mode == "RGBA" and image.getpixel((5, 5))[3] == 0


def test_small_images_are_never_enlarged():
    result = optimize(_jpeg((120, 80)), "photo")
    assert (result.width, result.height) == (120, 80)


@pytest.mark.parametrize("data", [b"", b"hello", b"\xff\xd8\xff\xe0" + b"\x00" * 64])
def test_anything_that_is_not_a_readable_image_is_refused(data):
    with pytest.raises(ImageRejected):
        optimize(data, "photo")


def test_decompression_bombs_are_refused():
    buffer = BytesIO()
    Image.new("1", (12000, 12000)).save(buffer, format="PNG")
    with pytest.raises(ImageRejected):
        optimize(buffer.getvalue(), "logo")
