#!/usr/bin/env python3
"""First-launch configurator for keyboard layout, timezone, and touchscreen mapping.

Autostarted by sway via /etc/sway/config.d/60-console-settings.conf. Reads
~/.config/console-settings.ini for the saved xkb layout/variant, system
timezone, and per-output touchscreen mapping. If complete and the stored
hardware is still present it pushes everything into sway via i3ipc (plus
timedatectl for the clock) and exits. Otherwise it opens a GTK3 wizard: a
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
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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

logger = logging.getLogger("console-settings")


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


# ---------- timezone ----------

def current_timezone() -> str:
    """Current system timezone as reported by timedatectl, or empty."""
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
    if not TIMEZONE_RE.match(timezone):
        logger.warning("invalid timezone %r; skipping", timezone)
        return
    if current_timezone() == timezone:
        return
    logger.info("setting timezone to %s", timezone)
    try:
        subprocess.run(
            ["timedatectl", "set-timezone", timezone],
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        logger.error("timedatectl set-timezone failed: %s", exc)


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
"""


class Wizard:
    """Two-stage GTK3 wizard: keyboard layout, then per-output touch map."""

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

    def run(self) -> Optional[Tuple[str, str, str, Dict[str, str]]]:
        """Return (layout, variant, timezone, touch_map) on success, None if cancelled."""
        if not self._run_keyboard_page():
            return None
        if not self._run_timezone_page():
            return None
        if self._outputs and not self._run_touch_calibration():
            return None
        self._completed = True
        return (
            self._selected_layout,
            self._selected_variant,
            self._selected_timezone,
            self._touch_map,
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

    wizard = Wizard(outputs)
    result = wizard.run()
    if result is None:
        logger.warning("wizard cancelled")
        return 1
    layout, variant, timezone, touch_map = result
    set_input_section(cfg, layout, variant, touch_map)
    set_time_section(cfg, timezone)
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
