"""Background thumbnail loading with a small in-memory cache."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage, QPixmap

from ..core.hashing import load_upright

_CACHE_LIMIT = 1500


def load_thumbnail(path: str, size: int) -> QImage:
    """Decode the same way hashing does, so HEIC, RAW and EXIF rotation all match."""
    upright = load_upright(path, min_size=(size, size))[0]
    upright.thumbnail((size, size))
    rgba = upright.convert("RGBA")
    data = rgba.tobytes()
    return QImage(data, rgba.width, rgba.height, rgba.width * 4, QImage.Format.Format_RGBA8888).copy()


class _Signals(QObject):
    decoded = Signal(str, int, QImage)


class _Task(QRunnable):
    def __init__(self, path: str, size: int, signals: _Signals) -> None:
        super().__init__()
        self._path, self._size, self._signals = path, size, signals

    def run(self) -> None:
        try:
            image = load_thumbnail(self._path, self._size)
        except Exception:
            image = QImage()
        try:
            self._signals.decoded.emit(self._path, self._size, image)
        except RuntimeError:  # the loader was destroyed while we were decoding
            pass


class ThumbnailLoader(QObject):
    """`get` returns a pixmap if it is ready; otherwise `loaded` fires when it is."""

    loaded = Signal(str, int)  # path, size

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._signals = _Signals(self)
        self._signals.decoded.connect(self._on_decoded)
        self._cache: OrderedDict[tuple[str, int], QPixmap] = OrderedDict()
        self._pending: set[tuple[str, int]] = set()

    def get(self, path: Path | str, size: int) -> QPixmap | None:
        """Return the thumbnail (a null pixmap if it cannot be decoded), or None while loading."""
        key = (str(path), size)
        pixmap = self._cache.get(key)
        if pixmap is not None:
            self._cache.move_to_end(key)
            return pixmap
        if key not in self._pending:
            self._pending.add(key)
            self._pool.start(_Task(key[0], size, self._signals))
        return None

    def forget(self, paths) -> None:
        gone = {str(path) for path in paths}
        for key in [key for key in self._cache if key[0] in gone]:
            del self._cache[key]

    def shutdown(self) -> None:
        self._pool.clear()
        self._pool.waitForDone()

    def _on_decoded(self, path: str, size: int, image: QImage) -> None:
        key = (path, size)
        self._pending.discard(key)
        self._cache[key] = QPixmap.fromImage(image)
        while len(self._cache) > _CACHE_LIMIT:
            self._cache.popitem(last=False)
        self.loaded.emit(path, size)
