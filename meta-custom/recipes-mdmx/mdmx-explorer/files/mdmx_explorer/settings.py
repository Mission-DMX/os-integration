"""Operator-facing preferences stored next to the console-lock PIN.

Shares ~/.config/console-settings.ini with console-lock.py (section
[lock]) and mdmx-explorer (section [explorer]) — one file for the
operator's local, non-privileged settings so a factory reset / sync
can treat it as a single unit.
"""

from __future__ import annotations

import configparser
import os
import tempfile
from pathlib import Path


CONFIG_PATH = Path.home() / ".config" / "console-settings.ini"
_SECTION = "explorer"


def _read() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        try:
            cfg.read(CONFIG_PATH)
        except configparser.Error:
            pass
    return cfg


def _write(cfg: configparser.ConfigParser) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replace — matches the pattern used by console-lock.py so
    # mid-write crashes can't leave a truncated INI.
    fd, tmp_path = tempfile.mkstemp(
        prefix=".console-settings.", dir=str(CONFIG_PATH.parent)
    )
    try:
        with os.fdopen(fd, "w") as fh:
            cfg.write(fh)
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, CONFIG_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def get_show_hidden() -> bool:
    cfg = _read()
    return cfg.getboolean(_SECTION, "show_hidden", fallback=False)


def set_show_hidden(value: bool) -> None:
    cfg = _read()
    if not cfg.has_section(_SECTION):
        cfg.add_section(_SECTION)
    cfg.set(_SECTION, "show_hidden", "true" if value else "false")
    _write(cfg)
