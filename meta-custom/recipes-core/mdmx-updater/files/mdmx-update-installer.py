#!/usr/bin/env python3
"""Full-screen RAUC update installer with progress + auto-reboot.

Launched by the console menu's "Install Update" entry as the desktop
user. Uses gtk-session-lock (ext-session-lock-v1) to take exclusive
control of the compositor — the same mechanism console-lock uses — so
no waybar click, keybinding, or incoming app can reach the system
while the install runs. The compositor keeps that lock in place even
if this process crashes, which closes the "trigger another install by
tapping waybar again" race the user hit before.

Progress bar + status line track `rauc install`'s own `  NN% message`
output format (parsed from the install helper's stdout). On success
the dialog does a short countdown and then `systemctl reboot`s into
the newly-written slot. On failure the user gets an "OK" button that
unlocks the session so they can see the error and try again.
"""

from __future__ import annotations

import re
import subprocess
import sys
import threading
from typing import Optional

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkSessionLock", "0.1")

from gi.repository import Gdk, GLib, Gtk, GtkSessionLock  # noqa: E402

# The pkexec-wrapped RAUC install trampoline. 50-mdmx-updater.rules
# already whitelists this exact path for the `user` subject, so the
# user can run it without a password prompt.
INSTALL_HELPER = "/usr/libexec/mdmx-updater/mdmx-updater-install"

# Match "  10% Determining slot states done." lines from rauc(1).
PROGRESS_RE = re.compile(r"^\s*(\d{1,3})%\s+(.+?)\s*$")

REBOOT_COUNTDOWN = 5

CSS = b"""
window { background-color: rgba(10, 10, 30, 0.98); }
label { color: #ffffff; }
label.title { font-size: 36px; font-weight: bold; margin-bottom: 20px; }
label.status { font-size: 22px; margin-top: 12px; }
label.error {
    color: #ff8080;
    font-size: 16px;
    margin-top: 16px;
}
progressbar {
    min-height: 30px;
    min-width: 640px;
}
progressbar trough {
    background-color: #2d2d54;
    border-radius: 4px;
    border: 1px solid #6b8afd;
}
progressbar progress {
    background-color: #4a63d6;
    border-radius: 4px;
}
button.ok {
    font-size: 24px;
    min-width: 200px;
    min-height: 70px;
    background-image: none;
    background-color: #4a8a4a;
    color: #ffffff;
    border-radius: 14px;
    border: 1px solid #7ed957;
    margin-top: 28px;
}
button.ok:hover,
button.ok:active { background-color: #5aa35a; }
expander { color: #cccccc; font-size: 16px; margin-top: 24px; }
expander > title { padding: 4px 8px; }
scrolledwindow.log { border: 1px solid #3a3a5a; border-radius: 6px; background-color: #0a0a1e; }
textview, textview text {
    font-family: monospace;
    font-size: 13px;
    background-color: #0a0a1e;
    color: #d0d0d0;
}
"""


