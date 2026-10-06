"""Content hash (SHA-256) and perceptual hash (64-bit pHash) of image files.

Everything here is a top-level function so it can run in worker processes.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import imagehash
from PIL import Image, ImageOps

from .scanner import ImageFile

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


def perceptual_hash(source: str | Path | BinaryIO) -> tuple[int, int, int]:
    """Return (phash, width, height) with EXIF rotation applied."""
    with Image.open(source) as img:
        width, height = img.size
        if img.getexif().get(_EXIF_ORIENTATION, 1) in (5, 6, 7, 8):
            width, height = height, width
        img.draft("RGB", _DRAFT_SIZE)
        upright = ImageOps.exif_transpose(img)
        value = int(str(imagehash.phash(upright)), 16)
    return value, width, height


# (path, sha256, phash, width, height, error)
HashResult = tuple[str, str | None, int, int, int, str | None]


def hash_file(path: str, need_sha: bool) -> HashResult:
    """Hash one file. Never raises: failures come back in the error slot."""
    try:
        if need_sha:
            data = Path(path).read_bytes()
            sha = hashlib.sha256(data).hexdigest()
            phash, width, height = perceptual_hash(io.BytesIO(data))
        else:
            sha = None
            phash, width, height = perceptual_hash(path)
        return path, sha, phash, width, height, None
    except Exception as exc:  # corrupt or unsupported files must not stop a scan
        return path, None, 0, 0, 0, f"{type(exc).__name__}: {exc}"
