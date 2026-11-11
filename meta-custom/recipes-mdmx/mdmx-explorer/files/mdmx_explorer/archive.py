"""Archive creation and extraction via multi-core CLI tools.

Everything runs through QProcess so the Qt event loop stays responsive
and we reuse the same async pattern as the mount code. The heavy work
lives in 7z / tar / pigz / xz, which already saturate all cores when
given the right flags (``-mmt=on`` for p7zip, ``pigz``, ``xz -T0``).
"""

from __future__ import annotations

import os
import re
import subprocess
from collections import deque
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable

from PySide6.QtCore import QObject, QProcess, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ArchiveFormat(Enum):
    ZIP = "zip"
    SEVENZ = "7z"
    TAR = "tar"
    TAR_GZ = "tar.gz"
    TAR_XZ = "tar.xz"
    TAR_BZ2 = "tar.bz2"   # extract-only


# Extension lookup — compound suffixes first so .tar.gz wins over .gz.
_COMPOUND_EXT: list[tuple[str, ArchiveFormat]] = [
    (".tar.gz",  ArchiveFormat.TAR_GZ),
    (".tgz",     ArchiveFormat.TAR_GZ),
    (".tar.xz",  ArchiveFormat.TAR_XZ),
    (".txz",     ArchiveFormat.TAR_XZ),
    (".tar.bz2", ArchiveFormat.TAR_BZ2),
    (".tbz2",    ArchiveFormat.TAR_BZ2),
    (".tbz",     ArchiveFormat.TAR_BZ2),
    (".tar",     ArchiveFormat.TAR),
    (".zip",     ArchiveFormat.ZIP),
    (".7z",      ArchiveFormat.SEVENZ),
]

DEFAULT_EXTENSION: dict[ArchiveFormat, str] = {
    ArchiveFormat.ZIP:     ".zip",
    ArchiveFormat.SEVENZ:  ".7z",
    ArchiveFormat.TAR:     ".tar",
    ArchiveFormat.TAR_GZ:  ".tar.gz",
    ArchiveFormat.TAR_XZ:  ".tar.xz",
    ArchiveFormat.TAR_BZ2: ".tar.bz2",
}

# Display order for the create-dialog combo box.
CREATE_FORMAT_LABELS: list[tuple[ArchiveFormat, str]] = [
    (ArchiveFormat.ZIP,    "ZIP (.zip)"),
    (ArchiveFormat.SEVENZ, "7-Zip (.7z)"),
    (ArchiveFormat.TAR,    "TAR, uncompressed (.tar)"),
    (ArchiveFormat.TAR_GZ, "TAR + gzip (.tar.gz)"),
    (ArchiveFormat.TAR_XZ, "TAR + xz (.tar.xz)"),
]

SUPPORTED_CREATE: tuple[ArchiveFormat, ...] = tuple(
    fmt for fmt, _ in CREATE_FORMAT_LABELS
)

# Formats that support password-based encryption via p7zip.
_ENCRYPTABLE = {ArchiveFormat.ZIP, ArchiveFormat.SEVENZ}


# -------------------------------------------------------------- detection ---

def detect_format(path: Path) -> ArchiveFormat | None:
    """Detect an archive format by compound extension, then magic bytes."""
    name = path.name.lower()
    for ext, fmt in _COMPOUND_EXT:
        if name.endswith(ext):
            return fmt
    try:
        with path.open("rb") as fh:
            head = fh.read(265)
    except OSError:
        return None
    if head.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return ArchiveFormat.ZIP
    if head.startswith(b"7z\xbc\xaf\x27\x1c"):
        return ArchiveFormat.SEVENZ
    if head.startswith(b"\xfd7zXZ\x00"):
        # A standalone .xz is almost always a tarball in this workflow.
        return ArchiveFormat.TAR_XZ
    if head.startswith(b"\x1f\x8b"):
        return ArchiveFormat.TAR_GZ
    if head.startswith(b"BZh"):
        return ArchiveFormat.TAR_BZ2
    if len(head) >= 265 and head[257:262] == b"ustar":
        return ArchiveFormat.TAR
    return None


def strip_archive_suffix(name: str) -> str:
    """Strip a recognised compound archive suffix, preserving the rest."""
    lower = name.lower()
    for ext, _ in _COMPOUND_EXT:
        if lower.endswith(ext):
            return name[: -len(ext)]
    return name


# ------------------------------------------------- path-traversal safety ---

