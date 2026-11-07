#!/usr/bin/env python3
"""First-launch configurator for keyboard layout, timezone, and touchscreen mapping.

Autostarted by sway via /etc/sway/config.d/60-console-settings.conf. Reads
~/.config/console-settings.ini for the saved xkb layout/variant, system
timezone, and per-output touchscreen mapping. If complete and the stored
hardware is still present it pushes everything into sway via i3ipc and
exits (the timezone is applied out-of-band — mdmx-tz.sh, sourced from
sway.service and /etc/profile.d, reads this INI and exports TZ, because
the rootfs is RO so timedatectl can't rewrite /etc/localtime). Otherwise
it opens a GTK3 wizard: a
layout dropdown, a timezone dropdown, then a per-output "touch this screen"
calibrator whose device identification is done via evdev (sway's identifier
is <vendor>:<product>:<name> and collapses on duplicate models, see
sway/input/input-manager.c:68-92 — the libinput quirks file written at commit
time rewrites each device's name based on its stable udev ID_PATH so the
daemon's fast path on the next sway start can address each device uniquely).
"""

from __future__ import annotations

import argparse
import configparser
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import i3ipc

CONFIG_PATH = Path.home() / ".config" / "console-settings.ini"
BASE_LST = Path("/usr/share/X11/xkb/rules/base.lst")
QUIRKS_HELPER = "/usr/libexec/console-settings-daemon/install-touch-quirks"
# INI keys are flat; nested data uses dotted keys.
TOUCH_KEY_PREFIX = "touch_map."
# Regex guards against INI-level injection into sway's command parser. Layout
# names can be comma-separated (e.g. "us,de") so comma is allowed.
LAYOUT_RE = re.compile(r"^[A-Za-z0-9_,]+$")
VARIANT_RE = re.compile(r"^[A-Za-z0-9_,]*$")  # empty is valid
# ID_PATH values from systemd's 60-persistent-input.rules: colon, dot,
# hyphen, underscore, alnum.
ID_PATH_RE = re.compile(r"^[A-Za-z0-9:._\-]+$")
# IANA timezone IDs: area/location, optionally with a sub-location
# ("America/Indiana/Indianapolis"). Also accept "UTC".
TIMEZONE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_+\-]*(?:/[A-Za-z][A-Za-z0-9_+\-]*){0,2}$")
# Font-group ids are alnum/underscore. Used as INI keys and as directory
# names under ~/.local/share/fonts/, so keep the character set tight.
FONT_GROUP_ID_RE = re.compile(r"^[a-z0-9_]+$")

FONTS_DIR = Path.home() / ".local" / "share" / "fonts"
# 1 MiB — same chunk size mdmx-updater uses. Balances TCP throughput
# against UI update cadence.
FONT_DOWNLOAD_CHUNK = 1024 * 1024

logger = logging.getLogger("console-settings")


# ---------- font group manifest ----------

# Hardcoded set of downloadable font groups the first-boot wizard offers.
# Each group is one row in the UI and one directory under
# ~/.local/share/fonts/. Packages within a group are downloaded
# sequentially; a per-package failure skips that package but does not
# abort the group. URL rot is handled the same way — if a release URL
# moves, the user just sees "Skipped X: HTTP 404" and the rest install.
#
# `format` is one of: "zip", "tar.gz", "exe-cab" (Microsoft SFX cab,
# needs `cabextract`), "tar.gz-full" (tar.gz walked recursively keeping
# every *.ttf / *.otf — used for the Google Fonts repo tarball).
FONT_GROUPS: List[Dict] = [
    {
        "id": "coding",
        "label": "Coding fonts",
        "description": "Fira Code, JetBrains Mono, Cascadia Code, IBM Plex Mono",
        "approx_size": "~20 MB",
        "eula": None,
        "packages": [
            {
                "name": "Fira Code",
                "url": "https://github.com/tonsky/FiraCode/releases/download/6.2/Fira_Code_v6.2.zip",
                "format": "zip",
            },
            {
                "name": "JetBrains Mono",
                "url": "https://download.jetbrains.com/fonts/JetBrainsMono-2.304.zip",
                "format": "zip",
            },
            {
                "name": "Cascadia Code",
                "url": "https://github.com/microsoft/cascadia-code/releases/download/v2407.24/CascadiaCode-2407.24.zip",
                "format": "zip",
            },
            {
                "name": "IBM Plex Mono",
                "url": "https://github.com/IBM/plex/releases/download/v6.4.2/TrueType.zip",
                "format": "zip",
            },
        ],
    },
    {
        "id": "proportional",
        "label": "Proportional families",
        "description": "Inter, IBM Plex Sans, Noto Sans/Serif/Mono core",
        "approx_size": "~40 MB",
        "eula": None,
        "packages": [
            {
                "name": "Inter",
                "url": "https://github.com/rsms/inter/releases/download/v4.0/Inter-4.0.zip",
                "format": "zip",
            },
            {
                "name": "IBM Plex (full TrueType)",
                "url": "https://github.com/IBM/plex/releases/download/v6.4.2/TrueType.zip",
                "format": "zip",
            },
            {
                "name": "Noto Sans",
                "url": "https://notofonts.github.io/latin-greek-cyrillic/fonts/NotoSans/googlefonts/ttf/NotoSans%5Bwdth%2Cwght%5D.ttf",
                "format": "raw-ttf",
            },
            {
                "name": "Noto Serif",
                "url": "https://notofonts.github.io/latin-greek-cyrillic/fonts/NotoSerif/googlefonts/ttf/NotoSerif%5Bwdth%2Cwght%5D.ttf",
                "format": "raw-ttf",
            },
            {
                "name": "Noto Sans Mono",
                "url": "https://notofonts.github.io/latin-greek-cyrillic/fonts/NotoSansMono/googlefonts/ttf/NotoSansMono%5Bwdth%2Cwght%5D.ttf",
                "format": "raw-ttf",
            },
        ],
    },
    {
        "id": "debian_free",
        "label": "Debian free fonts bundle",
        "description": "URW Nimbus Sans / Mono / Roman (fonts-freefont-ttf)",
        "approx_size": "~3 MB",
        "eula": None,
        "packages": [
            {
                "name": "Debian fonts-freefont-ttf",
                # Debian salsa serves the source tarball at a stable snapshot URL.
                "url": "https://salsa.debian.org/fonts-team/fonts-freefont/-/archive/debian/20120503-11/fonts-freefont-debian-20120503-11.tar.gz",
                "format": "tar.gz",
            },
        ],
    },
    {
        "id": "microsoft_core",
        "label": "Microsoft Core Fonts for the Web",
        "description": "Arial, Verdana, Times, Courier, Comic Sans, Georgia, "
                       "Impact, Trebuchet, Andale Mono, Webdings",
        "approx_size": "~8 MB",
        "eula": "https://corefonts.sourceforge.net/eula.htm",
        "packages": [
            {"name": "Andale Mono",  "url": "https://downloads.sourceforge.net/corefonts/andale32.exe", "format": "exe-cab"},
            {"name": "Arial",        "url": "https://downloads.sourceforge.net/corefonts/arial32.exe",  "format": "exe-cab"},
            {"name": "Arial Black",  "url": "https://downloads.sourceforge.net/corefonts/arialb32.exe", "format": "exe-cab"},
            {"name": "Comic Sans",   "url": "https://downloads.sourceforge.net/corefonts/comic32.exe",  "format": "exe-cab"},
            {"name": "Courier New",  "url": "https://downloads.sourceforge.net/corefonts/courie32.exe", "format": "exe-cab"},
            {"name": "Georgia",      "url": "https://downloads.sourceforge.net/corefonts/georgi32.exe", "format": "exe-cab"},
            {"name": "Impact",       "url": "https://downloads.sourceforge.net/corefonts/impact32.exe", "format": "exe-cab"},
            {"name": "Times New Roman", "url": "https://downloads.sourceforge.net/corefonts/times32.exe", "format": "exe-cab"},
            {"name": "Trebuchet",    "url": "https://downloads.sourceforge.net/corefonts/trebuc32.exe", "format": "exe-cab"},
            {"name": "Verdana",      "url": "https://downloads.sourceforge.net/corefonts/verdan32.exe", "format": "exe-cab"},
            {"name": "Webdings",     "url": "https://downloads.sourceforge.net/corefonts/webdin32.exe", "format": "exe-cab"},
        ],
    },
    {
        "id": "google",
        "label": "Google Fonts (full collection)",
        "description": "Entire Google Fonts repository — 1.3 GB download, "
                       "~3 GB on disk. Takes several minutes even on fast "
                       "links. Pick this only if you want everything.",
        "approx_size": "~1.3 GB",
        "eula": None,
        "packages": [
            {
                "name": "Google Fonts",
                "url": "https://github.com/google/fonts/archive/refs/heads/main.tar.gz",
                "format": "tar.gz-full",
            },
        ],
    },
]


