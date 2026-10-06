"""Walk folders and yield the image files found in them."""

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

IMAGE_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic", ".heif"}
)

Skipped = list[tuple[Path, str]]


@dataclass(frozen=True, slots=True)
class ImageFile:
    path: Path
    size: int
    mtime_ns: int


def scan(folders: Iterable[str | Path], skipped: Skipped | None = None) -> Iterator[ImageFile]:
    """Yield every image under `folders`, once each even if the folders overlap.

    Unreadable folders and files are appended to `skipped` instead of raising.
    """
    seen: set[str] = set()

    def on_error(exc: OSError) -> None:
        if skipped is not None:
            skipped.append((Path(exc.filename or "?"), exc.strerror or str(exc)))

    for folder in folders:
        for root, _dirs, names in os.walk(folder, onerror=on_error):
            for name in names:
                if os.path.splitext(name)[1].lower() not in IMAGE_EXTENSIONS:
                    continue
                path = Path(root, name)
                try:
                    key = os.path.normcase(path.resolve())
                    if key in seen:
                        continue
                    seen.add(key)
                    stat = path.stat()
                except OSError as exc:
                    if skipped is not None:
                        skipped.append((path, exc.strerror or str(exc)))
                    continue
                yield ImageFile(path, stat.st_size, stat.st_mtime_ns)
