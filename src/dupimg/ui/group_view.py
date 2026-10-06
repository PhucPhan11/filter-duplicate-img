"""Right pane: the images of one group side by side, each with a keep/remove toggle."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Collection
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from ..core.grouping import DuplicateGroup
from ..core.hashing import HashedImage
from ..util import human_size
from .thumbnails import ThumbnailLoader

_THUMB = 260
_KEEP_STYLE = "QPushButton { background: #2e7d32; color: white; font-weight: bold; padding: 6px; }"
_REMOVE_STYLE = "QPushButton { background: #c62828; color: white; font-weight: bold; padding: 6px; }"


def reveal_in_file_manager(path: Path) -> None:
    if sys.platform == "win32":
        subprocess.Popen(f'explorer /select,"{path}"')
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


class _Thumbnail(QLabel):
    double_clicked = Signal()

    def mouseDoubleClickEvent(self, event) -> None:
        self.double_clicked.emit()


class ImageCard(QFrame):
    remove_toggled = Signal(object, bool)  # Path, marked for removal

    def __init__(self, image: HashedImage, suggested: bool, removed: bool, parent=None) -> None:
        super().__init__(parent)
        self.path = image.file.path
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFixedWidth(_THUMB + 24)

        self.thumbnail = _Thumbnail("Loading…")
        self.thumbnail.setFixedSize(_THUMB, _THUMB)
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail.setToolTip("Double-click to open")
        self.thumbnail.double_clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path))))

        name = QLabel(self.path.name + ("  ★ suggested" if suggested else ""))
        name.setStyleSheet("font-weight: bold;")
        name.setWordWrap(True)

        modified = datetime.fromtimestamp(image.file.mtime_ns / 1e9).strftime("%Y-%m-%d %H:%M")
        suffix = self.path.suffix.lstrip(".").upper()
        details = QLabel(f"{image.width} × {image.height} · {human_size(image.file.size)} · {suffix}\nModified {modified}")

        folder = QLabel(str(self.path.parent))
        folder.setWordWrap(True)
        folder.setToolTip(str(self.path))
        folder.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        folder.setStyleSheet("color: gray;")

        self._toggle = QPushButton()
        self._toggle.setCheckable(True)
        self._toggle.clicked.connect(lambda checked: self.remove_toggled.emit(self.path, checked))
        self.set_removed(removed)

        reveal = QPushButton("Show in folder")
        reveal.clicked.connect(lambda: reveal_in_file_manager(self.path))

        layout = QVBoxLayout(self)
        for widget in (self.thumbnail, name, details, folder):
            layout.addWidget(widget)
        layout.addStretch(1)
        layout.addWidget(self._toggle)
        layout.addWidget(reveal)

    def set_removed(self, removed: bool) -> None:
        self._toggle.setChecked(removed)
        self._toggle.setText("Remove" if removed else "Keep")
        self._toggle.setStyleSheet(_REMOVE_STYLE if removed else _KEEP_STYLE)


class GroupView(QWidget):
    remove_toggled = Signal(object, bool)  # Path, marked for removal
    keep_all_requested = Signal()

    def __init__(self, loader: ThumbnailLoader, parent=None) -> None:
        super().__init__(parent)
        self._loader = loader
        self._cards: dict[str, ImageCard] = {}
        loader.loaded.connect(self._on_thumbnail)

        self._title = QLabel()
        self._keep_all = QPushButton("Keep all in this group")
        self._keep_all.clicked.connect(self.keep_all_requested)
        header = QHBoxLayout()
        header.addWidget(self._title, 1)
        header.addWidget(self._keep_all)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(self._scroll, 1)
        self.show_group(None, ())

    def show_group(self, group: DuplicateGroup | None, removed: Collection[Path]) -> None:
        self._cards = {}
        self._keep_all.setVisible(group is not None)
        if group is None:
            self._title.setText("")
            placeholder = QLabel("Add folders and press Scan. Duplicate groups will appear on the left.")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._scroll.setWidget(placeholder)
            return

        if group.kind == "exact":
            self._title.setText(f"{len(group.images)} byte-identical files")
        else:
            self._title.setText(f"{len(group.images)} similar images (up to {group.max_distance} of 64 hash bits differ)")

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        for index, image in enumerate(group.images):
            card = ImageCard(image, suggested=index == 0, removed=image.file.path in removed)
            card.remove_toggled.connect(self.remove_toggled)
            row_layout.addWidget(card)
            self._cards[str(image.file.path)] = card
            self._apply_thumbnail(card)
        self._scroll.setWidget(row)

    def set_removed(self, path: Path, removed: bool) -> None:
        card = self._cards.get(str(path))
        if card:
            card.set_removed(removed)

    def _apply_thumbnail(self, card: ImageCard) -> None:
        pixmap = self._loader.get(card.path, _THUMB)
        if pixmap is None:
            return
        if pixmap.isNull():
            card.thumbnail.setText("No preview")
        else:
            card.thumbnail.setPixmap(pixmap)

    def _on_thumbnail(self, path: str, size: int) -> None:
        card = self._cards.get(path)
        if size == _THUMB and card:
            self._apply_thumbnail(card)
