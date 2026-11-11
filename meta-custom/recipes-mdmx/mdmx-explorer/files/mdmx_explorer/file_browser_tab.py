"""Generic file-browser tab used for $HOME and each /run/media/* mount.

Thin wrapper around QFileSystemModel + QTreeView. Double-clicking a file
emits `fileActivated(path)`; MainWindow decides what application to hand
it to (editor for .show, docviewer for docs, xdg-open otherwise).

Right-clicking opens a context menu whose shape depends on the selection:
archive files get Extract actions, everything else gets Create archive.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QDir, QModelIndex, QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileSystemModel,
    QHBoxLayout,
    QMenu,
    QPushButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from .archive import detect_format


class FileBrowserTab(QWidget):
    """fileActivated(str) emits on double-click of a non-directory row."""

    fileActivated = Signal(str)
    unmountRequested = Signal(str)
    # (sources, base_dir) — sources are absolute, base_dir is their common parent.
    createArchiveRequested = Signal(list, str)
    # (archive_path, dest_dir, is_extract_here). dest_dir is "" when
    # is_extract_here is False — the handler asks the user to pick one.
    extractArchiveRequested = Signal(str, str, bool)

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
        self._view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._view.doubleClicked.connect(self._on_double_clicked)
        self._view.setContextMenuPolicy(Qt.CustomContextMenu)
        self._view.customContextMenuRequested.connect(self._on_context_menu)

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

    # -- context menu ----------------------------------------------------

    def _selected_paths(self) -> list[str]:
        """Selected rows' absolute paths (column 0 only, de-duplicated)."""
        indexes = self._view.selectionModel().selectedRows(0)
        seen: set[str] = set()
        out: list[str] = []
        for idx in indexes:
            p = self._model.filePath(idx)
            if p and p not in seen:
                seen.add(p)
                out.append(p)
        return out

    def _on_context_menu(self, point: QPoint) -> None:
        clicked = self._view.indexAt(point)
        # If the user right-clicked outside their current selection,
        # treat it as a single-item action on the clicked row.
        selected = self._selected_paths()
        if clicked.isValid():
            clicked_path = self._model.filePath(clicked)
            if clicked_path not in selected:
                selected = [clicked_path]
        elif not selected:
            selected = []

        menu = QMenu(self._view)

        if not selected:
            # Empty-area click: offer to archive the folder being viewed.
            folder = self._current_folder()
            act = menu.addAction("Create archive from this folder…")
            act.triggered.connect(
                lambda: self.createArchiveRequested.emit([folder], folder)
            )
        elif len(selected) == 1:
            path = selected[0]
            is_dir = os.path.isdir(path)
            fmt = None if is_dir else detect_format(Path(path))

            open_act = menu.addAction("Open")
            open_act.triggered.connect(lambda: self.fileActivated.emit(path))
            if is_dir:
                # Directories are "opened" by expanding them in the tree —
                # fileActivated only fires for files, so grey this out
                # instead of silently doing nothing.
                open_act.setEnabled(False)

            if fmt is not None:
                here_act = menu.addAction("Extract here")
                here_act.triggered.connect(
                    lambda: self.extractArchiveRequested.emit(path, "", True)
                )
                to_act = menu.addAction("Extract to…")
                to_act.triggered.connect(
                    lambda: self.extractArchiveRequested.emit(path, "", False)
                )

            menu.addSeparator()
            base = os.path.dirname(path) or self._current_folder()
            create_act = menu.addAction("Create archive from…")
            create_act.triggered.connect(
                lambda: self.createArchiveRequested.emit([path], base)
            )
        else:
            base = os.path.commonpath(selected) or self._current_folder()
            # commonpath can return a file path if two selections have the
            # same name in the same directory; dirname is the safe fallback.
            if not os.path.isdir(base):
                base = os.path.dirname(base)
            n = len(selected)
            act = menu.addAction(f"Create archive from {n} items…")
            act.triggered.connect(
                lambda: self.createArchiveRequested.emit(list(selected), base)
            )

        menu.exec(self._view.viewport().mapToGlobal(point))

    def _current_folder(self) -> str:
        """Absolute path of the folder currently shown as the tree's root."""
        return self._model.filePath(self._view.rootIndex()) or self._root
