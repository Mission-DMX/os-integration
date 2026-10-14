"""Generic file-browser tab used for $HOME and each /run/media/* mount.

Thin wrapper around QFileSystemModel + QTreeView. Double-clicking a file
emits `fileActivated(path)`; MainWindow decides what application to hand
it to (editor for .show, docviewer for docs, xdg-open otherwise).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDir, QModelIndex, Qt, Signal
from PySide6.QtWidgets import (
    QFileSystemModel,
    QHBoxLayout,
    QPushButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)


class FileBrowserTab(QWidget):
    """fileActivated(str) emits on double-click of a non-directory row."""

    fileActivated = Signal(str)
    unmountRequested = Signal(str)

    def __init__(
        self,
        root: str,
        show_unmount_button: bool = False,
        show_hidden: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._root = root

        self._model = QFileSystemModel(self)
        self._model.setRootPath(root)
        self._show_hidden = show_hidden
        self._apply_filter()

        self._view = QTreeView(self)
        self._view.setModel(self._model)
        self._view.setRootIndex(self._model.index(root))
        self._view.setSortingEnabled(True)
        self._view.sortByColumn(0, Qt.AscendingOrder)
        for col in (2, 3):
            self._view.hideColumn(col)
        self._view.doubleClicked.connect(self._on_double_clicked)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)

        if show_unmount_button:
            bar = QHBoxLayout()
            bar.addStretch(1)
            btn = QPushButton("Unmount", self)
            btn.clicked.connect(lambda: self.unmountRequested.emit(self._root))
            bar.addWidget(btn)
            layout.addLayout(bar)

    def set_show_hidden(self, value: bool) -> None:
        if value == self._show_hidden:
            return
        self._show_hidden = value
        self._apply_filter()

    def _apply_filter(self) -> None:
        flags = QDir.AllEntries | QDir.NoDotAndDotDot
        if self._show_hidden:
            flags |= QDir.Hidden
        self._model.setFilter(flags)

    def root(self) -> str:
        return self._root

    def _on_double_clicked(self, index: QModelIndex) -> None:
        if self._model.isDir(index):
            return
        self.fileActivated.emit(self._model.filePath(index))
