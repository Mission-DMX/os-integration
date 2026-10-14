"""Dialogs for adding SMB / NFS / sshfs mounts, plus the pkexec invocation.

Mountpoints always land under /run/media/net.<name>/ so the main-window
mount-watcher picks them up through the same codepath as USB tabs.
sshfs runs as the user via FUSE; CIFS/NFS go through the privileged
/usr/libexec/mdmx-explorer-mount helper via pkexec.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QProcess, QObject
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QWidget,
)


NET_MOUNT_ROOT = Path("/run/media")
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass
class MountRequest:
    fstype: str          # "cifs" | "nfs4" | "fuse.sshfs"
    source: str          # //host/share | host:/export | user@host:/path
    name: str            # becomes /run/media/net.<name>/
    options: str = ""    # comma-separated, no shell metachars

    @property
    def mountpoint(self) -> Path:
        return NET_MOUNT_ROOT / f"net.{self.name}"


class _ProtocolDialog(QDialog):
    FSTYPE = ""
    SOURCE_LABEL = "Source"
    SOURCE_PLACEHOLDER = ""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Mount {self.FSTYPE} share")
        form = QFormLayout(self)

        self._source = QLineEdit(self)
        self._source.setPlaceholderText(self.SOURCE_PLACEHOLDER)
        form.addRow(QLabel(self.SOURCE_LABEL + ":"), self._source)

        self._name = QLineEdit(self)
        self._name.setPlaceholderText("letters, digits, _ and - only")
        form.addRow(QLabel("Mount name:"), self._name)

        self._add_fields(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self
        )
        buttons.accepted.connect(self._try_accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _add_fields(self, form: QFormLayout) -> None:
        pass

    def _build_options(self) -> str:
        return ""

    def _try_accept(self) -> None:
        name = self._name.text().strip()
        source = self._source.text().strip()
        if not source or not _NAME_RE.match(name):
            QMessageBox.warning(self, "Invalid input",
                                "Source and mount name are required; "
                                "name may only contain [A-Za-z0-9_-].")
            return
        self._request = MountRequest(
            fstype=self.FSTYPE,
            source=source,
            name=name,
            options=self._build_options(),
        )
        self.accept()

    def request(self) -> MountRequest:
        return self._request


class SmbDialog(_ProtocolDialog):
    FSTYPE = "cifs"
    SOURCE_LABEL = "Server/share"
    SOURCE_PLACEHOLDER = "//host/share"

    def _add_fields(self, form: QFormLayout) -> None:
        self._user = QLineEdit(self)
        form.addRow(QLabel("Username:"), self._user)
        self._password = QLineEdit(self)
        self._password.setEchoMode(QLineEdit.Password)
        form.addRow(QLabel("Password:"), self._password)
        self._workgroup = QLineEdit(self)
        self._workgroup.setPlaceholderText("optional")
        form.addRow(QLabel("Workgroup:"), self._workgroup)

    def _build_options(self) -> str:
        parts = [f"uid={os.getuid()}", f"gid={os.getgid()}", "iocharset=utf8"]
        if u := self._user.text().strip():
            parts.append(f"username={u}")
        if p := self._password.text():
            parts.append(f"password={p}")
        if w := self._workgroup.text().strip():
            parts.append(f"domain={w}")
        return ",".join(parts)


class NfsDialog(_ProtocolDialog):
    FSTYPE = "nfs4"
    SOURCE_LABEL = "Export"
    SOURCE_PLACEHOLDER = "host:/export/path"

    def _add_fields(self, form: QFormLayout) -> None:
        self._version = QComboBox(self)
        self._version.addItems(["4.2", "4.1", "4", "3"])
        form.addRow(QLabel("NFS version:"), self._version)

    def _build_options(self) -> str:
        return f"vers={self._version.currentText()},soft,timeo=30"


class SshfsDialog(_ProtocolDialog):
    FSTYPE = "fuse.sshfs"
    SOURCE_LABEL = "Remote"
    SOURCE_PLACEHOLDER = "user@host:/remote/path"

    def _add_fields(self, form: QFormLayout) -> None:
        self._key = QLineEdit(self)
        self._key.setPlaceholderText("optional, e.g. ~/.ssh/id_ed25519")
        form.addRow(QLabel("Identity file:"), self._key)

    def _build_options(self) -> str:
        parts = [f"uid={os.getuid()}", f"gid={os.getgid()}",
                 "allow_other", "reconnect"]
        if k := self._key.text().strip():
            parts.append(f"IdentityFile={os.path.expanduser(k)}")
        return ",".join(parts)


class MountRunner(QObject):
    """Execute a MountRequest via sshfs (direct) or pkexec helper (cifs/nfs).

    Non-blocking; completion is signalled by the caller watching the QProcess.
    """

    HELPER = "/usr/libexec/mdmx-explorer-mount"

    def run(self, req: MountRequest, parent: QWidget) -> bool:
        req.mountpoint.mkdir(parents=True, exist_ok=True)

        if req.fstype == "fuse.sshfs":
            # sshfs is user-space; no pkexec needed.
            proc = QProcess(parent)
            opts = f"-o{req.options}" if req.options else ""
            args = [req.source, str(req.mountpoint)] + ([opts] if opts else [])
            proc.start("sshfs", args)
        else:
            proc = QProcess(parent)
            proc.start("pkexec", [
                self.HELPER, req.fstype, req.source,
                str(req.mountpoint), req.options,
            ])

        if not proc.waitForStarted(5000):
            QMessageBox.warning(parent, "Mount failed",
                                f"Could not start mount: {proc.errorString()}")
            return False
        if not proc.waitForFinished(30000):
            proc.kill()
            QMessageBox.warning(parent, "Mount failed",
                                "Mount command timed out after 30 s.")
            return False
        if proc.exitCode() != 0:
            err = bytes(proc.readAllStandardError()).decode("utf-8", "replace")
            QMessageBox.warning(parent, "Mount failed",
                                f"Mount exited with status {proc.exitCode()}:\n{err}")
            return False
        return True

    def unmount(self, mountpoint: str, parent: QWidget) -> None:
        """Try user umount first; fall back to pkexec helper on EPERM."""
        proc = QProcess(parent)
        proc.start("fusermount3", ["-u", mountpoint])
        if proc.waitForFinished(10000) and proc.exitCode() == 0:
            return
        # CIFS/NFS unmount needs root — reuse the helper with a special fstype.
        proc = QProcess(parent)
        proc.start("pkexec", [self.HELPER, "umount", mountpoint, "", ""])
        proc.waitForFinished(10000)
