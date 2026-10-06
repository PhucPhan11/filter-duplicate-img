"""Remove duplicates. The only removal path is the Recycle Bin."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from send2trash import send2trash

from .grouping import DuplicateGroup


@dataclass(slots=True)
class TrashResult:
    trashed: list[Path] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)


def remove_from_groups(groups: Iterable[DuplicateGroup], remove: Collection[Path]) -> TrashResult:
    """Send the files in `remove` to the Recycle Bin, group by group.

    A group is left untouched unless at least one of its other files still
    exists, and a file is left alone if it changed since it was scanned.
    """
    result = TrashResult()
    for group in groups:
        targets = [image for image in group.images if image.file.path in remove]
        if not targets:
            continue
        kept = [image for image in group.images if image.file.path not in remove]
        if not any(image.file.path.exists() for image in kept):
            result.failed.extend((image.file.path, "would remove every copy in its group") for image in targets)
            continue
        for image in targets:
            path = image.file.path
            try:
                stat = path.stat()
            except OSError:
                result.failed.append((path, "file no longer exists"))
                continue
            if stat.st_size != image.file.size or stat.st_mtime_ns != image.file.mtime_ns:
                result.failed.append((path, "file changed since the scan"))
                continue
            try:
                send2trash(str(path))
            except Exception as exc:  # send2trash raises platform-specific errors
                result.failed.append((path, str(exc) or type(exc).__name__))
            else:
                result.trashed.append(path)
    return result
