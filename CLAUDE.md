# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`dupimg`: a Windows desktop app (Python, PySide6) that finds exact and near-duplicate images, shows each group side by side, and sends the files the user rejects to the Recycle Bin.

## Commands

Dependencies are managed with `uv` (Python 3.11+ is the declared minimum, so avoid 3.12-only syntax such as reusing the same quote type inside an f-string).

```bash
uv sync                                        # install deps into .venv
uv run python -m dupimg                        # launch the GUI
uv run python -m dupimg.core <folder> [--threshold N] [--no-cache]   # print groups, touches no files
uv run pytest                                  # all tests
uv run pytest tests/test_core.py::test_groups_from_real_files       # one test
uv run pytest -k keeper                        # tests matching a name
```

There is no linter or formatter configured.

## Architecture

Two layers under `src/dupimg/`, with a hard rule: **`core/` never imports Qt**, so the engine is testable without a display. `ui/` depends on `core/`, never the reverse.

### Data flow

`scanner.scan` → `ImageFile(path, size, mtime_ns)` → `pipeline.run_scan` → `HashedImage(file, sha256, phash, width, height)` → `grouping.build_groups(images, threshold)` → `DuplicateGroup(images, kind, max_distance)` → `actions.remove_from_groups(groups, remove_paths)`.

Scanning/hashing and grouping are deliberately separate steps. `run_scan` is slow (disk + decode) and runs once; `build_groups` is pure and cheap, so the UI re-runs it on the in-memory `HashedImage` list each time the threshold slider moves.

### Things that are easy to get wrong

- **SHA-256 is conditional.** `run_scan` only computes a content hash for files that share a byte size with another file; otherwise `HashedImage.sha256` is `None`. A cache entry without a SHA is treated as a miss if the file now needs one.
- **Every file gets a pHash**, including byte-identical copies. A group's `kind` is `"exact"` only when all members share one non-`None` SHA.
- **Grouping is transitive** (union-find over a BK-tree of pHashes), so A~B~C can form one group even if A and C exceed the threshold. Threshold 0 still groups different files with an identical pHash.
- **`DuplicateGroup.images[0]` is the suggested keeper.** Order comes from `keeper.rank` (pixels → lossless extension → file size → oldest mtime → shortest path). `reclaimable` and the UI's default keep/remove marks both rely on that ordering.
- **Hashing functions must stay top-level and picklable** (`hashing.hash_file`): they run in a `ProcessPoolExecutor` (spawn on Windows). `hash_file` never raises; failures come back in the tuple's error slot and end up in `ScanResult.skipped`, and are not cached.
- **Below `pipeline._INLINE_LIMIT` files, hashing runs in-process.** Tests monkeypatch this to 0 to exercise the pool, and monkeypatch `pipeline.hash_file` to count calls (which only works on the inline path).
- **Pixel decoding must match between hashing and thumbnails**: both apply `ImageOps.exif_transpose` and use `img.draft` for JPEG speed. `core/hashing.py` registers the HEIC opener as an import side effect; `ui/thumbnails.py` imports it for that reason.
- **Camera RAW goes through `hashing._raw_preview`** (rawpy): the embedded JPEG preview is hashed and shown, while width/height report the full sensor size. So a RAW and its same-shot JPEG group together, and `keeper.rank` puts the RAW first. Add new formats in `scanner.RAW_EXTENSIONS` / `IMAGE_EXTENSIONS`; all decoding (hashing and thumbnails) goes through `hashing.load_upright`.
- **Scripts that call `run_scan` on more than `_INLINE_LIMIT` files must be real files with an `if __name__ == "__main__"` guard**, not stdin/heredocs, or the spawned workers crash.
- **pHash is stored as hex text in SQLite** because it is an unsigned 64-bit value. The cache lives at `%LOCALAPPDATA%\dupimg\cache.db`, keyed by path with size + mtime_ns validation.

### Removal safety invariants (`core/actions.py`)

These are enforced in the core, not just the UI, and are covered by tests. Preserve them:

- The only removal path is `send2trash`; there is no permanent delete.
- A group is skipped entirely unless at least one file *not* marked for removal still exists on disk.
- A file whose size or mtime changed since the scan is left alone and reported in `TrashResult.failed`.

Tests monkeypatch `actions.send2trash`; do not let tests send real files to the Recycle Bin.

### UI state (`ui/main_window.py`)

`MainWindow` owns all review state: `_images` (hashes from the last scan), `_groups` (derived), `_remove` (paths currently marked), and `_overrides` (the user's explicit keep/remove choices). `_regroup()` rebuilds `_groups` and recomputes `_remove` from keeper defaults plus `_overrides`, which is how user choices survive a threshold change. It also guarantees no group ends up fully marked.

Background work:

- `ui/worker.py` `ScanWorker` (QThread) runs `run_scan` and opens the `HashCache` inside the thread, since SQLite connections are thread-bound.
- `ui/thumbnails.py` `ThumbnailLoader.get(path, size)` returns a pixmap if cached, otherwise `None` and later emits `loaded(path, size)`; a null pixmap means the image could not be decoded. `GroupList` only requests icons for rows currently on screen.

### Testing the GUI

There are no GUI tests in `tests/`. To exercise the window without a display, set `QT_QPA_PLATFORM=offscreen` and point `LOCALAPPDATA` at a temp directory so the real hash cache is not touched. Text renders as boxes in offscreen screenshots (no fonts); layout and behaviour are still valid.

## Not yet built

PyInstaller `.exe` packaging (`__main__.main` already calls `multiprocessing.freeze_support()` for it).
