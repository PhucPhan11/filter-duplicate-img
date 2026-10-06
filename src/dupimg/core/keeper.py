"""Decide which file in a duplicate group is the best one to keep."""

from __future__ import annotations

from collections.abc import Iterable

from .hashing import HashedImage

LOSSLESS_EXTENSIONS = frozenset({".png", ".bmp", ".tif", ".tiff"})


def _rank_key(image: HashedImage) -> tuple:
    path = image.file.path
    return (
        -image.pixels,
        path.suffix.lower() not in LOSSLESS_EXTENSIONS,
        -image.file.size,
        image.file.mtime_ns,
        len(str(path)),
        str(path),
    )


def rank(images: Iterable[HashedImage]) -> list[HashedImage]:
    """Best keeper first: most pixels, lossless, largest file, oldest, shortest path."""
    return sorted(images, key=_rank_key)
