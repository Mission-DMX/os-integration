#!/usr/bin/env python3
"""Touch-friendly PIN screen locker using ext-session-lock-v1.

Uses gtk-session-lock, which wraps the Wayland ``ext-session-lock-v1``
protocol. The compositor takes over the display: normal clients are
hidden, every output gets a lock surface owned by this process, and the
session stays locked even if this process crashes — only an
``ext_session_lock_v1.unlock_and_destroy`` request (or a new lock
client) can dismiss it. That closes the "kill the client / switch app"
bypass that gtk4-layer-shell allowed.

Expected PIN lives in ``~/.config/console-settings.ini`` under
``[lock] pin = ...``; a missing file falls back to ``0000`` so a freshly
provisioned unit can always be unlocked. ``--change-pin`` walks the
operator through current → new → confirm and rewrites the config
atomically (0600).
"""

import argparse
import configparser
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkSessionLock", "0.1")

from gi.repository import Gdk, GLib, Gtk, GtkSessionLock  # noqa: E402

CONFIG_PATH = Path.home() / ".config" / "console-settings.ini"
DEFAULT_PIN = "0000"
MIN_PIN_LENGTH = 4
MAX_PIN_LENGTH = 32


def load_pin() -> str:
    cfg = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        try:
            cfg.read(CONFIG_PATH)
        except configparser.Error:
            return DEFAULT_PIN
    return cfg.get("lock", "pin", fallback=DEFAULT_PIN)


def save_pin(new_pin: str) -> None:
    cfg = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        try:
            cfg.read(CONFIG_PATH)
        except configparser.Error:
            pass
    if not cfg.has_section("lock"):
        cfg.add_section("lock")
    cfg.set("lock", "pin", new_pin)

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replace so a crash mid-write can't leave a truncated file.
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


CSS = b"""
window { background-color: rgba(10, 10, 30, 0.98); }
label { color: #ffffff; }
label.prompt { font-size: 26px; }
label.display {
    font-size: 56px;
    letter-spacing: 14px;
    min-width: 340px;
    min-height: 72px;
}
label.error { color: #ff8080; }
button.padkey {
    font-size: 34px;
    min-width: 110px;
    min-height: 110px;
    background-image: none;
    background-color: #2d2d54;
    color: #ffffff;
    border-radius: 14px;
    border: 1px solid #6b8afd;
}
button.padkey:hover,
button.padkey:active { background-color: #4a63d6; }
button.backspace { background-color: #b34747; border-color: #ff8080; }
button.ok { background-color: #4a8a4a; border-color: #7ed957; }
"""


