"""Main window: choose folders, scan, review groups, send rejects to the Recycle Bin."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..core.actions import remove_from_groups
from ..core.grouping import DEFAULT_THRESHOLD, MAX_THRESHOLD, DuplicateGroup, build_groups
from ..core.hashing import HashedImage
from ..core.pipeline import ScanResult
from ..core.scanner import Skipped
from ..util import human_size, plural
from .group_list import GroupList
from .group_view import GroupView
from .thumbnails import ThumbnailLoader
from .worker import ScanWorker


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Duplicate Image Filter")
        self.resize(1200, 760)

        self._images: list[HashedImage] = []
        self._groups: list[DuplicateGroup] = []
        self._skipped: Skipped = []
        # Files marked for removal, and the user's explicit choices (which survive regrouping).
        self._remove: set[Path] = set()
        self._overrides: dict[Path, bool] = {}
        self._worker: ScanWorker | None = None
        self._loader = ThumbnailLoader(self)

        # --- top bar: folders, threshold, scan ---
        self._folders = QListWidget()
        self._folders.setMaximumHeight(72)
        add_folder = QPushButton("Add folder…")
        add_folder.clicked.connect(self._add_folder)
        remove_folder = QPushButton("Remove")
        remove_folder.clicked.connect(lambda: self._folders.takeItem(self._folders.currentRow()))
        folder_buttons = QVBoxLayout()
        folder_buttons.addWidget(add_folder)
        folder_buttons.addWidget(remove_folder)
        self._folder_controls = (self._folders, add_folder, remove_folder)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, MAX_THRESHOLD)
        self._slider.setValue(DEFAULT_THRESHOLD)
        self._slider.setFixedWidth(180)
        self._slider.setTracking(False)  # regroup when released, not on every step
        self._slider.setToolTip("How different two images may be and still count as duplicates.\n0 = strictest, 16 = loosest.")
        self._slider_label = QLabel()
        self._slider.sliderMoved.connect(self._show_threshold)
        self._slider.valueChanged.connect(self._on_threshold_changed)
        self._show_threshold(DEFAULT_THRESHOLD)
        slider_box = QVBoxLayout()
        slider_box.addWidget(self._slider_label)
        slider_box.addWidget(self._slider)

        self._scan_button = QPushButton("Scan")
        self._scan_button.setMinimumHeight(48)
        self._scan_button.setMinimumWidth(100)
        self._scan_button.clicked.connect(self._scan_or_cancel)

        top = QHBoxLayout()
        top.addWidget(self._folders, 1)
        top.addLayout(folder_buttons)
        top.addSpacing(16)
        top.addLayout(slider_box)
        top.addSpacing(16)
        top.addWidget(self._scan_button)

        self._progress = QProgressBar()
        self._progress.setVisible(False)

        # --- centre: group list and review pane ---
        self._group_list = GroupList(self._loader)
        self._group_list.currentRowChanged.connect(self._show_current_group)
        self._group_view = GroupView(self._loader)
        self._group_view.remove_toggled.connect(self._on_remove_toggled)
        self._group_view.keep_all_requested.connect(self._keep_all_in_current_group)
        splitter = QSplitter()
        splitter.addWidget(self._group_list)
        splitter.addWidget(self._group_view)
        splitter.setStretchFactor(1, 1)

        # --- bottom bar: totals and the one destructive button ---
        self._totals = QLabel()
        self._skipped_button = QPushButton()
        self._skipped_button.setFlat(True)
        self._skipped_button.setVisible(False)
        self._skipped_button.clicked.connect(self._show_skipped)
        self._trash_button = QPushButton("Move to Recycle Bin")
        self._trash_button.setMinimumHeight(36)
        self._trash_button.clicked.connect(self._move_to_recycle_bin)
        bottom = QHBoxLayout()
        bottom.addWidget(self._totals, 1)
        bottom.addWidget(self._skipped_button)
        bottom.addWidget(self._trash_button)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(top)
        layout.addWidget(self._progress)
        layout.addWidget(splitter, 1)
        layout.addLayout(bottom)
        self.setCentralWidget(central)
        self._update_totals()

    # --- folders and scanning ---------------------------------------------

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder to scan")
        if folder and not self._folders.findItems(folder, Qt.MatchFlag.MatchExactly):
            self._folders.addItem(folder)

    def _scan_or_cancel(self) -> None:
        if self._worker:
            self._worker.cancel()
            self._scan_button.setEnabled(False)
            return
        folders = [self._folders.item(row).text() for row in range(self._folders.count())]
        if not folders:
            self._add_folder()
            folders = [self._folders.item(row).text() for row in range(self._folders.count())]
            if not folders:
                return

        self._set_scanning(True)
        worker = ScanWorker(folders, self)
        worker.progress.connect(self._on_progress)
        worker.done.connect(self._on_scan_done)
        worker.cancelled.connect(lambda: self.statusBar().showMessage("Scan cancelled.", 5000))
        worker.failed.connect(lambda message: QMessageBox.critical(self, "Scan failed", message))
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker
        worker.start()

    def _set_scanning(self, scanning: bool) -> None:
        self._scan_button.setText("Cancel" if scanning else "Scan")
        self._scan_button.setEnabled(True)
        self._progress.setVisible(scanning)
        self._progress.setRange(0, 0)
        self._slider.setEnabled(not scanning)
        for widget in self._folder_controls:
            widget.setEnabled(not scanning)
        self._update_totals()

    def _on_progress(self, phase: str, done: int, total: int) -> None:
        if total:
            self._progress.setRange(0, total)
            self._progress.setValue(done)
            self._progress.setFormat(f"Hashing {done} / {total}")
        else:
            self._progress.setRange(0, 0)
            self.statusBar().showMessage(f"Found {done} images…")

    def _on_scan_done(self, result: ScanResult) -> None:
        self._images = result.images
        self._skipped = result.skipped
        self._overrides.clear()
        self._skipped_button.setText(f"{plural(len(self._skipped), 'file')} skipped")
        self._skipped_button.setVisible(bool(self._skipped))
        self._regroup()
        self.statusBar().showMessage(f"Scanned {plural(len(self._images), 'image')}, found {plural(len(self._groups), 'duplicate group')}.")

    def _on_worker_finished(self) -> None:
        self._worker.deleteLater()
        self._worker = None
        self._set_scanning(False)

    def _show_skipped(self) -> None:
        box = QMessageBox(QMessageBox.Icon.Information, "Skipped files", f"{plural(len(self._skipped), 'file')} could not be read and left out of the scan.", parent=self)
        box.setDetailedText("\n".join(f"{path}\n    {reason}" for path, reason in self._skipped))
        box.exec()

    # --- grouping and review ----------------------------------------------

    def _show_threshold(self, value: int) -> None:
        self._slider_label.setText(f"Similarity tolerance: {value}")

    def _on_threshold_changed(self, value: int) -> None:
        self._show_threshold(value)
        if self._images:
            self._regroup()

    def _regroup(self) -> None:
        """Rebuild groups from the hashes in memory and re-apply the user's choices."""
        current = self._current_group()
        anchor = current.keeper.file.path if current else None

        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._groups = build_groups(self._images, self._slider.value())
        finally:
            QGuiApplication.restoreOverrideCursor()

        self._remove = set()
        select = 0
        for row, group in enumerate(self._groups):
            paths = [image.file.path for image in group.images]
            marked = {path for index, path in enumerate(paths) if self._overrides.get(path, index > 0)}
            if len(marked) == len(paths):  # earlier choices must never empty a regrouped set
                marked.discard(paths[0])
            self._remove |= marked
            if anchor in paths:
                select = row

        self._group_list.set_groups(self._groups)
        if self._groups:
            self._group_list.setCurrentRow(select)
        else:
            self._group_view.show_group(None, ())
        self._update_totals()

    def _current_group(self) -> DuplicateGroup | None:
        row = self._group_list.currentRow()
        return self._groups[row] if 0 <= row < len(self._groups) else None

    def _show_current_group(self) -> None:
        self._group_view.show_group(self._current_group(), self._remove)

    def _on_remove_toggled(self, path: Path, removed: bool) -> None:
        group = self._current_group()
        if group is None:
            return
        if removed and all(image.file.path in self._remove or image.file.path == path for image in group.images):
            self._group_view.set_removed(path, False)
            self.statusBar().showMessage("At least one file in each group has to be kept.", 5000)
            return
        self._overrides[path] = removed
        (self._remove.add if removed else self._remove.discard)(path)
        self._group_view.set_removed(path, removed)
        self._update_totals()

    def _keep_all_in_current_group(self) -> None:
        group = self._current_group()
        if group is None:
            return
        for image in group.images:
            self._overrides[image.file.path] = False
            self._remove.discard(image.file.path)
            self._group_view.set_removed(image.file.path, False)
        self._update_totals()

    def _removal_size(self) -> int:
        return sum(image.file.size for group in self._groups for image in group.images if image.file.path in self._remove)

    def _update_totals(self) -> None:
        count = len(self._remove)
        if not self._groups:
            self._totals.setText("No duplicate groups." if self._images else "")
        else:
            self._totals.setText(f"{plural(len(self._groups), 'group')} · {plural(count, 'file')} marked for removal ({human_size(self._removal_size())})")
        self._trash_button.setEnabled(count > 0 and self._worker is None)

    # --- removal ----------------------------------------------------------

    def _move_to_recycle_bin(self) -> None:
        count = len(self._remove)
        answer = QMessageBox.question(
            self,
            "Move to Recycle Bin",
            f"Move {plural(count, 'file')} ({human_size(self._removal_size())}) to the Recycle Bin?\n\nYou can restore them from the Recycle Bin afterwards.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = remove_from_groups(self._groups, self._remove)
        finally:
            QGuiApplication.restoreOverrideCursor()

        # Drop everything we tried to remove: failures are gone, changed, or need a rescan.
        attempted = set(result.trashed) | {path for path, _reason in result.failed}
        self._images = [image for image in self._images if image.file.path not in attempted]
        for path in attempted:
            self._overrides.pop(path, None)
        self._loader.forget(attempted)
        self._regroup()

        self.statusBar().showMessage(f"Moved {plural(len(result.trashed), 'file')} to the Recycle Bin.")
        if result.failed:
            box = QMessageBox(
                QMessageBox.Icon.Warning,
                "Some files were not moved",
                f"{len(result.trashed)} files were moved to the Recycle Bin.\n{len(result.failed)} files were left where they are.",
                parent=self,
            )
            box.setDetailedText("\n".join(f"{path}\n    {reason}" for path, reason in result.failed))
            box.exec()

    def closeEvent(self, event) -> None:
        if self._worker:
            self._worker.cancel()
            self._worker.wait()
        self._loader.shutdown()
        super().closeEvent(event)