def has_traversal(members: Iterable[str]) -> list[str]:
    """Return archive members whose path would escape the destination."""
    bad: list[str] = []
    for m in members:
        p = m.replace("\\", "/").strip()
        if not p:
            continue
        if p.startswith("/") or (len(p) >= 2 and p[1] == ":"):
            bad.append(m)
            continue
        if any(part == ".." for part in p.split("/")):
            bad.append(m)
    return bad


# -------------------------------------------------------- list / members ---

def build_list_command(
    fmt: ArchiveFormat,
    archive: Path,
    password: str | None = None,
) -> tuple[str, list[str]]:
    if fmt in (ArchiveFormat.ZIP, ArchiveFormat.SEVENZ):
        # "-slt" emits reliable `Path = foo/bar` lines that are
        # locale-independent and easy to parse.
        args = ["l", "-ba", "-slt", f"-p{password or ''}", "--", str(archive)]
        return "7z", args
    # GNU tar auto-detects gz/xz/bz2 on read.
    return "tar", ["-tf", str(archive)]


def parse_members(stdout: bytes, fmt: ArchiveFormat) -> list[str]:
    text = stdout.decode("utf-8", "replace")
    members: list[str] = []
    if fmt in (ArchiveFormat.ZIP, ArchiveFormat.SEVENZ):
        for line in text.splitlines():
            if line.startswith("Path = "):
                members.append(line[len("Path = "):])
    else:
        for line in text.splitlines():
            if line:
                members.append(line)
    return members


