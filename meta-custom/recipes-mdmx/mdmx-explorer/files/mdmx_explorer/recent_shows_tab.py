"""Recent-shows tab: lists ~/.local/share/missionDMX/recently_used.list.

Each row renders filename + show_name + a 3-line notes preview, lifted
from the show file's root attributes via show_metadata.extract (streaming
— does not open the body of the XML).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QAbstractListModel,
    QFileSystemWatcher,
    QModelIndex,
    QObject,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QFont, QPainter
from PySide6.QtWidgets import (
    QListView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from .show_metadata import MetadataCache, ShowMetadata


_RECENT_FILE = Path.home() / ".local" / "share" / "missionDMX" / "recently_used.list"


class _RecentShowsModel(QAbstractListModel):
    PathRole = Qt.UserRole + 1
    MetadataRole = Qt.UserRole + 2

    def __init__(self, cache: MetadataCache, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cache = cache
        self._entries: list[tuple[str, ShowMetadata | None]] = []

    def reload(self, path: Path = _RECENT_FILE) -> None:
        self.beginResetModel()
        self._entries = []
        try:
            lines = path.read_text("utf-8").splitlines()
        except OSError:
            lines = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            self._entries.append((line, self._cache.get(line)))
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._entries)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        path, meta = self._entries[index.row()]
        if role == Qt.DisplayRole:
            return path
        if role == self.PathRole:
            return path
        if role == self.MetadataRole:
            return meta
        return None


class _ShowCardDelegate(QStyledItemDelegate):
    _PADDING = 8
    _NOTE_LINES = 3

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        fm = option.fontMetrics
        line = fm.height()
        return QSize(option.rect.width(),
                     self._PADDING * 2 + line * (2 + self._NOTE_LINES))

    def paint(self, painter: QPainter, option: QStyleOptionViewItem,
              index: QModelIndex) -> None:
        painter.save()
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
            painter.setPen(option.palette.highlightedText().color())
        else:
            painter.setPen(option.palette.text().color())

        path = index.data(_RecentShowsModel.PathRole) or ""
        meta: ShowMetadata | None = index.data(_RecentShowsModel.MetadataRole)
        fm = option.fontMetrics
        rect: QRect = option.rect.adjusted(self._PADDING, self._PADDING,
                                           -self._PADDING, -self._PADDING)
        line_h = fm.height()
        x, y = rect.x(), rect.y()

        bold = QFont(option.font)
        bold.setBold(True)
        painter.setFont(bold)
        heading = meta.show_name if (meta and meta.show_name) else Path(path).name
        painter.drawText(x, y + fm.ascent(), heading)

        painter.setFont(option.font)
        y += line_h
        subtle = option.palette.windowText().color()
        subtle.setAlphaF(0.75)
        painter.setPen(subtle)
        painter.drawText(x, y + fm.ascent(), path)

        if meta and meta.notes:
            painter.setPen(option.palette.text().color())
            for i, note_line in enumerate(meta.notes.splitlines()[: self._NOTE_LINES]):
                y += line_h
                painter.drawText(x, y + fm.ascent(), note_line)
        painter.restore()


class RecentShowsTab(QWidget):
    """Signal: showActivated(str) — emitted on double-click of a row."""

    showActivated = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cache = MetadataCache()
        self._model = _RecentShowsModel(self._cache, self)
        self._view = QListView(self)
        self._view.setModel(self._model)
        self._view.setItemDelegate(_ShowCardDelegate(self))
        self._view.setUniformItemSizes(False)
        self._view.doubleClicked.connect(self._on_double_clicked)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)

        self._watcher = QFileSystemWatcher([str(_RECENT_FILE)], self) \
            if _RECENT_FILE.exists() else QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(lambda _p: self._model.reload())
        self._model.reload()

    def _on_double_clicked(self, index: QModelIndex) -> None:
        path = index.data(_RecentShowsModel.PathRole)
        if path:
            self.showActivated.emit(path)