class Locker:
    """PIN pad driven by a real Wayland session lock.

    Stages:
      * ``unlock``  — normal unlock; correct PIN calls unlock_and_destroy.
      * ``current`` — first step of re-key; validates the old PIN.
      * ``new``     — pick the new PIN.
      * ``confirm`` — re-enter the new PIN; on match, write config & unlock.
    """

    def __init__(self, change_pin: bool) -> None:
        self._stage = "current" if change_pin else "unlock"
        self._entered = ""
        self._pending_new_pin: Optional[str] = None
        self._expected = load_pin()
        self._prompt_label: Optional[Gtk.Label] = None
        self._display_label: Optional[Gtk.Label] = None
        # Kept untyped because the introspected class name for
        # GtkSessionLockLock isn't worth pinning down in an annotation
        # that never leaves this file.
        self._lock = None

    def run(self) -> int:
        if not GtkSessionLock.is_supported():
            sys.stderr.write(
                "console-lock: compositor does not support "
                "ext_session_lock_v1\n"
            )
            return 1

        # Install CSS for the default screen before any windows are
        # realized, so the lock surfaces come up already styled.
        style = Gtk.CssProvider()
        style.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            style,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        self._lock = GtkSessionLock.prepare_lock()
        self._lock.connect("locked", self._on_locked)
        self._lock.connect("finished", self._on_finished)
        # Sends the lock request. The compositor either grants it (and
        # emits "locked") or refuses (emits "finished" — e.g. because
        # another lock client is already active).
        self._lock.lock_lock()

        display = Gdk.Display.get_default()
        # ext-session-lock requires one surface per output; without a
        # surface on every output the compositor keeps that output
        # blanked with no way to authenticate on it. Iterating over
        # every monitor also covers the single-touchscreen kiosk case.
        for i in range(display.get_n_monitors()):
            monitor = display.get_monitor(i)
            window = self._build_window(primary=(i == 0))
            self._lock.new_surface(window, monitor)
            window.show_all()

        Gtk.main()
        return 0

    # ---------- window construction ----------

    def _build_window(self, *, primary: bool) -> Gtk.Window:
        window = Gtk.Window()
        window.set_app_paintable(True)
        window.set_can_focus(True)

        outer = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=24,
        )
        outer.set_halign(Gtk.Align.CENTER)
        outer.set_valign(Gtk.Align.CENTER)

        if primary:
            prompt = Gtk.Label()
            prompt.get_style_context().add_class("prompt")
            outer.pack_start(prompt, False, False, 0)

            display_label = Gtk.Label(label="")
            display_label.get_style_context().add_class("display")
            outer.pack_start(display_label, False, False, 0)

            grid = Gtk.Grid()
            grid.set_row_spacing(16)
            grid.set_column_spacing(16)
            grid.set_halign(Gtk.Align.CENTER)
            for i, digit in enumerate("123456789"):
                grid.attach(self._pad_button(digit), i % 3, i // 3, 1, 1)
            grid.attach(self._pad_button("<", extra="backspace"), 0, 3, 1, 1)
            grid.attach(self._pad_button("0"), 1, 3, 1, 1)
            grid.attach(self._pad_button("OK", extra="ok"), 2, 3, 1, 1)
            outer.pack_start(grid, False, False, 0)

            self._prompt_label = prompt
            self._display_label = display_label
            self._update_prompt()
        else:
            # Secondary outputs get a blank "locked" surface so the
            # compositor keeps them blanked but visibly owned.
            info = Gtk.Label(label="Screen locked")
            info.get_style_context().add_class("prompt")
            outer.pack_start(info, False, False, 0)

        window.add(outer)
        window.connect("key-press-event", self._on_key)
        return window

    def _pad_button(
        self, label: str, extra: Optional[str] = None
    ) -> Gtk.Button:
        b = Gtk.Button(label=label)
        b.get_style_context().add_class("padkey")
        if extra:
            b.get_style_context().add_class(extra)
        # Buttons don't steal focus — otherwise Enter after a tap would
        # re-activate the button rather than submitting the PIN.
        b.set_can_focus(False)
        b.connect("clicked", self._on_click, label)
        return b

    # ---------- input handling ----------

    def _on_click(self, _btn: Gtk.Button, label: str) -> None:
        if label == "<":
            self._entered = self._entered[:-1]
        elif label == "OK":
            self._submit()
            return
        else:
            if len(self._entered) < MAX_PIN_LENGTH:
                self._entered += label
        self._refresh_display()

    def _on_key(self, _widget: Gtk.Widget, event: Gdk.EventKey) -> bool:
        keyval = event.keyval
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self._submit()
            return True
        if keyval == Gdk.KEY_BackSpace:
            self._entered = self._entered[:-1]
            self._refresh_display()
            return True
        if keyval == Gdk.KEY_Escape:
            # Esc only clears the buffer — it can never dismiss the lock.
            self._entered = ""
            self._refresh_display()
            return True
        name = Gdk.keyval_name(keyval) or ""
        # Accept keypad and top-row digits alike.
        if name.startswith("KP_") and name[3:].isdigit():
            name = name[3:]
        if name.isdigit() and len(self._entered) < MAX_PIN_LENGTH:
            self._entered += name
            self._refresh_display()
            return True
        return False

    # ---------- stage transitions ----------

    def _submit(self) -> None:
        entered = self._entered
        self._entered = ""
        self._refresh_display()

        if self._stage == "unlock":
            if entered == self._expected:
                self._finish()
            else:
                self._flash("Wrong PIN")
            return

        if self._stage == "current":
            if entered == self._expected:
                self._stage = "new"
                self._update_prompt()
            else:
                self._flash("Wrong PIN")
            return

        if self._stage == "new":
            if len(entered) < MIN_PIN_LENGTH:
                self._flash(f"PIN too short (min {MIN_PIN_LENGTH})")
                return
            self._pending_new_pin = entered
            self._stage = "confirm"
            self._update_prompt()
            return

        if self._stage == "confirm":
            if entered == self._pending_new_pin:
                try:
                    save_pin(entered)
                except OSError as exc:
                    self._flash(f"Save failed: {exc.strerror or 'error'}")
                    self._pending_new_pin = None
                    self._stage = "new"
                    return
                self._finish()
            else:
                self._pending_new_pin = None
                self._stage = "new"
                self._flash("Mismatch — try again")

    # ---------- UI helpers ----------

    def _refresh_display(self) -> None:
        if self._display_label is not None:
            self._display_label.set_label("●" * len(self._entered))

    def _update_prompt(self) -> None:
        prompts = {
            "unlock": "Enter PIN",
            "current": "Enter current PIN",
            "new": "Enter new PIN",
            "confirm": "Confirm new PIN",
        }
        if self._prompt_label is not None:
            self._prompt_label.get_style_context().remove_class("error")
            self._prompt_label.set_label(prompts[self._stage])

    def _flash(self, message: str) -> None:
        if self._prompt_label is None:
            return
        self._prompt_label.get_style_context().add_class("error")
        self._prompt_label.set_label(message)
        GLib.timeout_add(1500, self._restore_prompt)

    def _restore_prompt(self) -> bool:
        self._update_prompt()
        return False

    # ---------- session-lock lifecycle ----------

    def _finish(self) -> None:
        # unlock_and_destroy tells the compositor to release the session
        # lock. Sync the display before quitting so the unlock request
        # is actually flushed — without it GTK can exit while the
        # request is still queued client-side and the session stays
        # locked with no owner.
        if self._lock is not None:
            self._lock.unlock_and_destroy()
            display = Gdk.Display.get_default()
            if display is not None:
                display.sync()
        Gtk.main_quit()

    def _on_locked(self, _lock) -> None:
        # Intentionally empty — the surfaces are already up and the UI
        # is live. Kept so the "locked" signal is connected (some
        # compositors log warnings if it isn't).
        pass

    def _on_finished(self, _lock) -> None:
        # Compositor refused the lock (another lock owner, protocol
        # mismatch, …). No point falling back to a fake overlay: that
        # would just reintroduce the bypass we switched away from.
        sys.stderr.write(
            "console-lock: compositor sent 'finished' — not locking\n"
        )
        Gtk.main_quit()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--change-pin",
        action="store_true",
        help="prompt for a new PIN instead of unlocking",
    )
    args = parser.parse_args()
    return Locker(change_pin=args.change_pin).run()


if __name__ == "__main__":
    sys.exit(main())
