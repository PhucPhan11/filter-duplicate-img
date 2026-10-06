"""SQLite cache of hashes so rescans only touch new or changed files."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from .hashing import HashedImage
from .scanner import ImageFile

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    path     TEXT PRIMARY KEY,
    size     INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    sha256   TEXT,
    phash    TEXT NOT NULL,
    width    INTEGER NOT NULL,
    height   INTEGER NOT NULL
)
"""


def default_cache_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or Path.home() / ".cache"
    return Path(base) / "dupimg" / "cache.db"


class HashCache:
    def __init__(self, path: str | Path | None = None) -> None:
        path = Path(path) if path else default_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute(_SCHEMA)

    def get(self, file: ImageFile) -> HashedImage | None:
        """Return the cached hashes, or None if the file is new or has changed."""
        row = self._db.execute(
            "SELECT size, mtime_ns, sha256, phash, width, height FROM files WHERE path = ?",
            (str(file.path),),
        ).fetchone()
        if row is None or row[0] != file.size or row[1] != file.mtime_ns:
            return None
        # phash is stored as hex text: SQLite integers are signed 64-bit.
        return HashedImage(file, row[2], int(row[3], 16), row[4], row[5])

    def put(self, image: HashedImage) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO files VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                str(image.file.path),
                image.file.size,
                image.file.mtime_ns,
                image.sha256,
                f"{image.phash:016x}",
                image.width,
                image.height,
            ),
        )

    def commit(self) -> None:
        self._db.commit()

    def close(self) -> None:
        self._db.commit()
        self._db.close()

    def __enter__(self) -> HashCache:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
