"""Scan folders and hash every image, using the cache and worker processes."""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Callable, Iterable
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from .cache import HashCache
from .hashing import HashedImage, HashResult, hash_file
from .scanner import ImageFile, Skipped, scan

# Below this many files, hashing in-process beats starting a worker pool.
_INLINE_LIMIT = 32
_COMMIT_EVERY = 500

Progress = Callable[[str, int, int], None]  # phase, done, total (0 = unknown)


class ScanCancelled(Exception):
    pass


@dataclass(slots=True)
class ScanResult:
    images: list[HashedImage] = field(default_factory=list)
    skipped: Skipped = field(default_factory=list)


def run_scan(
    folders: Iterable[str | Path],
    cache: HashCache | None = None,
    progress: Progress | None = None,
    cancel: Callable[[], bool] | None = None,
    workers: int | None = None,
) -> ScanResult:
    """Find and hash all images under `folders`. Raises ScanCancelled if `cancel()` turns true."""

    def report(phase: str, done: int, total: int) -> None:
        if progress:
            progress(phase, done, total)

    def check_cancel() -> None:
        if cancel and cancel():
            raise ScanCancelled

    result = ScanResult()
    files: list[ImageFile] = []
    for file in scan(folders, result.skipped):
        check_cancel()
        files.append(file)
        if len(files) % 200 == 0:
            report("scanning", len(files), 0)

    # A content hash can only match between files of the same size.
    size_counts = Counter(file.size for file in files)
    todo: list[tuple[ImageFile, bool]] = []
    for file in files:
        need_sha = size_counts[file.size] > 1
        cached = cache.get(file) if cache else None
        if cached and (cached.sha256 or not need_sha):
            result.images.append(cached)
        else:
            todo.append((file, need_sha))

    total = len(files)
    done = len(result.images)
    report("hashing", done, total)

    def record(file: ImageFile, hashed: HashResult) -> None:
        nonlocal done
        _path, sha, phash, width, height, error = hashed
        if error:
            result.skipped.append((file.path, error))
        else:
            image = HashedImage(file, sha, phash, width, height)
            result.images.append(image)
            if cache:
                cache.put(image)
                if done % _COMMIT_EVERY == 0:
                    cache.commit()
        done += 1
        report("hashing", done, total)

    try:
        if len(todo) <= _INLINE_LIMIT:
            for file, need_sha in todo:
                check_cancel()
                record(file, hash_file(str(file.path), need_sha))
        else:
            workers = workers or max(1, (os.cpu_count() or 2) - 1)
            with ProcessPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(hash_file, str(file.path), need_sha): file for file, need_sha in todo}
                try:
                    for future in as_completed(futures):
                        check_cancel()
                        record(futures[future], future.result())
                except BaseException:
                    pool.shutdown(wait=True, cancel_futures=True)
                    raise
    finally:
        # Keep what was hashed so far, even when cancelled.
        if cache:
            cache.commit()
    return result
