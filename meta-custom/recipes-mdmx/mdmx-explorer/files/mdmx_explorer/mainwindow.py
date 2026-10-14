"""QMainWindow with the four kinds of tab wired up to the mount watcher.

Tabs sit on the left (QTabWidget.West) and are icon-only; the full name
sits in each tab's tooltip. System partitions (rootfsA/rootfsB/userdata)
that udev-extraconf might auto-mount under /run/media/ are hidden —
only external thumb drives and user-mounted network shares get a tab.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, QSize, Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QTabWidget,
    QToolBar,
    QToolButton,
    QWidget,
)

from . import settings
from .file_browser_tab import FileBrowserTab
from .icons import icon as md_icon
from .mount_watcher import MountWatcher
from .network_mount import (
    MountRunner,
    NET_MOUNT_ROOT,
    NfsDialog,
    SmbDialog,
    SshfsDialog,
)
from .recent_shows_tab import RecentShowsTab


EDITOR_BIN = "/opt/MissionDMX/editor"
DOCVIEWER_BIN = "/usr/bin/mdmx-docviewer"

_DOC_SUFFIXES = {".md", ".pdf", ".rtf", ".txt"}

# Mount-dir prefixes udev-extraconf uses for the local system partitions
# (names come from the WIC filesystem LABELs defined in mdmx-ab.wks.in).
# Any /run/media/<name>/ whose basename starts with one of these is
# a system mount and must not get a tab.
_SYSTEM_LABEL_PREFIXES = ("rootfsA-", "rootfsB-", "userdata-")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Mission-DMX Explorer")
        self.setWindowIcon(QIcon.fromTheme("mdmx-explorer"))
        self.resize(1024, 640)

        self._tabs = QTabWidget(self)
        self._tabs.setMovable(False)
        self._tabs.setTabsClosable(False)
        self._tabs.setTabPosition(QTabWidget.West)
        self._tabs.setIconSize(QSize(28, 28))
        # Icon-only tabs stacked vertically; the full name is in the
        # tooltip because rotated text on a West-positioned tabbar is
        # unpleasant to read.
        self.setCentralWidget(self._tabs)

        self._runner = MountRunner()
        self._show_hidden = settings.get_show_hidden()
        # Map mountpoint path -> tab widget. Only tracks tabs we created
        # dynamically (removable + network); not Recent / Home.
        self._dynamic_tabs: dict[str, FileBrowserTab] = {}

        self._build_toolbar()
        self._add_recent_tab()
        self._add_home_tab()

        self._watcher = MountWatcher(self)
        self._watcher.mountAdded.connect(self._on_mount_added)
        self._watcher.mountRemoved.connect(self._on_mount_removed)
        for mp in self._watcher.current():
            self._on_mount_added(mp)

    # -- toolbar --------------------------------------------------------

    def _build_toolbar(self) -> None:
        bar = QToolBar("Main", self)
        self.addToolBar(bar)

        menu = QMenu(self)
        menu.addAction("SMB (Windows)…", lambda: self._open_mount_dialog(SmbDialog))
        menu.addAction("NFS…", lambda: self._open_mount_dialog(NfsDialog))
        menu.addAction("sshfs…", lambda: self._open_mount_dialog(SshfsDialog))

        button = QToolButton(self)
        button.setText("Add network share…")
        button.setIcon(md_icon("network"))
        button.setPopupMode(QToolButton.InstantPopup)
        button.setMenu(menu)
        bar.addWidget(button)

        bar.addSeparator()

        self._hidden_action = QAction("Show hidden files", self)
        self._hidden_action.setCheckable(True)
        self._hidden_action.setChecked(self._show_hidden)
        self._hidden_action.toggled.connect(self._on_hidden_toggled)
        bar.addAction(self._hidden_action)

    def _on_hidden_toggled(self, value: bool) -> None:
        self._show_hidden = value
        try:
            settings.set_show_hidden(value)
        except OSError as exc:
            QMessageBox.warning(self, "Settings not saved",
                                f"Could not persist show-hidden preference:\n{exc}")
        for tab in self._all_file_tabs():
            tab.set_show_hidden(value)

    def _all_file_tabs(self) -> list[FileBrowserTab]:
        tabs: list[FileBrowserTab] = []
        for idx in range(self._tabs.count()):
            widget = self._tabs.widget(idx)
            if isinstance(widget, FileBrowserTab):
                tabs.append(widget)
        return tabs

    def _open_mount_dialog(self, cls) -> None:
        dlg = cls(self)
        if dlg.exec() != QDialog.Accepted:
            return
        req = dlg.request()
        self._runner.run(req, self)
        # The mount watcher will emit mountAdded and the tab shows up.

    # -- static tabs ----------------------------------------------------

    def _add_recent_tab(self) -> None:
        tab = RecentShowsTab(self)
        tab.showActivated.connect(self._open_show)
        self._add_tab(tab, md_icon("recent"), "Recent shows")

    def _add_home_tab(self) -> None:
        home = str(Path.home())
        tab = FileBrowserTab(home, show_unmount_button=False,
                             show_hidden=self._show_hidden, parent=self)
        tab.fileActivated.connect(self._open_file)
        self._add_tab(tab, md_icon("home"), "Home")

    def _add_tab(self, widget: QWidget, icon: QIcon, label: str) -> int:
        idx = self._tabs.addTab(widget, icon, "")
        self._tabs.setTabToolTip(idx, label)
        return idx

    # -- dynamic (mount-driven) tabs ------------------------------------

    def _on_mount_added(self, mountpoint: str) -> None:
        if mountpoint in self._dynamic_tabs:
            return
        if not self._should_show_tab(mountpoint):
            return
        name = Path(mountpoint).name
        is_network = name.startswith("net.")

        tab = FileBrowserTab(mountpoint, show_unmount_button=is_network,
                             show_hidden=self._show_hidden, parent=self)
        tab.fileActivated.connect(self._open_file)
        if is_network:
            tab.unmountRequested.connect(
                lambda mp=mountpoint: self._runner.unmount(mp, self))

        label = name[len("net."):] if is_network else name
        icon = md_icon("network" if is_network else "usb")
        self._add_tab(tab, icon, label)
        self._dynamic_tabs[mountpoint] = tab

    def _on_mount_removed(self, mountpoint: str) -> None:
        tab = self._dynamic_tabs.pop(mountpoint, None)
        if tab is None:
            return
        idx = self._tabs.indexOf(tab)
        if idx >= 0:
            self._tabs.removeTab(idx)
        tab.deleteLater()

    def _should_show_tab(self, mountpoint: str) -> bool:
        p = Path(mountpoint)
        if p.parent != NET_MOUNT_ROOT:
            return False
        # Filter the A/B rootfs and userdata partitions — if the firstboot
        # module hasn't bind-mounted them away yet or udev-extraconf races
        # it, they can briefly appear under /run/media/ by their WIC
        # label. The operator never has reason to click into them from
        # the explorer.
        if any(p.name.startswith(prefix) for prefix in _SYSTEM_LABEL_PREFIXES):
            return False
        return True

    # -- opening files --------------------------------------------------

    def _open_show(self, path: str) -> None:
        self._launch(EDITOR_BIN, [path])

    def _open_file(self, path: str) -> None:
        suffix = Path(path).suffix.lower()
        if suffix == ".show":
            self._launch(EDITOR_BIN, [path])
        elif suffix in _DOC_SUFFIXES and shutil.which(DOCVIEWER_BIN):
            self._launch(DOCVIEWER_BIN, [path])
        else:
            self._launch("xdg-open", [path])

    def _launch(self, program: str, args: list[str]) -> None:
        env = QProcessEnvironment()
        # Explicit allowlist — don't leak the explorer's QT_* / PySide6
        # bundle env into the child process. Wayland display + user
        # identity + path are all the child needs.
        for key in ("WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "XDG_SESSION_TYPE",
                    "HOME", "USER", "LOGNAME", "PATH", "LANG", "LC_ALL",
                    "DBUS_SESSION_BUS_ADDRESS"):
            value = os.environ.get(key)
            if value is not None:
                env.insert(key, value)

        pid_holder: list[int] = []
        ok = QProcess.startDetached(program, args, os.environ.get("HOME", "."),
                                    pid_holder)
        if not ok:
            QMessageBox.warning(self, "Launch failed",
                                f"Could not start {program}.")

    # -- shutdown -------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._watcher.close()
        super().closeEvent(event)
