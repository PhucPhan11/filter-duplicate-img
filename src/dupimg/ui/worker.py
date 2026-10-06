"""Runs a scan off the GUI thread."""

from __future__ import annotations

import time

from PySide6.QtCore import QThread, Signal

from ..core.cache import HashCache
from ..core.pipeline import ScanCancelled, run_scan


class ScanWorker(QThread):
    progress = Signal(str, int, int)  # phase, done, total
    done = Signal(object)  # ScanResult
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, folders: list[str], parent=None) -> None:
        super().__init__(parent)
        self._folders = folders
        self._cancel = False
        self._last_report = 0.0

    def cancel(self) -> None:
        self._cancel = True

    def _report(self, phase: str, done: int, total: int) -> None:
        now = time.monotonic()
        if done == total or now - self._last_report >= 0.05:
            self._last_report = now
            self.progress.emit(phase, done, total)

    def run(self) -> None:
        try:
            # The cache is opened here because SQLite connections belong to one thread.
            with HashCache() as cache:
                result = run_scan(self._folders, cache, self._report, lambda: self._cancel)
        except ScanCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.done.emit(result)