# ---------- config ----------

def load_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        try:
            cfg.read(CONFIG_PATH)
        except configparser.Error as exc:
            logger.warning("config parse failed (%s); treating as empty", exc)
    return cfg


def save_config(cfg: configparser.ConfigParser) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=".console-settings.", dir=str(CONFIG_PATH.parent)
    )
    try:
        with os.fdopen(fd, "w") as fh:
            cfg.write(fh)
        os.chmod(tmp, 0o600)
        os.replace(tmp, CONFIG_PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def get_input_section(cfg: configparser.ConfigParser) -> Dict[str, str]:
    if not cfg.has_section("input"):
        return {}
    return dict(cfg.items("input"))


def set_input_section(
    cfg: configparser.ConfigParser,
    layout: str,
    variant: str,
    touch_map: Dict[str, str],
) -> None:
    # Remove the old section entirely so stale touch_map.* keys for outputs
    # the user skipped don't linger.
    if cfg.has_section("input"):
        cfg.remove_section("input")
    cfg.add_section("input")
    cfg.set("input", "keyboard_layout", layout)
    cfg.set("input", "keyboard_variant", variant)
    for output, id_path in touch_map.items():
        cfg.set("input", TOUCH_KEY_PREFIX + output, id_path)


def set_time_section(cfg: configparser.ConfigParser, timezone: str) -> None:
    if not cfg.has_section("time"):
        cfg.add_section("time")
    cfg.set("time", "timezone", timezone)


def get_time_section(cfg: configparser.ConfigParser) -> Dict[str, str]:
    if not cfg.has_section("time"):
        return {}
    return dict(cfg.items("time"))


def parse_touch_map(items: Dict[str, str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key, value in items.items():
        if key.startswith(TOUCH_KEY_PREFIX):
            out[key[len(TOUCH_KEY_PREFIX):]] = value
    return out


def get_fonts_section(cfg: configparser.ConfigParser) -> Dict[str, str]:
    if not cfg.has_section("fonts"):
        return {}
    return dict(cfg.items("fonts"))


def mark_fonts_installed(
    cfg: configparser.ConfigParser, group_ids: List[str]
) -> None:
    """Record which font groups the wizard installed (or user opted out of).

    `group_ids` is additive — existing entries survive so a reconfigure
    pass doesn't lose history. "skipped" also counts as a terminal state
    and prevents the wizard from asking again unless --reconfigure.
    """
    if not cfg.has_section("fonts"):
        cfg.add_section("fonts")
    for gid in group_ids:
        if not FONT_GROUP_ID_RE.match(gid):
            continue
        cfg.set("fonts", gid, "installed")


def mark_fonts_decision_made(cfg: configparser.ConfigParser) -> None:
    """Flag the wizard's font page as having been shown.

    Without this, a user who skips all rows on first boot would see the
    page again on the next wizard run (triggered e.g. by a new
    touchscreen). The flag lives as `_decided = yes` under [fonts] so
    an explicit `--reconfigure` still re-opens the page.
    """
    if not cfg.has_section("fonts"):
        cfg.add_section("fonts")
    cfg.set("fonts", "_decided", "yes")


# ---------- timezone ----------

def current_timezone() -> str:
    """Current timezone from the saved INI, falling back to timedatectl.

    Prefer the INI because the rootfs is read-only: `timedatectl
    set-timezone` can't rewrite /etc/localtime, so timedatectl always
    reports the image default (Universal/UTC) regardless of what the
    user picked. The INI is the actual source of truth for the wizard's
    "current choice" preselect.
    """
    try:
        cfg = load_config()
        saved = get_time_section(cfg).get("timezone", "").strip()
        if saved and TIMEZONE_RE.match(saved):
            return saved
    except Exception:
        pass
    try:
        proc = subprocess.run(
            ["timedatectl", "show", "--property=Timezone", "--value"],
            capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return proc.stdout.strip()


def list_timezones() -> List[str]:
    try:
        proc = subprocess.run(
            ["timedatectl", "list-timezones"],
            capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        logger.warning("timedatectl list-timezones failed (%s)", exc)
        return ["UTC"]
    zones = [z.strip() for z in proc.stdout.splitlines() if z.strip()]
    return zones or ["UTC"]


def apply_timezone(timezone: str) -> None:
    # The rootfs is read-only, so `timedatectl set-timezone` can't update
    # /etc/localtime (systemd-timedated gets EROFS from unlink). Instead,
    # the saved zone travels via the TZ environment variable: profile.d
    # drop-in mdmx-tz.sh reads it from this INI and exports it, and
    # sway.service's ExecStart sources the same file before starting the
    # compositor. Nothing to do here beyond the regex check — the write to
    # the INI has already happened in the caller, and the TZ picks up on
    # the next sway (re)start / login.
    if not TIMEZONE_RE.match(timezone):
        logger.warning("invalid timezone %r; skipping", timezone)
        return
    logger.info("timezone %s saved to %s", timezone, CONFIG_PATH)


# ---------- hardware scan ----------

def _sanitize_sway_name(name: str) -> str:
    # Mirrors sway's input_device_get_identifier: spaces or non-printables
    # become underscores. ASCII whitespace handling matches strip + per-char.
    stripped = name.strip()
    return "".join(
        "_" if (c == " " or not c.isprintable()) else c for c in stripped
    )


def expected_override_name(id_path: str) -> str:
    """Device name that libinput reports after our quirks file applies.

    Must survive sway's name mangling without collapsing to the same
    string as another device's name, so we keep the id_path verbatim
    (minus characters sway would strip).
    """
    return f"MDMX Touch {id_path}"


def expected_sway_identifier(id_path: str) -> str:
    # libinput reports vendor/product as 0 for the quirks-renamed virtual
    # name path; sway's format is "%d:%d:%s". Vendor/product come from the
    # real device, so match on name only — call sites look this up by
    # substring match against actual get_inputs() output.
    return _sanitize_sway_name(expected_override_name(id_path))


def scan_touchscreens(i3: i3ipc.Connection) -> Dict[str, str]:
    """Return {id_path: sway_identifier} for all currently connected touchscreens.

    Uses pyudev to walk /sys/class/input, cross-references each touchscreen's
    ID_PATH against the identifiers sway sees via get_inputs. Devices without
    the quirks-shipped name override are still enumerated (they just appear
    under their vendor-model name instead of the per-port one).
    """
    import pyudev

    sway_inputs = {
        d.identifier: d for d in i3.get_inputs() if d.type == "touch"
    }

    ctx = pyudev.Context()
    result: Dict[str, str] = {}
    for dev in ctx.list_devices(subsystem="input"):
        if dev.properties.get("ID_INPUT_TOUCHSCREEN") != "1":
            continue
        id_path = dev.properties.get("ID_PATH")
        if not id_path:
            continue
        if id_path in result:
            continue  # same device shows up as both inputN and eventN
        wanted_name = _sanitize_sway_name(expected_override_name(id_path))
        match = next(
            (
                ident for ident in sway_inputs
                if ident.endswith(":" + wanted_name)
            ),
            None,
        )
        # Fall back to any touch input matching device name roughly, so a
        # unit without the quirks rename in effect yet (first-boot pre-
        # restart) still works.
        if match is None:
            dev_name = dev.properties.get("NAME", "").strip('"')
            if dev_name:
                sanitized = _sanitize_sway_name(dev_name)
                match = next(
                    (
                        ident for ident in sway_inputs
                        if ident.endswith(":" + sanitized)
                    ),
                    None,
                )
        if match is not None:
            result[id_path] = match
    return result


# ---------- apply ----------

def _run_sway_cmd(i3: i3ipc.Connection, cmd: str) -> None:
    logger.info("sway: %s", cmd)
    reply = i3.command(cmd)
    for r in reply or []:
        if not getattr(r, "success", True):
            logger.error("sway rejected %r: %s", cmd, getattr(r, "error", "?"))


def apply_settings(
    cfg: configparser.ConfigParser,
    i3: i3ipc.Connection,
    touchscreens: Dict[str, str],
) -> None:
    items = get_input_section(cfg)
    layout = items.get("keyboard_layout", "").strip()
    variant = items.get("keyboard_variant", "").strip()
    if layout and LAYOUT_RE.match(layout):
        _run_sway_cmd(i3, f'input type:keyboard xkb_layout "{layout}"')
    if VARIANT_RE.match(variant):
        _run_sway_cmd(i3, f'input type:keyboard xkb_variant "{variant}"')

    timezone = get_time_section(cfg).get("timezone", "").strip()
    if timezone:
        apply_timezone(timezone)

    for output, id_path in parse_touch_map(items).items():
        identifier = touchscreens.get(id_path)
        if identifier is None:
            logger.warning(
                "stored touch_map.%s=%s has no matching device; skipped",
                output, id_path,
            )
            continue
        _run_sway_cmd(
            i3, f'input "{identifier}" map_to_output "{output}"'
        )


# ---------- completeness check ----------

def diagnose(
    cfg: configparser.ConfigParser,
    outputs: List[str],
    touchscreens: Dict[str, str],
) -> List[str]:
    """Return list of human-readable problems; empty list = complete."""
    problems: List[str] = []
    items = get_input_section(cfg)

    layout = items.get("keyboard_layout", "").strip()
    if not layout:
        problems.append("keyboard layout not set")
    elif not LAYOUT_RE.match(layout):
        problems.append(f"invalid keyboard_layout {layout!r}")

    variant = items.get("keyboard_variant", "").strip()
    if variant and not VARIANT_RE.match(variant):
        problems.append(f"invalid keyboard_variant {variant!r}")

    timezone = get_time_section(cfg).get("timezone", "").strip()
    if not timezone:
        problems.append("timezone not set")
    elif not TIMEZONE_RE.match(timezone):
        problems.append(f"invalid timezone {timezone!r}")

    touch_map = parse_touch_map(items)
    stored_paths = set(touch_map.values())
    present_paths = set(touchscreens.keys())
    for id_path in stored_paths - present_paths:
        problems.append(f"stored touchscreen {id_path} not present")
    for id_path in present_paths - stored_paths:
        problems.append(f"touchscreen {id_path} present but not mapped")
    for id_path in touch_map.values():
        if not ID_PATH_RE.match(id_path):
            problems.append(f"invalid id_path {id_path!r}")

    return problems


# ---------- base.lst parsing ----------

def parse_base_lst() -> Dict[str, List[Tuple[str, str]]]:
    """Returns {section_name: [(code, description), …]} from xkb's base.lst."""
    sections: Dict[str, List[Tuple[str, str]]] = {}
    current: Optional[str] = None
    try:
        for raw in BASE_LST.read_text().splitlines():
            line = raw.rstrip()
            if line.startswith("! "):
                current = line[2:].strip()
                sections[current] = []
            elif current and line.strip():
                code, _, desc = line.strip().partition(" ")
                sections[current].append((code.strip(), desc.strip()))
    except OSError as exc:
        logger.warning("could not read %s (%s)", BASE_LST, exc)
    return sections


# ---------- evdev helpers ----------

def list_touchscreens_evdev() -> List[Tuple[str, str]]:
    """Return [(evdev_path, id_path), …] for currently connected touchscreens.

    id_path is the udev ID_PATH; used both for the INI mapping and for the
    libinput quirks file written at commit time.
    """
    import evdev
    import pyudev

    ctx = pyudev.Context()
    result: List[Tuple[str, str]] = []
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
        except OSError:
            continue
        caps = dev.capabilities()
        # evdev.capabilities() returns plain ints for EV_KEY entries but
        # (code, AbsInfo) tuples for EV_ABS entries, so unpack differently.
        # ABS_MT_POSITION_X=53 is the canonical multitouch flag; BTN_TOUCH
        # single-touch fallback. ecodes.EV_ABS = 3, EV_KEY = 1.
        abs_codes = {c for c, *_ in caps.get(3, [])}
        key_codes = set(caps.get(1, []))
        is_touch = 53 in abs_codes or 330 in key_codes  # ABS_MT_POSITION_X, BTN_TOUCH
        if not is_touch:
            dev.close()
            continue
        try:
            udev = pyudev.Devices.from_device_file(ctx, path)
        except (pyudev.DeviceNotFoundByFileError, OSError):
            dev.close()
            continue
        id_path = udev.properties.get("ID_PATH")
        if id_path:
            result.append((path, id_path))
        dev.close()
    return result


# ---------- quirks helper invocation ----------

def write_quirks(touch_map: Dict[str, str]) -> None:
    """Build quirks payload and push through the pkexec helper.

    Only touchscreens actually mapped to an output get an override entry;
    the helper validates and atomically rewrites /var/lib/console-settings/
    local-overrides.quirks (reached by libinput via the /etc/libinput
    symlink shipped by the recipe).
    """
    seen: set = set()
    entries = []
    for id_path in touch_map.values():
        if id_path in seen or not ID_PATH_RE.match(id_path):
            continue
        seen.add(id_path)
        entries.append({
            "id_path": id_path,
            "override_name": expected_override_name(id_path),
        })
    payload = json.dumps(entries).encode("utf-8")
    logger.info("writing quirks via pkexec for %d device(s)", len(entries))
    subprocess.run(
        ["pkexec", QUIRKS_HELPER],
        input=payload,
        check=True,
    )


def restart_sway() -> None:
    logger.info("restarting sway so libinput re-reads quirks")
    subprocess.run(
        ["pkexec", "systemctl", "restart", "sway.service"],
        check=True,
    )


# ---------- GUI wizard ----------

CSS = b"""
window { background-color: rgba(10, 10, 30, 0.98); }
label { color: #ffffff; }
label.title { font-size: 36px; }
label.prompt { font-size: 26px; }
label.wait { font-size: 32px; color: #a0a0b8; }
label.target { font-size: 56px; }
button.action {
    font-size: 28px;
    min-width: 240px;
    min-height: 90px;
    background-image: none;
    background-color: #2d2d54;
    color: #ffffff;
    border-radius: 14px;
    border: 1px solid #6b8afd;
}
button.action:hover,
button.action:active { background-color: #4a63d6; }
button.skip { background-color: #7a3f3f; border-color: #b36b6b; }
button.touchtarget {
    font-size: 72px;
    background-color: #2d2d54;
    color: #ffffff;
    border: 4px solid #6b8afd;
    border-radius: 24px;
    min-width: 480px;
    min-height: 360px;
}

/* GTK's default theme paints list/row/scrolledwindow/textview/progressbar
   white, which makes the white label text in the fonts wizard invisible
   against the dark window. Force the dark palette onto the widgets used
   by _run_fonts_* so the page actually reads. */
scrolledwindow,
scrolledwindow viewport,
list,
list row,
textview,
textview text {
    background-color: rgba(10, 10, 30, 0.98);
    color: #ffffff;
}
list row:selected,
list row:hover { background-color: #2d2d54; }
checkbutton { color: #ffffff; }
checkbutton check {
    background-color: #1a1a3a;
    border-color: #6b8afd;
}
checkbutton check:checked {
    background-color: #4a63d6;
    border-color: #6b8afd;
    color: #ffffff;
}
progressbar trough { background-color: #1a1a3a; border-color: #6b8afd; }
progressbar progress { background-color: #4a63d6; }
progressbar text { color: #ffffff; }
"""


# ---------- font installer ----------

# Progress payload passed from the worker thread back to the main
# thread via GLib.idle_add. Fields:
#   kind       — "status" (new overall step), "bytes" (download progress),
#                "log" (append to scrolling log), "done" (worker exited).
#   group_idx  — 0-based group counter, matches outer progress bar.
#   group_total — total number of selected groups.
#   group_label — human string for the current group.
#   pkg_name   — current package name, if applicable.
#   pkg_idx    — current package index within the group.
#   pkg_total  — total packages in the current group.
#   bytes_done — bytes downloaded so far (for "bytes").
#   bytes_total — total bytes expected, or None if the server didn't
#                 send Content-Length.
#   message    — log line.
#   ok         — final success flag (for "done").
#   installed  — list of successfully installed group ids (for "done").
Progress = Dict[str, object]


def _safe_font_filename(name: str) -> bool:
    """Reject archive entries with absolute paths, .., or control chars.

    Downloaded TTF/OTF files land in a user-writable directory outside
    the sandbox; a maliciously-crafted archive could otherwise drop a
    file at /home/user/.ssh/authorized_keys or similar.
    """
    base = os.path.basename(name)
    if not base or base.startswith(".") or "/" in base or "\\" in base:
        return False
    return base.lower().endswith((".ttf", ".otf"))


def _extract_zip_fonts(archive: Path, dest: Path) -> int:
    """Copy *.ttf/*.otf out of a zip into dest. Returns file count."""
    count = 0
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue
            name = member.filename
            if not _safe_font_filename(name):
                continue
            target = dest / os.path.basename(name)
            with zf.open(member) as src, target.open("wb") as fh:
                shutil.copyfileobj(src, fh)
            count += 1
    return count


def _extract_tar_fonts(archive: Path, dest: Path) -> int:
    count = 0
    with tarfile.open(archive, "r:*") as tf:
        for member in tf:
            if not member.isfile():
                continue
            if not _safe_font_filename(member.name):
                continue
            src = tf.extractfile(member)
            if src is None:
                continue
            target = dest / os.path.basename(member.name)
            with target.open("wb") as fh:
                shutil.copyfileobj(src, fh)
            count += 1
    return count


def _extract_exe_cab_fonts(archive: Path, dest: Path) -> int:
    """Microsoft SFX cab (.exe). Shell out to cabextract."""
    with tempfile.TemporaryDirectory(prefix="mdmx-cab-") as tdir:
        # `-L` lower-cases filenames which simplifies the TTF glob. `-F`
        # restricts extraction so only the fonts come out — avoids
        # dropping readme.txt / fontinst.inf on us.
        try:
            subprocess.run(
                ["cabextract", "-q", "-L", "-F", "*.TTF",
                 "-d", tdir, str(archive)],
                check=True, capture_output=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            logger.warning("cabextract failed on %s: %s", archive.name, exc)
            return 0
        count = 0
        for root, _dirs, files in os.walk(tdir):
            for fname in files:
                if not fname.lower().endswith(".ttf"):
                    continue
                src = Path(root) / fname
                target = dest / fname
                shutil.copy2(src, target)
                count += 1
        return count


def _download_to(
    url: str,
    dest: Path,
    *,
    cancel_event: threading.Event,
    on_progress: Callable[[int, Optional[int]], None],
    timeout: int = 1800,
) -> None:
    """Stream a URL to dest, reporting bytes_done / bytes_total.

    Raises on failure; caller handles per-package exceptions. Respects
    a cancel_event: if it fires mid-stream, abort and unlink the
    partial file instead of truncating a half-download onto disk.
    """
    req = urllib.request.Request(
        url, headers={"User-Agent": "mdmx-fontsetup/1"}
    )
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            total_hdr = r.headers.get("Content-Length")
            total = int(total_hdr) if total_hdr and total_hdr.isdigit() else None
            done = 0
            on_progress(done, total)
            with tmp.open("wb") as fh:
                while True:
                    if cancel_event.is_set():
                        raise RuntimeError("cancelled")
                    chunk = r.read(FONT_DOWNLOAD_CHUNK)
                    if not chunk:
                        break
                    fh.write(chunk)
                    done += len(chunk)
                    on_progress(done, total)
        tmp.replace(dest)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _install_one_package(
    pkg: Dict,
    group_dir: Path,
    *,
    cancel_event: threading.Event,
    report_bytes: Callable[[int, Optional[int]], None],
    report_log: Callable[[str], None],
) -> bool:
    """Download + extract one package into group_dir. Returns True on success."""
    name = pkg["name"]
    url = pkg["url"]
    fmt = pkg["format"]
    report_log(f"⟳ {name} — downloading…")

    with tempfile.TemporaryDirectory(prefix="mdmx-font-") as tdir:
        archive = Path(tdir) / "download.bin"
        try:
            _download_to(
                url, archive,
                cancel_event=cancel_event,
                on_progress=report_bytes,
            )
        except Exception as exc:
            if cancel_event.is_set():
                report_log(f"⨯ {name} — cancelled")
            else:
                report_log(f"⨯ {name} — download failed ({exc})")
            return False

        try:
            group_dir.mkdir(parents=True, exist_ok=True)
            if fmt == "zip":
                count = _extract_zip_fonts(archive, group_dir)
            elif fmt in ("tar.gz", "tar.gz-full"):
                count = _extract_tar_fonts(archive, group_dir)
            elif fmt == "exe-cab":
                count = _extract_exe_cab_fonts(archive, group_dir)
            elif fmt == "raw-ttf":
                # Already a bare .ttf; copy using the package name.
                target = group_dir / f"{name.replace(' ', '')}.ttf"
                shutil.copy2(archive, target)
                count = 1
            else:
                report_log(f"⨯ {name} — unknown format {fmt}")
                return False
        except Exception as exc:
            report_log(f"⨯ {name} — extract failed ({exc})")
            return False

    if count == 0:
        report_log(f"⚠ {name} — archive contained no fonts")
        return False
    report_log(f"✓ {name} — {count} font file(s)")
    return True


def _install_font_groups(
    groups: List[Dict],
    cancel_event: threading.Event,
    on_progress: Callable[[Progress], None],
) -> List[str]:
    """Download + install selected groups sequentially. Returns ids installed."""
    installed: List[str] = []
    total = len(groups)
    for idx, group in enumerate(groups):
        if cancel_event.is_set():
            break
        group_dir = FONTS_DIR / group["id"]
        on_progress({
            "kind": "status",
            "group_idx": idx,
            "group_total": total,
            "group_label": group["label"],
            "pkg_idx": 0,
            "pkg_total": len(group["packages"]),
            "pkg_name": "",
        })
        on_progress({"kind": "log", "message": f"— {group['label']}"})

        any_ok = False
        for pidx, pkg in enumerate(group["packages"]):
            if cancel_event.is_set():
                break
            on_progress({
                "kind": "status",
                "group_idx": idx,
                "group_total": total,
                "group_label": group["label"],
                "pkg_idx": pidx,
                "pkg_total": len(group["packages"]),
                "pkg_name": pkg["name"],
            })

            def report_bytes(done, total_bytes, _pidx=pidx):
                on_progress({
                    "kind": "bytes",
                    "bytes_done": done,
                    "bytes_total": total_bytes,
                })

            def report_log(msg):
                on_progress({"kind": "log", "message": msg})

            ok = _install_one_package(
                pkg, group_dir,
                cancel_event=cancel_event,
                report_bytes=report_bytes,
                report_log=report_log,
            )
            any_ok = any_ok or ok

        if any_ok:
            installed.append(group["id"])

    # fc-cache picks up the new files so subsequently-started apps see
    # them without a logout. Scoped to the user's font dir to avoid
    # EACCES on /usr/share/fonts.
    try:
        subprocess.run(
            ["fc-cache", "-f", str(FONTS_DIR)],
            check=False, capture_output=True, timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        on_progress({
            "kind": "log",
            "message": f"⚠ fc-cache failed ({exc}) — restart apps to see new fonts",
        })
    return installed


class Wizard:
    """GTK3 wizard: keyboard → timezone → optional fonts → per-output touch map."""

    def __init__(self, outputs: List[str]):
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        gi.require_version("GtkLayerShell", "0.1")
        from gi.repository import Gdk, Gtk  # noqa: F401

        self._outputs = outputs
        self._selected_layout: str = ""
        self._selected_variant: str = ""
        self._selected_timezone: str = ""
        self._touch_map: Dict[str, str] = {}
        self._touch_devs: List[Tuple[str, str]] = []
        self._installed_fonts: List[str] = []
        self._fonts_decided: bool = False
        self._completed: bool = False
        self._install_css()

    def _install_css(self) -> None:
        from gi.repository import Gdk, Gtk
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def run(
        self, offer_fonts: bool = True
    ) -> Optional[Tuple[str, str, str, Dict[str, str], List[str], bool]]:
        """Return a tuple of wizard results, or None if cancelled.

        Tuple fields: (layout, variant, timezone, touch_map,
        installed_font_group_ids, fonts_decided). The caller only persists
        the font-related fields when `fonts_decided` is True — a
        force-skipped page (offer_fonts=False) returns [] / False so the
        existing INI isn't clobbered.
        """
        if not self._run_keyboard_page():
            return None
        if not self._run_timezone_page():
            return None
        if offer_fonts:
            # Dialog can't be cancelled — "Skip" is a valid exit — so no
            # return-value check here. Side effects land on
            # self._installed_fonts / self._fonts_decided.
            self._run_fonts_page()
        if self._outputs and not self._run_touch_calibration():
            return None
        self._completed = True
        return (
            self._selected_layout,
            self._selected_variant,
            self._selected_timezone,
            self._touch_map,
            self._installed_fonts,
            self._fonts_decided,
        )

    # ----- keyboard page -----

    def _run_keyboard_page(self) -> bool:
        from gi.repository import Gtk

        sections = parse_base_lst()
        layouts = sections.get("layout", [("us", "English (US)")])

        win = Gtk.Window(title="MissionDMX setup — keyboard")
        win.set_default_size(640, 480)
        win.set_position(Gtk.WindowPosition.CENTER)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        box.set_margin_top(40)
        box.set_margin_bottom(40)
        box.set_margin_start(40)
        box.set_margin_end(40)

        title = Gtk.Label(label="Pick a keyboard layout")
        title.get_style_context().add_class("title")
        box.pack_start(title, False, False, 0)

        layout_combo = Gtk.ComboBoxText()
        for code, desc in layouts:
            layout_combo.append(code, f"{code} — {desc}")
        layout_combo.set_active_id("us")
        box.pack_start(layout_combo, False, False, 0)

        variant_label = Gtk.Label(label="Variant (optional)")
        variant_label.get_style_context().add_class("prompt")
        box.pack_start(variant_label, False, False, 0)

        variant_combo = Gtk.ComboBoxText()
        box.pack_start(variant_combo, False, False, 0)

        def refresh_variants(_combo):
            variant_combo.remove_all()
            variant_combo.append("", "(default)")
            layout_code = layout_combo.get_active_id() or ""
            prefix = layout_code + ":"
            for code, desc in sections.get("variant", []):
                if desc.startswith(prefix):
                    variant_combo.append(code, f"{code} — {desc}")
            variant_combo.set_active_id("")

        layout_combo.connect("changed", refresh_variants)
        refresh_variants(layout_combo)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        buttons.set_halign(Gtk.Align.END)

        cont = Gtk.Button(label="Continue")
        cont.get_style_context().add_class("action")

        def on_continue(_btn):
            layout_code = (layout_combo.get_active_id() or "").strip()
            variant_code = (variant_combo.get_active_id() or "").strip()
            if not LAYOUT_RE.match(layout_code):
                return
            if variant_code and not VARIANT_RE.match(variant_code):
                return
            self._selected_layout = layout_code
            self._selected_variant = variant_code
            win.close()

        cont.connect("clicked", on_continue)
        buttons.pack_start(cont, False, False, 0)
        box.pack_end(buttons, False, False, 0)

        win.add(box)
        win.connect("destroy", Gtk.main_quit)
        win.show_all()
        Gtk.main()
        return bool(self._selected_layout)

    # ----- timezone page -----

    def _run_timezone_page(self) -> bool:
        from gi.repository import Gtk

        zones = list_timezones()
        current = current_timezone() or "UTC"
        # If timedatectl's current pick isn't in the list (rare — e.g. a
        # non-canonical alias), fall back to UTC so the combo always has
        # a sensible default.
        default_zone = current if current in zones else "UTC"

        win = Gtk.Window(title="MissionDMX setup — timezone")
        win.set_default_size(640, 480)
        win.set_position(Gtk.WindowPosition.CENTER)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        box.set_margin_top(40)
        box.set_margin_bottom(40)
        box.set_margin_start(40)
        box.set_margin_end(40)

        title = Gtk.Label(label="Pick a time zone")
        title.get_style_context().add_class("title")
        box.pack_start(title, False, False, 0)

        # Gtk.ComboBoxText scrolls poorly for ~400 timezones on a touch
        # display, so we pair a type-to-filter entry with a scrolled list.
        model = Gtk.ListStore(str)
        for z in zones:
            model.append([z])

        filter_entry = Gtk.SearchEntry()
        filter_entry.set_placeholder_text("Type to filter (e.g. Berlin)")
        box.pack_start(filter_entry, False, False, 0)

        tree_filter = model.filter_new()
        tree_filter.set_visible_func(
            lambda m, it, _d: filter_entry.get_text().lower() in m[it][0].lower()
        )

        tree = Gtk.TreeView(model=tree_filter)
        tree.append_column(
            Gtk.TreeViewColumn("Timezone", Gtk.CellRendererText(), text=0)
        )
        tree.set_headers_visible(False)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(260)
        scroll.add(tree)
        box.pack_start(scroll, True, True, 0)

        selection = tree.get_selection()
        selection.set_mode(Gtk.SelectionMode.SINGLE)

        def select_zone(zone: str):
            for i, row in enumerate(tree_filter):
                if row[0] == zone:
                    tree.set_cursor(Gtk.TreePath.new_from_indices([i]))
                    break

        select_zone(default_zone)
        filter_entry.connect("search-changed", lambda _e: tree_filter.refilter())

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        buttons.set_halign(Gtk.Align.END)
        cont = Gtk.Button(label="Continue")
        cont.get_style_context().add_class("action")

        def on_continue(_btn):
            model_, iter_ = selection.get_selected()
            if iter_ is None:
                return
            zone = model_[iter_][0]
            if not TIMEZONE_RE.match(zone):
                return
            self._selected_timezone = zone
            win.close()

        cont.connect("clicked", on_continue)
        tree.connect(
            "row-activated",
            lambda _tv, _p, _c: on_continue(cont),
        )
        buttons.pack_start(cont, False, False, 0)
        box.pack_end(buttons, False, False, 0)

        win.add(box)
        win.connect("destroy", Gtk.main_quit)
        win.show_all()
        Gtk.main()
        return bool(self._selected_timezone)

    # ----- fonts page -----

    def _run_fonts_page(self) -> None:
        """Offer optional font downloads into ~/.local/share/fonts/.

        Two windows back-to-back: a selection form, then (if the user
        picked ≥1 group) a progress window that drives the actual
        downloads on a background thread. Both record their outcome
        into self._installed_fonts / self._fonts_decided so the caller
        can persist the result without extra round-trips.
        """
        from gi.repository import Gtk

        selected_groups = self._run_fonts_selection_page()
        self._fonts_decided = True  # user has seen the page either way
        if not selected_groups:
            logger.info("fonts: user skipped the download page")
            return
        self._installed_fonts = self._run_fonts_install_page(selected_groups)

    def _run_fonts_selection_page(self) -> List[Dict]:
        from gi.repository import Gtk

        win = Gtk.Window(title="MissionDMX setup — extra fonts")
        win.set_default_size(820, 640)
        win.set_position(Gtk.WindowPosition.CENTER)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        outer.set_margin_top(32)
        outer.set_margin_bottom(32)
        outer.set_margin_start(40)
        outer.set_margin_end(40)

        title = Gtk.Label(label="Install extra fonts? (optional)")
        title.get_style_context().add_class("title")
        outer.pack_start(title, False, False, 0)

        subtitle = Gtk.Label(
            label="Selected packages are downloaded to "
                  "~/.local/share/fonts/. Skip if your network is slow — "
                  "you can rerun this later with "
                  "`console-settings-daemon --reconfigure`."
        )
        subtitle.get_style_context().add_class("prompt")
        subtitle.set_line_wrap(True)
        subtitle.set_xalign(0.0)
        outer.pack_start(subtitle, False, False, 0)

        # One ListBoxRow per group. Store the group dict and the
        # row's checkbutton + (optional) EULA checkbutton together so
        # the submit handler can collect selections without another
        # walk of FONT_GROUPS.
        rows_state: List[Dict] = []

        listbox = Gtk.ListBox()
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        for group in FONT_GROUPS:
            row = Gtk.ListBoxRow()
            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
            hbox.set_margin_top(12)
            hbox.set_margin_bottom(12)
            hbox.set_margin_start(12)
            hbox.set_margin_end(12)

            check = Gtk.CheckButton()
            check.set_valign(Gtk.Align.START)
            hbox.pack_start(check, False, False, 0)

            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            label = Gtk.Label(
                label=f"{group['label']}  ({group['approx_size']})"
            )
            label.set_xalign(0.0)
            label.get_style_context().add_class("prompt")
            vbox.pack_start(label, False, False, 0)
            desc = Gtk.Label(label=group["description"])
            desc.set_xalign(0.0)
            desc.set_line_wrap(True)
            vbox.pack_start(desc, False, False, 0)

            eula_check: Optional[Gtk.CheckButton] = None
            if group["eula"]:
                eula_check = Gtk.CheckButton(
                    label=f"I accept the EULA ({group['eula']})"
                )
                eula_check.set_sensitive(False)
                vbox.pack_start(eula_check, False, False, 0)

                def _sync_eula(cb, inner=eula_check):
                    inner.set_sensitive(cb.get_active())
                check.connect("toggled", _sync_eula)

            hbox.pack_start(vbox, True, True, 0)
            row.add(hbox)
            listbox.add(row)
            rows_state.append({
                "group": group,
                "check": check,
                "eula_check": eula_check,
            })

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(listbox)
        outer.pack_start(scroll, True, True, 0)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        buttons.set_halign(Gtk.Align.END)

        skip = Gtk.Button(label="Skip")
        skip.get_style_context().add_class("action")
        skip.get_style_context().add_class("skip")

        cont = Gtk.Button(label="Install selected")
        cont.get_style_context().add_class("action")

        chosen: List[Dict] = []

        def on_cont(_btn):
            chosen.clear()
            for state in rows_state:
                if not state["check"].get_active():
                    continue
                if state["eula_check"] is not None \
                   and not state["eula_check"].get_active():
                    # Highlight the missing EULA tick instead of silently
                    # dropping the row — user otherwise won't know why
                    # their selection didn't take.
                    state["eula_check"].grab_focus()
                    return
                chosen.append(state["group"])
            win.close()

        def on_skip(_btn):
            chosen.clear()
            win.close()

        cont.connect("clicked", on_cont)
        skip.connect("clicked", on_skip)
        buttons.pack_start(skip, False, False, 0)
        buttons.pack_start(cont, False, False, 0)
        outer.pack_end(buttons, False, False, 0)

        win.add(outer)
        win.connect("destroy", Gtk.main_quit)
        win.show_all()
        Gtk.main()
        return chosen

    def _run_fonts_install_page(self, groups: List[Dict]) -> List[str]:
        from gi.repository import GLib, Gtk

        win = Gtk.Window(title="MissionDMX setup — downloading fonts")
        win.set_default_size(820, 560)
        win.set_position(Gtk.WindowPosition.CENTER)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        outer.set_margin_top(32)
        outer.set_margin_bottom(32)
        outer.set_margin_start(40)
        outer.set_margin_end(40)

        title = Gtk.Label(label="Downloading fonts")
        title.get_style_context().add_class("title")
        outer.pack_start(title, False, False, 0)

        status_label = Gtk.Label(label="Preparing…")
        status_label.get_style_context().add_class("prompt")
        status_label.set_xalign(0.0)
        outer.pack_start(status_label, False, False, 0)

        # Outer bar: group-level completion. Inner bar: byte-level
        # progress of the current download / extraction. A separate
        # label under the inner bar shows "123 MB / 500 MB" so the user
        # has a concrete answer to "is it still working?".
        outer_bar = Gtk.ProgressBar()
        outer_bar.set_show_text(True)
        outer.pack_start(outer_bar, False, False, 0)

        inner_bar = Gtk.ProgressBar()
        inner_bar.set_show_text(True)
        outer.pack_start(inner_bar, False, False, 0)

        bytes_label = Gtk.Label(label="")
        bytes_label.set_xalign(0.0)
        outer.pack_start(bytes_label, False, False, 0)

        log_buffer = Gtk.TextBuffer()
        log_view = Gtk.TextView(buffer=log_buffer)
        log_view.set_editable(False)
        log_view.set_cursor_visible(False)
        log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        log_scroll = Gtk.ScrolledWindow()
        log_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        log_scroll.set_min_content_height(220)
        log_scroll.add(log_view)
        outer.pack_start(log_scroll, True, True, 0)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        buttons.set_halign(Gtk.Align.END)
        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.get_style_context().add_class("action")
        cancel_btn.get_style_context().add_class("skip")
        close_btn = Gtk.Button(label="Close")
        close_btn.get_style_context().add_class("action")
        close_btn.set_sensitive(False)
        buttons.pack_start(cancel_btn, False, False, 0)
        buttons.pack_start(close_btn, False, False, 0)
        outer.pack_end(buttons, False, False, 0)

        win.add(outer)
        win.connect("destroy", Gtk.main_quit)
        win.show_all()

        cancel_event = threading.Event()
        state: Dict[str, object] = {"installed": [], "worker_done": False}

        def apply_progress(prog: Progress) -> bool:
            kind = prog.get("kind")
            if kind == "status":
                gi = prog["group_idx"]
                gt = prog["group_total"]
                outer_bar.set_fraction((gi) / max(gt, 1))
                outer_bar.set_text(
                    f"{gi + 1} of {gt} — {prog['group_label']}"
                )
                pkg = prog.get("pkg_name") or ""
                pi = prog.get("pkg_idx", 0)
                pt = prog.get("pkg_total", 1)
                status_label.set_text(
                    f"Package {pi + 1}/{pt}: {pkg}" if pkg
                    else f"Starting group: {prog['group_label']}"
                )
                inner_bar.set_fraction(0.0)
                inner_bar.set_text("")
                bytes_label.set_text("")
            elif kind == "bytes":
                done = prog.get("bytes_done", 0)
                total = prog.get("bytes_total")
                if total:
                    inner_bar.set_fraction(min(done / total, 1.0))
                    inner_bar.set_text(f"{int(done * 100 / total)}%")
                    bytes_label.set_text(
                        f"{done / 1_000_000:.1f} / {total / 1_000_000:.1f} MB"
                    )
                else:
                    inner_bar.pulse()
                    bytes_label.set_text(f"{done / 1_000_000:.1f} MB")
            elif kind == "log":
                end = log_buffer.get_end_iter()
                log_buffer.insert(end, (prog.get("message") or "") + "\n")
                # Autoscroll to the newest entry.
                mark = log_buffer.create_mark(None, log_buffer.get_end_iter(), False)
                log_view.scroll_to_mark(mark, 0.0, False, 0.0, 0.0)
            elif kind == "done":
                state["installed"] = prog.get("installed", [])
                state["worker_done"] = True
                outer_bar.set_fraction(1.0)
                outer_bar.set_text("Done")
                status_label.set_text(
                    "All selected packages processed."
                    if prog.get("ok") else
                    "Some downloads failed — see log."
                )
                inner_bar.set_fraction(1.0)
                inner_bar.set_text("")
                bytes_label.set_text("")
                cancel_btn.set_sensitive(False)
                close_btn.set_sensitive(True)
            return False  # one-shot idle callback

        def on_progress(prog: Progress) -> None:
            GLib.idle_add(apply_progress, prog)

        def worker() -> None:
            installed: List[str] = []
            ok = True
            try:
                installed = _install_font_groups(groups, cancel_event, on_progress)
            except Exception as exc:
                logger.exception("font install thread crashed")
                on_progress({"kind": "log", "message": f"⨯ internal error: {exc}"})
                ok = False
            on_progress({"kind": "done", "installed": installed, "ok": ok})

        th = threading.Thread(target=worker, name="mdmx-font-installer", daemon=True)
        th.start()

        def on_cancel(_btn):
            cancel_event.set()
            cancel_btn.set_sensitive(False)
            status_label.set_text("Cancelling — finishing current chunk…")

        def on_close(_btn):
            win.close()

        cancel_btn.connect("clicked", on_cancel)
        close_btn.connect("clicked", on_close)

        Gtk.main()
        return list(state.get("installed", []))  # type: ignore[return-value]

    # ----- touch calibration -----

    def _run_touch_calibration(self) -> bool:
        self._touch_devs = list_touchscreens_evdev()
        if not self._touch_devs:
            logger.info("no touchscreens detected; skipping calibration")
            return True

        for index, output in enumerate(self._outputs):
            if not self._run_calibration_step(index, output):
                return False
        return True

    def _run_calibration_step(self, index: int, target_output: str) -> bool:
        import evdev
        from gi.repository import Gdk, GLib, Gtk, GtkLayerShell

        display = Gdk.Display.get_default()
        gdk_monitors: Dict[str, "Gdk.Monitor"] = {}
        for i in range(display.get_n_monitors()):
            mon = display.get_monitor(i)
            model = mon.get_model() or ""
            if model:
                gdk_monitors[model] = mon

        windows: List["Gtk.Window"] = []
        for output in self._outputs:
            win = Gtk.Window()
            win.set_decorated(False)
            win.set_app_paintable(True)
            GtkLayerShell.init_for_window(win)
            if output in gdk_monitors:
                GtkLayerShell.set_monitor(win, gdk_monitors[output])
            GtkLayerShell.set_layer(win, GtkLayerShell.Layer.OVERLAY)
            for edge in (
                GtkLayerShell.Edge.TOP,
                GtkLayerShell.Edge.BOTTOM,
                GtkLayerShell.Edge.LEFT,
                GtkLayerShell.Edge.RIGHT,
            ):
                GtkLayerShell.set_anchor(win, edge, True)
            GtkLayerShell.set_exclusive_zone(win, -1)
            GtkLayerShell.set_keyboard_mode(
                win, GtkLayerShell.KeyboardMode.NONE
            )
            body, skip_btn = self._build_calibration_body(
                is_target=(output == target_output),
                step=index + 1,
                total=len(self._outputs),
                output_name=target_output,
            )
            win.add(body)
            win._mdmx_skip_button = skip_btn  # type: ignore[attr-defined]
            win.show_all()
            windows.append(win)

        open_devs: Dict[int, "evdev.InputDevice"] = {}
        for path, _id_path in self._touch_devs:
            try:
                d = evdev.InputDevice(path)
                open_devs[d.fd] = d
            except OSError as exc:
                logger.warning("open %s failed: %s", path, exc)

        state: Dict[str, object] = {"skipped": False, "id_path": None}

        def on_fd_ready(fd, _condition):
            dev = open_devs.get(fd)
            if dev is None:
                return False
            try:
                for ev in dev.read():
                    # ecodes.EV_KEY=1, BTN_TOUCH=330, value=1 is press.
                    # ABS_MT_TRACKING_ID (type=3,code=57) going non-negative
                    # covers devices without BTN_TOUCH.
                    if (ev.type == 1 and ev.code == 330 and ev.value == 1) \
                       or (ev.type == 3 and ev.code == 57 and ev.value != -1):
                        state["id_path"] = next(
                            (p for pth, p in self._touch_devs
                             if pth == dev.path),
                            None,
                        )
                        Gtk.main_quit()
                        return False
            except OSError:
                return False
            return True

        source_ids: List[int] = [
            GLib.io_add_watch(fd, GLib.IO_IN, on_fd_ready)
            for fd in open_devs
        ]

        def on_skip(_btn):
            state["skipped"] = True
            Gtk.main_quit()

        for win in windows:
            btn = getattr(win, "_mdmx_skip_button", None)
            if btn is not None:
                btn.connect("clicked", on_skip)

        Gtk.main()

        for sid in source_ids:
            try:
                GLib.source_remove(sid)
            except Exception:
                pass
        for d in open_devs.values():
            try:
                d.close()
            except OSError:
                pass
        for win in windows:
            win.close()

        if state["skipped"]:
            logger.info("output %s skipped", target_output)
            return True
        if state["id_path"]:
            logger.info("output %s mapped to %s", target_output, state["id_path"])
            self._touch_map[target_output] = state["id_path"]
            return True
        logger.info("calibration step %s produced no mapping", target_output)
        return False

    def _build_calibration_body(
        self,
        *,
        is_target: bool,
        step: int,
        total: int,
        output_name: str,
    ):
        from gi.repository import Gtk

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=32)
        outer.set_halign(Gtk.Align.CENTER)
        outer.set_valign(Gtk.Align.CENTER)
        skip: Optional["Gtk.Button"] = None

        if is_target:
            step_label = Gtk.Label(
                label=f"Step {step} of {total} — touch output {output_name}"
            )
            step_label.get_style_context().add_class("prompt")
            outer.pack_start(step_label, False, False, 0)

            target_label = Gtk.Label(label="Touch this screen")
            target_label.get_style_context().add_class("target")
            outer.pack_start(target_label, False, False, 0)

            skip = Gtk.Button(label="Skip this screen (no touch here)")
            skip.get_style_context().add_class("action")
            skip.get_style_context().add_class("skip")
            outer.pack_start(skip, False, False, 0)
        else:
            info = Gtk.Label(
                label="Please wait — calibrating another screen"
            )
            info.get_style_context().add_class("wait")
            outer.pack_start(info, False, False, 0)

        return outer, skip


# ---------- main ----------

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reconfigure",
        action="store_true",
        help="skip the fast path even if the INI looks complete",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        i3 = i3ipc.Connection()
    except Exception as exc:
        logger.error("i3ipc connect failed: %s", exc)
        return 1

    cfg = load_config()
    outputs = [o.name for o in i3.get_outputs() if o.active]
    touchscreens = scan_touchscreens(i3)

    problems = diagnose(cfg, outputs, touchscreens)
    if not problems and not args.reconfigure:
        apply_settings(cfg, i3, touchscreens)
        return 0

    logger.info("entering wizard: %s", "; ".join(problems) or "forced")

    # Offer the font download page only if the user hasn't already
    # answered it before. --reconfigure overrides and re-shows the page
    # so an operator can install additional families later.
    fonts_section = get_fonts_section(cfg)
    offer_fonts = args.reconfigure or not fonts_section.get("_decided")

    wizard = Wizard(outputs)
    result = wizard.run(offer_fonts=offer_fonts)
    if result is None:
        logger.warning("wizard cancelled")
        return 1
    layout, variant, timezone, touch_map, installed_fonts, fonts_decided = result
    set_input_section(cfg, layout, variant, touch_map)
    set_time_section(cfg, timezone)
    if fonts_decided:
        mark_fonts_decision_made(cfg)
        mark_fonts_installed(cfg, installed_fonts)
    save_config(cfg)

    # Apply timezone before the (potential) sway restart — set-timezone
    # survives the restart but there's no reason to make the user wait
    # for an extra tick with a stale clock.
    apply_timezone(timezone)

    if touch_map:
        try:
            write_quirks(touch_map)
        except subprocess.CalledProcessError as exc:
            logger.error("quirks helper failed: %s", exc)
            return 1
        try:
            restart_sway()
        except subprocess.CalledProcessError as exc:
            logger.error("sway restart failed: %s", exc)
            return 1
        # The restart will tear us down; return 0 as a courtesy.
        return 0

    apply_settings(cfg, i3, touchscreens)
    return 0


if __name__ == "__main__":
    sys.exit(main())
