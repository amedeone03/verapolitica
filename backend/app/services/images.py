"""Image optimisation for everything the redazione uploads.

One pass, at upload time, so serving stays a plain byte copy (cheap on a VPS):

* the file must really be an image (Pillow decodes it; a renamed text file or a
  truncated upload is refused) and not a decompression bomb;
* the camera orientation (EXIF) is applied, then all metadata is dropped
  (GPS position, camera serial, editing history);
* it is resized for its use, never enlarged;
* it is re-encoded as WebP: photos lossy at a visually transparent quality,
  logos and coats of arms keep transparency and use lossless when that is
  smaller. If the result is not smaller than a clean original, the original
  wins.

The output is what ``/media/{id}`` serves with a one-year immutable cache.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

# A 50-megapixel camera photo is fine; a crafted 1-gigapixel PNG is not.
Image.MAX_IMAGE_PIXELS = 60_000_000
MAX_INPUT_BYTES = 15 * 1024 * 1024

# Longest side in pixels and WebP quality (None = logo rules: transparency kept,
# lossless when smaller). Sizes cover 2x screens at the size each image is shown.
PURPOSES: dict[str, tuple[int, int | None]] = {
    "card": (512, 84),       # round portrait on a feed card (shown at ~56px)
    "portrait": (900, 84),   # politician photo (hero up to ~300px wide)
    "logo": (640, None),     # party logo, coat of arms of a region/province/comune
    "photo": (1800, 80),     # territory cover photo (full-width hero)
}
DEFAULT_PURPOSE = "card"
PURPOSE_LABELS = {"card": "card del feed", "portrait": "foto di un politico", "logo": "logo o stemma", "photo": "foto del territorio"}


class ImageRejected(ValueError):
    """The upload is not an image we can publish."""


@dataclass(frozen=True)
class OptimizedImage:
    data: bytes
    content_type: str
    width: int
    height: int
    original_bytes: int

    @property
    def saved_percent(self) -> int:
        if not self.original_bytes:
            return 0
        return max(0, round(100 * (1 - len(self.data) / self.original_bytes)))


def _has_alpha(image: Image.Image) -> bool:
    if image.mode in ("RGBA", "LA"):
        return image.getextrema()[-1][0] < 255
    if image.mode == "P":
        return "transparency" in image.info
    return False


def _encode(image: Image.Image, **options) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="WEBP", **options)
    return buffer.getvalue()


def optimize(data: bytes, purpose: str = DEFAULT_PURPOSE) -> OptimizedImage:
    """Decode, clean, resize and re-encode an uploaded image."""

    if not data:
        raise ImageRejected("Immagine vuota.")
    if len(data) > MAX_INPUT_BYTES:
        raise ImageRejected("L'immagine è troppo grande (massimo 15 MB).")
    max_side, quality = PURPOSES.get(purpose, PURPOSES[DEFAULT_PURPOSE])
    try:
        with Image.open(io.BytesIO(data)) as probe:
            source_format = probe.format
            probe.verify()
        image = Image.open(io.BytesIO(data))
        image.seek(0)  # first frame of an animated file
        image.load()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError) as error:
        raise ImageRejected("Il file non è un'immagine leggibile: usa JPEG, PNG o WebP.") from error
    if source_format not in {"JPEG", "PNG", "WEBP", "MPO", "AVIF", "HEIF", "GIF"}:
        raise ImageRejected("Formato non supportato: usa JPEG, PNG o WebP.")

    image = ImageOps.exif_transpose(image)
    alpha = _has_alpha(image)
    image = image.convert("RGBA" if alpha else "RGB")
    if max(image.size) > max_side:
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)

    if quality is None:
        # Logos: crisp edges and flat colours. Try both and keep the smaller.
        candidates = [
            _encode(image, lossless=True, quality=100, method=6),
            _encode(image, quality=92, alpha_quality=100, method=6),
        ]
        encoded = min(candidates, key=len)
    else:
        if alpha:
            # Photos are shown on light surfaces: flatten transparency on white.
            flat = Image.new("RGB", image.size, (255, 255, 255))
            flat.paste(image, mask=image.getchannel("A"))
            image = flat
        encoded = _encode(image, quality=quality, method=4)

    width, height = image.size
    original = _clean_original(data, source_format, (width, height))
    if original is not None and len(original[0]) <= len(encoded):
        return OptimizedImage(original[0], original[1], width, height, len(data))
    return OptimizedImage(encoded, "image/webp", width, height, len(data))


def _clean_original(data: bytes, source_format: str, size: tuple[int, int]) -> tuple[bytes, str] | None:
    """The original file, when it needs no resizing and carries no metadata to remove.

    A PNG is re-saved losslessly (that drops text chunks and often shrinks it).
    JPEG/WebP cannot be stripped without re-compressing, so they are kept only
    when they have no EXIF/XMP at all.
    """

    with Image.open(io.BytesIO(data)) as image:
        if image.size != size or image.info.get("exif") or image.info.get("xmp"):
            return None
        if source_format == "PNG":
            buffer = io.BytesIO()
            image.save(buffer, format="PNG", optimize=True)
            return buffer.getvalue(), "image/png"
    if source_format == "JPEG":
        return data, "image/jpeg"
    if source_format == "WEBP":
        return data, "image/webp"
    return None
