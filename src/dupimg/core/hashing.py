"""Content hash (SHA-256) and perceptual hash (64-bit pHash) of image files.

Everything here is a top-level function so it can run in worker processes.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

import imagehash
import rawpy
from PIL import Image, ImageOps

from .scanner import RAW_EXTENSIONS, ImageFile

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:  # HEIC support is optional
    pass

# JPEGs are decoded at reduced scale (never below this size) to keep hashing fast.
_DRAFT_SIZE = (512, 512)
_EXIF_ORIENTATION = 0x0112


@dataclass(frozen=True, slots=True)
class HashedImage:
    file: ImageFile
    sha256: str | None  # only computed when another file has the same size
    phash: int
    width: int
    height: int

    @property
    def pixels(self) -> int:
        return self.width * self.height


def _raw_preview(source: str | io.BytesIO) -> tuple[io.BytesIO | Image.Image, tuple[int, int]]:
    """Return a RAW file's preview and its full upright (width, height).

    The embedded JPEG is used when there is one, since developing the sensor
    data is far slower. Its own EXIF tag carries the rotation.
    """
    with rawpy.imread(source) as raw:
        sizes = raw.sizes
        full_size = (sizes.height, sizes.width) if sizes.flip in (5, 6) else (sizes.width, sizes.height)
        try:
            thumb = raw.extract_thumb()
        except (rawpy.LibRawNoThumbnailError, rawpy.LibRawUnsupportedThumbnailError):
            return Image.fromarray(raw.postprocess(half_size=True)), full_size
        if thumb.format == rawpy.ThumbFormat.JPEG:
            return io.BytesIO(thumb.data), full_size
        return Image.fromarray(thumb.data), full_size


def load_upright(
    path: str | Path, data: bytes | None = None, min_size: tuple[int, int] = _DRAFT_SIZE
) -> tuple[Image.Image, int, int]:
    """Decode an image (from `data` if given) with EXIF rotation applied.

    Returns (image, width, height). The image may be smaller than the stated
    full size: JPEGs are decoded at reduced scale, though not below `min_size`.
    """
    source: str | io.BytesIO | Image.Image = io.BytesIO(data) if data is not None else str(path)
    full_size = None
    if Path(path).suffix.lower() in RAW_EXTENSIONS:
        source, full_size = _raw_preview(source)
        if isinstance(source, Image.Image):
            return source, *full_size
    with Image.open(source) as img:
        width, height = img.size
        if img.getexif().get(_EXIF_ORIENTATION, 1) in (5, 6, 7, 8):
            width, height = height, width
        img.draft("RGB", min_size)
        upright = ImageOps.exif_transpose(img)
    return upright, *(full_size or (width, height))


def perceptual_hash(path: str | Path, data: bytes | None = None) -> tuple[int, int, int]:
    """Return (phash, width, height) with EXIF rotation applied."""
    upright, width, height = load_upright(path, data)
    return int(str(imagehash.phash(upright)), 16), width, height


# (path, sha256, phash, width, height, error)
HashResult = tuple[str, str | None, int, int, int, str | None]


def hash_file(path: str, need_sha: bool) -> HashResult:
    """Hash one file. Never raises: failures come back in the error slot."""
    try:
        if need_sha:
            data = Path(path).read_bytes()
            sha = hashlib.sha256(data).hexdigest()
            phash, width, height = perceptual_hash(path, data)
        else:
            sha = None
            phash, width, height = perceptual_hash(path)
        return path, sha, phash, width, height, None
    except Exception as exc:  # corrupt or unsupported files must not stop a scan
        return path, None, 0, 0, 0, f"{type(exc).__name__}: {exc}"
