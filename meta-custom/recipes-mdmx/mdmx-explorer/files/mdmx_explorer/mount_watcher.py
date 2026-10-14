"""Watch /proc/self/mountinfo for changes.

inotify does not fire on procfs; the documented way to notice mount-table
changes is poll(fd, POLLERR | POLLPRI). Qt exposes this through
QSocketNotifier(fd, Exception).
"""

from __future__ import annotations

import os

from PySide6.QtCore import QObject, QSocketNotifier, Signal


_MOUNTINFO = "/proc/self/mountinfo"


def _parse_mountpoints() -> set[str]:
    """Return the set of currently-mounted mountpoints."""
    try:
        with open(_MOUNTINFO, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return set()
    paths: set[str] = set()
    for line in lines:
        # Format: see proc(5) mountinfo section. Field 5 is the mount point,
        # with octal-escaped special chars.
        fields = line.split()
        if len(fields) < 5:
            continue
        paths.add(_octal_unescape(fields[4]))
    return paths


def _octal_unescape(s: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 3 < len(s) and s[i + 1 : i + 4].isdigit():
            out.append(chr(int(s[i + 1 : i + 4], 8)))
            i += 4
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


class MountWatcher(QObject):
    """Emits mountAdded/mountRemoved whenever /proc/self/mountinfo changes."""

    mountAdded = Signal(str)
    mountRemoved = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._fd = os.open(_MOUNTINFO, os.O_RDONLY)
        self._known = _parse_mountpoints()
        self._notifier = QSocketNotifier(self._fd, QSocketNotifier.Exception, self)
        self._notifier.activated.connect(self._on_change)

    def current(self) -> set[str]:
        return set(self._known)

    def _on_change(self) -> None:
        now = _parse_mountpoints()
        for added in now - self._known:
            self.mountAdded.emit(added)
        for removed in self._known - now:
            self.mountRemoved.emit(removed)
        self._known = now

    def close(self) -> None:
        self._notifier.setEnabled(False)
        try:
            os.close(self._fd)
        except OSError:
            pass