class Installer:
    def __init__(self) -> None:
        self._lock = None
        self._title: Optional[Gtk.Label] = None
        self._status: Optional[Gtk.Label] = None
        self._progress: Optional[Gtk.ProgressBar] = None
        self._error: Optional[Gtk.Label] = None
        self._ok_button: Optional[Gtk.Button] = None
        self._countdown = REBOOT_COUNTDOWN
        self._last_error_line = ""
        # Shared log buffer, driven live by stdout and rendered in the
        # "Show log" expander on the primary surface. Kept as a Gtk
        # TextBuffer (not a plain list) so new lines appear instantly
        # when the expander is open — no manual copy step.
        self._log_buffer: Optional[Gtk.TextBuffer] = None
        self._log_view: Optional[Gtk.TextView] = None

    def run(self) -> int:
        if not GtkSessionLock.is_supported():
            sys.stderr.write(
                "mdmx-update-installer: compositor does not support "
                "ext_session_lock_v1\n"
            )
            return 1

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
        self._lock.lock_lock()

        display = Gdk.Display.get_default()
        # One surface per output, same as console-lock: without that the
        # compositor keeps non-primary outputs blanked but with no way
        # to receive input, which looks broken on multi-head.
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

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        outer.set_halign(Gtk.Align.CENTER)
        outer.set_valign(Gtk.Align.CENTER)

        if primary:
            title = Gtk.Label(label="Installing update")
            title.get_style_context().add_class("title")
            outer.pack_start(title, False, False, 0)

            progress = Gtk.ProgressBar()
            progress.set_fraction(0.0)
            outer.pack_start(progress, False, False, 0)

            status = Gtk.Label(label="Starting install…")
            status.get_style_context().add_class("status")
            status.set_line_wrap(True)
            status.set_max_width_chars(80)
            outer.pack_start(status, False, False, 0)

            error = Gtk.Label(label="")
            error.get_style_context().add_class("error")
            error.set_line_wrap(True)
            error.set_max_width_chars(80)
            outer.pack_start(error, False, False, 0)

            ok_button = Gtk.Button(label="OK")
            ok_button.get_style_context().add_class("ok")
            # Keep hidden until we actually have a failure the operator
            # has to acknowledge. set_no_show_all so show_all() in run()
            # doesn't surface it prematurely.
            ok_button.set_no_show_all(True)
            ok_button.connect("clicked", self._on_ok_clicked)
            outer.pack_start(ok_button, False, False, 0)

            # Collapsible log viewer. Lives in an Expander so the main
            # status surface stays uncluttered; the operator opens it
            # on demand (hence the "Show log" label) to see the full
            # rauc output in real time. Buffer is shared across build
            # so appending from _handle_line updates whatever the user
            # is viewing without any extra plumbing.
            log_buffer = Gtk.TextBuffer()
            log_view = Gtk.TextView.new_with_buffer(log_buffer)
            log_view.set_editable(False)
            log_view.set_cursor_visible(False)
            log_view.set_monospace(True)
            log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)

            scrolled = Gtk.ScrolledWindow()
            scrolled.get_style_context().add_class("log")
            scrolled.set_policy(
                Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC
            )
            scrolled.set_size_request(840, 320)
            scrolled.add(log_view)

            expander = Gtk.Expander(label="Show log")
            expander.set_expanded(False)
            expander.add(scrolled)
            outer.pack_start(expander, False, False, 0)

            self._title = title
            self._status = status
            self._progress = progress
            self._error = error
            self._ok_button = ok_button
            self._log_buffer = log_buffer
            self._log_view = log_view
        else:
            info = Gtk.Label(label="Installing update…")
            info.get_style_context().add_class("title")
            outer.pack_start(info, False, False, 0)

        window.add(outer)
        return window

    # ---------- signals ----------

    def _on_locked(self, _lock) -> None:
        # Compositor accepted the lock request — safe to start the
        # install subprocess now. Starting it before the lock takes
        # could let input reach the previously-focused window during
        # the race.
        threading.Thread(target=self._install_thread, daemon=True).start()

    def _on_finished(self, _lock) -> None:
        # Compositor refused the lock (another lock client already in
        # control, likely a stale console-lock); nothing we can do.
        Gtk.main_quit()

    # ---------- install subprocess ----------

    def _install_thread(self) -> None:
        try:
            proc = subprocess.Popen(
                ["/usr/bin/pkexec", INSTALL_HELPER],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                text=True,
            )
        except OSError as exc:
            GLib.idle_add(self._on_done, 127, f"failed to launch pkexec: {exc}")
            return

        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip()
            if not line:
                continue
            GLib.idle_add(self._handle_line, line)

        rc = proc.wait()
        GLib.idle_add(self._on_done, rc, "")

    def _handle_line(self, line: str) -> bool:
        # Every line, progress or not, feeds the "Show log" view. This
        # mirrors what gets persisted to /var/log/update.log by the
        # install helper, so the on-demand viewer and the file stay in
        # sync without extra sync code.
        self._append_log(line)

        m = PROGRESS_RE.match(line)
        if m:
            pct = int(m.group(1))
            msg = m.group(2)
            if self._progress is not None:
                self._progress.set_fraction(min(pct, 100) / 100.0)
            if self._status is not None:
                self._status.set_text(msg)
        else:
            # Non-progress line: capture if it smells like an error so we
            # can surface it when the install exits non-zero. Keep only
            # the most recent such line; rauc emits a final `LastError:`
            # that strictly supersedes earlier chatter.
            lowered = line.lower()
            if "lasterror:" in lowered or "failed" in lowered or "error" in lowered:
                self._last_error_line = line
        return False

    def _append_log(self, line: str) -> None:
        buf = self._log_buffer
        view = self._log_view
        if buf is None or view is None:
            return
        end = buf.get_end_iter()
        buf.insert(end, line + "\n")
        # Keep the view pinned to the latest line so the operator sees
        # live output when they open the expander. A transient mark
        # lets scroll_mark_onscreen work even if the TextView isn't
        # currently allocated (expander collapsed) — GTK remembers the
        # position and applies it the next time the view lays out.
        mark = buf.create_mark(None, buf.get_end_iter(), False)
        view.scroll_mark_onscreen(mark)
        buf.delete_mark(mark)

    def _on_done(self, rc: int, launch_err: str) -> bool:
        if rc == 0:
            if self._title is not None:
                self._title.set_text("Update installed")
            if self._progress is not None:
                self._progress.set_fraction(1.0)
            if self._status is not None:
                self._status.set_text(
                    f"Rebooting into the new slot in {self._countdown}s…"
                )
            GLib.timeout_add_seconds(1, self._tick_countdown)
        else:
            if self._title is not None:
                self._title.set_text("Update failed")
            if self._status is not None:
                self._status.set_text(f"Installer exited with code {rc}.")
            if self._error is not None:
                detail = launch_err or self._last_error_line or \
                    "No further detail available from rauc."
                self._error.set_text(detail)
            if self._ok_button is not None:
                self._ok_button.set_no_show_all(False)
                self._ok_button.show()
        return False

    def _tick_countdown(self) -> bool:
        self._countdown -= 1
        if self._countdown <= 0:
            # Fire and forget — we're about to be killed by systemd.
            subprocess.Popen(["/bin/systemctl", "reboot"])
            return False
        if self._status is not None:
            self._status.set_text(
                f"Rebooting into the new slot in {self._countdown}s…"
            )
        return True

    def _on_ok_clicked(self, _btn: Gtk.Button) -> None:
        if self._lock is not None:
            self._lock.unlock_and_destroy()


def main() -> int:
    return Installer().run()


if __name__ == "__main__":
    sys.exit(main())