def list_members_sync(
    fmt: ArchiveFormat,
    archive: Path,
    password: str | None = None,
    timeout: float = 60.0,
) -> tuple[bool, list[str], str]:
    """Blocking member-list. Returns (ok, members, error_message).

    Used during the pre-extraction safety scan. For most archives this
    is fast; worst case (a many-GB .tar.xz) it costs decompression of
    the index — bounded by ``timeout``.
    """
    program, args = build_list_command(fmt, archive, password)
    try:
        result = subprocess.run(
            [program, *args],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return (False, [], f"{program} is not installed")
    except subprocess.TimeoutExpired:
        return (False, [], f"Listing timed out after {timeout:.0f} s")
    if result.returncode != 0:
        err = (result.stderr.decode("utf-8", "replace").strip()
               or result.stdout.decode("utf-8", "replace").strip()
               or f"{program} exited with status {result.returncode}")
        return (False, [], err)
    return (True, parse_members(result.stdout, fmt), "")


def looks_encrypted(error_message: str) -> bool:
    """Heuristic: did a 7z failure look like it was caused by encryption?"""
    lo = error_message.lower()
    return any(s in lo for s in (
        "wrong password", "enter password", "encrypted", "data error in encrypted",
    ))


# ----------------------------------------------------- command builders ---

def _level_flag(level: int) -> str:
    # -mx1 fast, -mx5 normal, -mx9 ultra.
    return f"-mx{level}"


def build_create_command(
    fmt: ArchiveFormat,
    archive: Path,
    sources: list[str],
    level: int = 5,
    password: str = "",
) -> tuple[str, list[str]]:
    """Build the subprocess invocation for creating ``archive``.

    ``sources`` are names relative to the job's cwd. We rely on the caller
    setting ``cwd`` on the QProcess (the explorer's handler does this via
    ``base_dir`` derived from the selection's common parent).
    """
    if fmt not in SUPPORTED_CREATE:
        raise ValueError(f"unsupported create format: {fmt}")

    if fmt is ArchiveFormat.ZIP:
        args = ["a", "-tzip", "-mmt=on", _level_flag(level), "-bsp1", "-bb0"]
        if password:
            args.append(f"-p{password}")
        args.extend(["--", str(archive), *sources])
        return "7z", args

    if fmt is ArchiveFormat.SEVENZ:
        args = ["a", "-t7z", "-mmt=on", _level_flag(level), "-bsp1", "-bb0"]
        if password:
            # -mhe=on also encrypts the header (filenames).
            args.extend([f"-p{password}", "-mhe=on"])
        args.extend(["--", str(archive), *sources])
        return "7z", args

    if fmt is ArchiveFormat.TAR:
        return "tar", ["-cf", str(archive), "--", *sources]

    if fmt is ArchiveFormat.TAR_GZ:
        # ``pigz`` is a drop-in, multi-threaded gzip.
        return "tar", ["--use-compress-program=pigz",
                       "-cf", str(archive), "--", *sources]

    if fmt is ArchiveFormat.TAR_XZ:
        # ``xz -T0`` fans out across every available core.
        return "tar", [f"--use-compress-program=xz -T0 -{level}",
                       "-cf", str(archive), "--", *sources]

    raise ValueError(f"unhandled create format: {fmt}")


def build_extract_command(
    fmt: ArchiveFormat,
    archive: Path,
    dest: Path,
    password: str = "",
) -> tuple[str, list[str]]:
    if fmt in (ArchiveFormat.ZIP, ArchiveFormat.SEVENZ):
        # ``-y`` auto-answers "Yes" to overwrite / confirm-extract prompts;
        # ``-p`` is always supplied so 7z never blocks on an interactive
        # password prompt — if the archive turns out to be encrypted and
        # we passed the wrong (empty) password, it'll fail fast with a
        # recognisable error that the caller can re-prompt on.
        args = ["x", "-y", "-bsp1", "-bb0", f"-o{dest}", f"-p{password}",
                "--", str(archive)]
        return "7z", args

    if fmt is ArchiveFormat.TAR:
        return "tar", ["-xf", str(archive), "-C", str(dest)]

    if fmt is ArchiveFormat.TAR_GZ:
        return "tar", ["--use-compress-program=pigz",
                       "-xf", str(archive), "-C", str(dest)]

    if fmt is ArchiveFormat.TAR_XZ:
        return "tar", ["--use-compress-program=xz -T0",
                       "-xf", str(archive), "-C", str(dest)]

    if fmt is ArchiveFormat.TAR_BZ2:
        # No pbzip2 dep — bzip2 is extract-only courtesy. Multi-core here
        # would require pbzip2; not worth another image package.
        return "tar", ["-xjf", str(archive), "-C", str(dest)]

    raise ValueError(f"unhandled extract format: {fmt}")


# ------------------------------------------------------- unique-path pick ---

def unique_path(base: Path) -> Path:
    """Append ``(1)`` / ``(2)`` / … until the path doesn't exist."""
    if not base.exists():
        return base
    # Strip any compound archive extension so "foo.tar.gz" becomes
    # "foo" + ".tar.gz" rather than "foo.tar" + ".gz".
    name = base.name
    stem = strip_archive_suffix(name)
    ext = name[len(stem):]
    parent = base.parent
    i = 1
    while True:
        candidate = parent / f"{stem} ({i}){ext}"
        if not candidate.exists():
            return candidate
        i += 1


# --------------------------------------------------- ArchiveJob (worker) ---

@dataclass
class CreateRequest:
    fmt: ArchiveFormat
    archive_path: Path
    sources: list[str]        # names relative to ``base_dir``
    base_dir: Path            # cwd for the subprocess
    level: int = 5
    password: str = ""


class ArchiveJob(QObject):
    """A single create / extract operation, async on the Qt event loop.

    Progress signals are best-effort: 7z reports a real percentage;
    tar only tells us the current filename (we emit percent = -1 so
    the dialog keeps its indeterminate spinner).
    """

    MODE_CREATE = "create"
    MODE_EXTRACT = "extract"

    progress = Signal(int, str)     # percent (-1 = indeterminate), status
    log = Signal(str)               # verbose line (stdout or stderr)
    finished = Signal(bool, str)    # success, message

    _PCT_RE = re.compile(rb"\s*(\d+)%")

    def __init__(
        self,
        program: str,
        args: list[str],
        cwd: Path,
        *,
        mode: str,
        fmt: ArchiveFormat,
        target_path: Path,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._program = program
        self._args = args
        self._cwd = Path(cwd)
        self._mode = mode
        self._fmt = fmt
        self._target = Path(target_path)

        self._proc = QProcess(self)
        self._proc.setWorkingDirectory(str(self._cwd))
        self._proc.readyReadStandardOutput.connect(self._on_stdout)
        self._proc.readyReadStandardError.connect(self._on_stderr)
        self._proc.errorOccurred.connect(self._on_error)
        self._proc.finished.connect(self._on_finished)

        self._stderr_tail: deque[str] = deque(maxlen=64)
        self._stdout_tail: deque[str] = deque(maxlen=64)
        self._cancelled = False
        self._last_progress = -1
        self._kill_timer: QTimer | None = None
        self._start_failed = False

    def start(self) -> None:
        self._proc.start(self._program, self._args)
        # Signal EOF on stdin: prevents 7z from blocking on an interactive
        # password prompt if we passed the wrong credentials.
        self._proc.closeWriteChannel()

    def cancel(self) -> None:
        if self._cancelled or self._proc.state() == QProcess.NotRunning:
            return
        self._cancelled = True
        self._proc.terminate()
        self._kill_timer = QTimer(self)
        self._kill_timer.setSingleShot(True)
        self._kill_timer.timeout.connect(self._proc.kill)
        self._kill_timer.start(2000)

    def is_running(self) -> bool:
        return self._proc.state() != QProcess.NotRunning

    def mode(self) -> str:
        return self._mode

    def target(self) -> Path:
        return self._target

    def stderr_tail(self) -> str:
        return "".join(self._stderr_tail).strip()

    # --- slots -----------------------------------------------------------

    def _on_stdout(self) -> None:
        data = bytes(self._proc.readAllStandardOutput())
        for raw in data.splitlines():
            line = raw.decode("utf-8", "replace").rstrip("\r")
            self._stdout_tail.append(line + "\n")
            self.log.emit(line)
            m = self._PCT_RE.match(raw.lstrip())
            if m:
                pct = int(m.group(1))
                if pct != self._last_progress:
                    self._last_progress = pct
                    # 7z progress lines look like " 47% 42 - foo/bar".
                    tail = line.split("-", 1)[-1].strip() if " - " in line else ""
                    self.progress.emit(pct, tail)

    def _on_stderr(self) -> None:
        data = bytes(self._proc.readAllStandardError())
        for raw in data.splitlines():
            line = raw.decode("utf-8", "replace").rstrip("\r")
            self._stderr_tail.append(line + "\n")
            self.log.emit(line)
            # ``tar`` with -v emits filenames on stderr; use as status
            # for the indeterminate progress label.
            if self._program == "tar" and line:
                self.progress.emit(-1, line)

    def _on_error(self, err: QProcess.ProcessError) -> None:
        if err == QProcess.FailedToStart:
            self._start_failed = True
            self.finished.emit(
                False,
                f"Could not start {self._program}: {self._proc.errorString()}",
            )

    def _on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        if self._start_failed:
            return  # already reported via _on_error
        if self._kill_timer is not None:
            self._kill_timer.stop()
        if self._cancelled:
            if self._mode == self.MODE_CREATE:
                try:
                    self._target.unlink()
                except OSError:
                    pass
            self.finished.emit(False, "Cancelled")
            return
        if exit_status == QProcess.CrashExit or exit_code != 0:
            msg = (self.stderr_tail()
                   or "".join(self._stdout_tail).strip()
                   or f"{self._program} exited with status {exit_code}")
            self.finished.emit(False, msg)
            return
        self.finished.emit(True, "")


# ---------------------------------------------------- create-dialog ------

class CreateArchiveDialog(QDialog):
    """Pick format, destination, compression level and (optional) password."""

    LEVEL_LABELS: list[tuple[str, int]] = [
        ("Fast", 1),
        ("Normal", 5),
        ("Maximum", 9),
    ]

    def __init__(
        self,
        sources: list[str],
        base_dir: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create archive")
        self._sources = sources
        self._base_dir = Path(base_dir)
        self._request: CreateRequest | None = None

        form = QFormLayout(self)

        self._format = QComboBox(self)
        for _, label in CREATE_FORMAT_LABELS:
            self._format.addItem(label)
        self._format.currentIndexChanged.connect(self._on_format_changed)
        form.addRow(QLabel("Format:"), self._format)

        self._name = QLineEdit(self._default_stem(), self)
        form.addRow(QLabel("Archive name:"), self._name)

        dest_row = QHBoxLayout()
        self._dest = QLineEdit(str(self._base_dir), self)
        browse = QPushButton("Browse…", self)
        browse.clicked.connect(self._pick_dest)
        dest_row.addWidget(self._dest, 1)
        dest_row.addWidget(browse)
        form.addRow(QLabel("Destination folder:"), dest_row)

        self._level = QComboBox(self)
        for label, _ in self.LEVEL_LABELS:
            self._level.addItem(label)
        self._level.setCurrentIndex(1)
        form.addRow(QLabel("Compression level:"), self._level)

        self._password = QLineEdit(self)
        self._password.setEchoMode(QLineEdit.Password)
        self._password.setPlaceholderText("optional (ZIP / 7z only)")
        form.addRow(QLabel("Password:"), self._password)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self,
        )
        buttons.accepted.connect(self._try_accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        self._on_format_changed()

    def _default_stem(self) -> str:
        if len(self._sources) == 1:
            s = Path(self._sources[0]).name
            stem = strip_archive_suffix(s)
            # For a directory, ``stem`` already is the name.
            return stem or s or "archive"
        if self._base_dir.name:
            return self._base_dir.name
        return "archive"

    def _current_format(self) -> ArchiveFormat:
        return CREATE_FORMAT_LABELS[self._format.currentIndex()][0]

    def _on_format_changed(self) -> None:
        fmt = self._current_format()
        self._level.setEnabled(fmt is not ArchiveFormat.TAR)
        self._password.setEnabled(fmt in _ENCRYPTABLE)
        if fmt not in _ENCRYPTABLE:
            self._password.clear()

    def _pick_dest(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Destination folder", self._dest.text(),
        )
        if chosen:
            self._dest.setText(chosen)

    def _try_accept(self) -> None:
        name = self._name.text().strip()
        dest_text = self._dest.text().strip()
        if not name:
            QMessageBox.warning(self, "Missing name",
                                "Please enter an archive name.")
            return
        dest = Path(dest_text).expanduser()
        if not dest.is_dir():
            QMessageBox.warning(self, "Invalid folder",
                                f"Destination folder does not exist:\n{dest}")
            return
        fmt = self._current_format()
        ext = DEFAULT_EXTENSION[fmt]
        # If the user typed the extension themselves, honour it; otherwise
        # append the one the format dictates.
        if not name.lower().endswith(ext):
            name = strip_archive_suffix(name) + ext

        _, level = self.LEVEL_LABELS[self._level.currentIndex()]

        self._request = CreateRequest(
            fmt=fmt,
            archive_path=dest / name,
            sources=list(self._sources),
            base_dir=self._base_dir,
            level=level,
            password=self._password.text(),
        )
        self.accept()

    def request(self) -> CreateRequest:
        assert self._request is not None, "accept() has not fired"
        return self._request


# ------------------------------------------------ progress-dialog -------

class ArchiveProgressDialog(QDialog):
    """Modeless progress dialog bound to one ArchiveJob."""

    def __init__(
        self,
        title: str,
        job: ArchiveJob,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(False)
        self.resize(520, 160)
        self._job = job
        self._details_shown = False
        self._finished = False

        layout = QVBoxLayout(self)
        self._label = QLabel("Starting…", self)
        self._label.setWordWrap(True)
        layout.addWidget(self._label)

        self._bar = QProgressBar(self)
        self._bar.setRange(0, 0)  # indeterminate until a percentage arrives
        layout.addWidget(self._bar)

        row = QHBoxLayout()
        self._details_btn = QPushButton("Details…", self)
        self._details_btn.setCheckable(True)
        self._details_btn.toggled.connect(self._on_details_toggled)
        row.addWidget(self._details_btn)
        row.addStretch(1)
        self._action_btn = QPushButton("Cancel", self)
        self._action_btn.clicked.connect(self._on_action)
        row.addWidget(self._action_btn)
        layout.addLayout(row)

        self._log = QPlainTextEdit(self)
        self._log.setReadOnly(True)
        self._log.setFont(QFont("monospace"))
        self._log.setMaximumBlockCount(2000)
        self._log.hide()
        layout.addWidget(self._log, 1)

        job.progress.connect(self._on_progress)
        job.log.connect(self._on_log)
        job.finished.connect(self._on_job_finished)

    def _on_progress(self, pct: int, status: str) -> None:
        if pct >= 0:
            if self._bar.maximum() == 0:
                self._bar.setRange(0, 100)
            self._bar.setValue(pct)
        if status:
            self._label.setText(status)

    def _on_log(self, line: str) -> None:
        self._log.appendPlainText(line)

    def _on_action(self) -> None:
        if self._finished:
            self.accept()
            return
        self._action_btn.setEnabled(False)
        self._label.setText("Cancelling…")
        self._job.cancel()

    def _on_details_toggled(self, shown: bool) -> None:
        self._details_shown = shown
        self._log.setVisible(shown)
        if shown and self.height() < 340:
            self.resize(self.width(), 340)

    def _on_job_finished(self, ok: bool, message: str) -> None:
        self._finished = True
        self._action_btn.setEnabled(True)
        self._action_btn.setText("Close")
        if ok:
            self._bar.setRange(0, 100)
            self._bar.setValue(100)
            self._label.setText("Finished.")
            if not self._details_shown:
                # Autoclose briefly so the operator doesn't have to dismiss
                # every successful job.
                QTimer.singleShot(1200, self.accept)
        else:
            self._bar.setRange(0, 100)
            self._bar.setValue(0)
            # Show the last meaningful stderr line, not the whole tail.
            summary = message.splitlines()[-1] if message else "unknown error"
            self._label.setText(f"Failed: {summary}")
            if not self._details_shown:
                self._details_btn.setChecked(True)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # Avoid orphan child processes if the user closes the dialog.
        self._job.cancel()
        super().closeEvent(event)
