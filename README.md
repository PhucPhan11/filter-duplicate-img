# filter-duplicate-img

A Windows desktop app that finds duplicate images, shows each set side by side, and sends the ones you reject to the Recycle Bin.

It catches byte-identical copies and near-duplicates: the same picture resized, recompressed, rotated via EXIF, or saved in another format.

## Run

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run python -m dupimg
```

1. **Add folder…** for each folder to search (subfolders are included), then **Scan**.
2. Pick a group on the left. The suggested keeper (highest resolution, then lossless format, larger file, older file) is marked **Keep**; the rest are marked **Remove**. Click a button to flip it, or **Keep all in this group** to skip the group.
3. **Move to Recycle Bin** removes everything marked. Files can be restored from the Recycle Bin.

The **Similarity tolerance** slider sets how many of the 64 perceptual-hash bits may differ (0 = strictest, 16 = loosest, default 6). Moving it regroups without rescanning.

Hashes are cached in `%LOCALAPPDATA%\dupimg\cache.db`, so later scans only read new or changed files.

## Command-line preview

Prints the groups without opening the GUI or touching any file:

```bash
uv run python -m dupimg.core "C:\path\to\photos" --threshold 6
```

## Tests

```bash
uv run pytest
```

## Layout

- `src/dupimg/core/` scanning, hashing, cache, grouping, keeper ranking, Recycle Bin action (no GUI imports)
- `src/dupimg/ui/` PySide6 window, group list, review pane, background scan and thumbnail loading
