"""Left pane: one row per duplicate group."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QListWidget, QListWidgetItem

from ..core.grouping import DuplicateGroup
from ..util import human_size
from .thumbnails import ThumbnailLoader

_ICON = 56


class GroupList(QListWidget):
    def __init__(self, loader: ThumbnailLoader, parent=None) -> None:
        super().__init__(parent)
        self._loader = loader
        self._groups: list[DuplicateGroup] = []
        self._row_of: dict[str, int] = {}  # keeper path -> row
        self.setIconSize(QSize(_ICON, _ICON))
        self.setUniformItemSizes(True)
        self.setMinimumWidth(260)
        loader.loaded.connect(self._on_thumbnail)
        self.verticalScrollBar().valueChanged.connect(self._load_visible)

    def set_groups(self, groups: list[DuplicateGroup]) -> None:
        self.clear()
        self._groups = groups
        self._row_of = {str(group.keeper.file.path): row for row, group in enumerate(groups)}
        for group in groups:
            kind = "exact copies" if group.kind == "exact" else "similar"
            text = f"{len(group.images)} files · {kind}\n{human_size(group.reclaimable)} reclaimable"
            item = QListWidgetItem(text)
            item.setSizeHint(QSize(0, _ICON + 12))
            self.addItem(item)
        # Rows have no geometry until the event loop has laid them out.
        QTimer.singleShot(0, self._load_visible)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._load_visible()

    def _load_visible(self) -> None:
        """Request icons only for the rows on screen."""
        if not self._groups:
            return
        first = max(self.indexAt(QPoint(4, 4)).row(), 0)
        last = self.indexAt(QPoint(4, self.viewport().height() - 4)).row()
        if last < 0:
            last = len(self._groups) - 1
        for row in range(first, last + 1):
            if self.item(row).icon().isNull():
                self._set_icon(row)

    def _set_icon(self, row: int) -> None:
        pixmap = self._loader.get(self._groups[row].keeper.file.path, _ICON)
        if pixmap is not None and not pixmap.isNull():
            self.item(row).setIcon(QIcon(pixmap))

    def _on_thumbnail(self, path: str, size: int) -> None:
        row = self._row_of.get(path)
        if size == _ICON and row is not None:
            self._set_icon(row)
