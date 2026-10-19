#!/usr/bin/env python3
"""osk-manager — on-screen-keyboard lifecycle manager for sway.

Owns the wvkbd-deskintl process on behalf of the kiosk's graphical
session. Three responsibilities:

* Decide wvkbd's startup flags from live hardware state. When no
  hardware keyboard is connected we add `--auto` so wvkbd binds
  zwp_input_method_v2 and auto-pops open on text-input focus. When a
  hardware keyboard is connected `--auto` is dropped — the keyboard
  only appears when the user asks for it via tray/binding.

* Respawn wvkbd whenever the hardware-keyboard set changes, since the
  `--auto` flag can only be set at startup. A pyudev monitor on the
  `input` subsystem fires on add/remove; after settling for a short
  debounce we rescan and, if the "any keyboard present" bit flipped,
  SIGTERM the running wvkbd and launch a new one.

* Expose a Unix socket (`$XDG_RUNTIME_DIR/osk.sock`) accepting one-shot
  commands — `show`, `hide`, `toggle`, `status`. The waybar tray
  module and the sway `$mod+k` binding both lower to `oskctl` calls
  that write to this socket. Commands translate to wvkbd signals
  (SIGUSR2/SIGUSR1/SIGRTMIN per wvkbd(1)).
"""

from __future__ import annotations

import errno
import json
import logging
import os
import shutil
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pyudev

# Signals wvkbd 0.20 handles — reproduced here so the mapping is in one
# place and so swapping the OSK binary later only has to touch this
# section plus WVKBD_BIN.
WVKBD_BIN = "wvkbd-deskintl"
WVKBD_SIG_HIDE = signal.SIGUSR1
WVKBD_SIG_SHOW = signal.SIGUSR2
WVKBD_SIG_TOGGLE = signal.SIGRTMIN

# How long to coalesce udev events before deciding whether the keyboard
# set actually changed. USB keyboards announce themselves across several
# input* nodes (one per logical sub-device) over ~100 ms; without a
# debounce we'd thrash wvkbd on every single add.
UDEV_DEBOUNCE_SEC = 0.4

# How long to wait for wvkbd to exit after SIGTERM before escalating to
# SIGKILL during a respawn.
WVKBD_TERM_TIMEOUT = 2.0


def socket_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime:
        # sway.service sets XDG_RUNTIME_DIR=/run/sway (see sway-env.sh);
        # fall back to that if we were launched outside the session.
        runtime = "/run/sway"
    return Path(runtime) / "osk.sock"


def _device_is_hardware_keyboard(device: pyudev.Device) -> bool:
    """Does this udev device look like a physical keyboard?

    `ID_INPUT_KEYBOARD=1` is set by systemd's input_id builtin when the
    device advertises a sufficiently complete alphanumeric key range —
    power buttons, lid switches, and touchscreens all have EV_KEY but
    none of them trip this flag. That makes it the right primitive for
    "did somebody plug in a real keyboard?".

    Wayland `zwp_virtual_keyboard_v1` surfaces (wvkbd included) never
    materialize as /dev/input nodes, so no extra filter is needed to
    exclude the OSK itself.
    """
    if device.get("ID_INPUT_KEYBOARD") != "1":
        return False
    # The input subsystem advertises both the `input` parent device
    # (bookkeeping) and the `event*` child; we only want to count the
    # parent so a single physical keyboard contributes one hit.
    devname = device.get("DEVNAME", "") or ""
    if devname and "/event" in devname:
        return False
    return True


def any_hardware_keyboard(ctx: pyudev.Context) -> bool:
    for device in ctx.list_devices(subsystem="input"):
        if _device_is_hardware_keyboard(device):
            return True
    return False


@dataclass
class WvkbdState:
    proc: Optional[subprocess.Popen] = None
    hw_kbd_present: bool = False


class OSKManager:
    def __init__(self) -> None:
        self.state = WvkbdState()
        # Guards every mutation of self.state so the udev thread, the
        # socket thread, and the main thread don't race on respawn.
        self.lock = threading.RLock()
        self.ctx = pyudev.Context()
        self.stop_event = threading.Event()
        self._debounce_timer: Optional[threading.Timer] = None

    # ---------- wvkbd lifecycle ----------

    def _wvkbd_args(self, hw_kbd_present: bool) -> list[str]:
        args = [WVKBD_BIN, "--hidden"]
        if not hw_kbd_present:
            # --auto makes wvkbd bind zwp_input_method_v2 and show/hide
            # with text-input focus. Only enabled when there's no real
            # keyboard — otherwise typing on the physical keyboard also
            # bounces the OSK up on every focused field.
            args.append("--auto")
        return args

    def _spawn_wvkbd(self, hw_kbd_present: bool) -> None:
        args = self._wvkbd_args(hw_kbd_present)
        logging.info("spawning wvkbd: %s", " ".join(args))
        # start_new_session=True puts wvkbd in its own process group so
        # if osk-manager is foregrounded in a shell for debugging a
        # Ctrl-C doesn't propagate into wvkbd.
        self.state.proc = subprocess.Popen(args, start_new_session=True)
        self.state.hw_kbd_present = hw_kbd_present

    def _reap_wvkbd(self) -> None:
        proc = self.state.proc
        if proc is None:
            return
        if proc.poll() is not None:
            # Already dead; just forget it.
            self.state.proc = None
            return
        logging.info("terminating wvkbd pid=%d", proc.pid)
        proc.terminate()
        try:
            proc.wait(timeout=WVKBD_TERM_TIMEOUT)
        except subprocess.TimeoutExpired:
            logging.warning("wvkbd pid=%d did not exit; sending SIGKILL", proc.pid)
            proc.kill()
            proc.wait()
        self.state.proc = None

    def _ensure_running(self) -> subprocess.Popen:
        """Return a live wvkbd Popen, respawning if the previous one died.

        wvkbd can exit on its own (OOM, assertion, user-sent SIGTERM via
        pkill) — a show/hide/toggle request that arrives in that gap
        would silently drop otherwise. This is the signal path's single
        point of recovery.
        """
        proc = self.state.proc
        if proc is None or proc.poll() is not None:
            if proc is not None:
                logging.warning("wvkbd exited unexpectedly (rc=%s); respawning",
                                proc.returncode)
            self._spawn_wvkbd(self.state.hw_kbd_present)
            # Give wvkbd a moment to install its SIGUSR handlers before
            # the caller signals it; without this the first show/toggle
            # after an unexpected exit races and gets lost.
            time.sleep(0.1)
        return self.state.proc  # type: ignore[return-value]

    def _signal_wvkbd(self, sig: signal.Signals) -> bool:
        with self.lock:
            proc = self._ensure_running()
            try:
                proc.send_signal(sig)
                return True
            except ProcessLookupError:
                logging.warning("wvkbd disappeared mid-signal; respawning")
                self.state.proc = None
                proc = self._ensure_running()
                try:
                    proc.send_signal(sig)
                    return True
                except ProcessLookupError:
                    return False

    # ---------- hardware-keyboard tracking ----------

    def _rescan_and_reconfigure(self) -> None:
        """Called from the debounce timer after udev events settle."""
        with self.lock:
            present = any_hardware_keyboard(self.ctx)
            if present == self.state.hw_kbd_present and self.state.proc is not None:
                logging.debug("hw-kbd state unchanged (present=%s); nothing to do",
                              present)
                return
            logging.info("hw-kbd state transition: %s -> %s",
                         self.state.hw_kbd_present, present)
            self._reap_wvkbd()
            self._spawn_wvkbd(present)

    def _schedule_rescan(self) -> None:
        with self.lock:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
            self._debounce_timer = threading.Timer(
                UDEV_DEBOUNCE_SEC, self._rescan_and_reconfigure
            )
            self._debounce_timer.daemon = True
            self._debounce_timer.start()

    def _udev_loop(self) -> None:
        monitor = pyudev.Monitor.from_netlink(self.ctx)
        monitor.filter_by(subsystem="input")
        monitor.start()
        logging.info("udev monitor started")
        for device in iter(monitor.poll, None):
            if self.stop_event.is_set():
                break
            action = device.action or ""
            if action not in ("add", "remove"):
                continue
            # Keyboard parent device changes typically also set
            # ID_INPUT_KEYBOARD on the add; on remove the property is
            # already gone, so just unconditionally rescan on any input
            # add/remove and let the debounced rescan decide.
            self._schedule_rescan()

    # ---------- control socket ----------

    def _handle_command(self, cmd: str) -> dict:
        if cmd == "show":
            ok = self._signal_wvkbd(WVKBD_SIG_SHOW)
            return {"ok": ok}
        if cmd == "hide":
            ok = self._signal_wvkbd(WVKBD_SIG_HIDE)
            return {"ok": ok}
        if cmd == "toggle":
            ok = self._signal_wvkbd(WVKBD_SIG_TOGGLE)
            return {"ok": ok}
        if cmd == "status":
            with self.lock:
                proc = self.state.proc
                return {
                    "ok": True,
                    "hw_keyboard": self.state.hw_kbd_present,
                    "wvkbd_running": proc is not None and proc.poll() is None,
                    "wvkbd_pid": proc.pid if proc else None,
                }
        return {"ok": False, "error": f"unknown command: {cmd!r}"}

    def _socket_loop(self) -> None:
        sock_path = socket_path()
        sock_path.parent.mkdir(parents=True, exist_ok=True)
        # Clean up stale socket from a previous run — SOCK_STREAM Unix
        # sockets refuse to bind on top of an existing path.
        try:
            sock_path.unlink()
        except FileNotFoundError:
            pass
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(sock_path))
        # 0660 so other members of the login user's primary group can
        # ping it (future-proofing for a second UI client); 0666 would
        # let any system account toggle the OSK which is a surprise.
        os.chmod(sock_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP)
        srv.listen(8)
        srv.settimeout(1.0)
        logging.info("control socket listening at %s", sock_path)
        try:
            while not self.stop_event.is_set():
                try:
                    conn, _ = srv.accept()
                except socket.timeout:
                    continue
                with conn:
                    conn.settimeout(2.0)
                    try:
                        data = conn.recv(1024)
                    except socket.timeout:
                        continue
                    cmd = data.decode("utf-8", "replace").strip()
                    reply = self._handle_command(cmd)
                    try:
                        conn.sendall((json.dumps(reply) + "\n").encode("utf-8"))
                    except OSError:
                        pass
        finally:
            srv.close()
            try:
                sock_path.unlink()
            except FileNotFoundError:
                pass

    # ---------- top-level ----------

    def run(self) -> int:
        if shutil.which(WVKBD_BIN) is None:
            logging.error("%s not found on PATH; is the wvkbd recipe installed?",
                          WVKBD_BIN)
            return 1

        with self.lock:
            self._spawn_wvkbd(any_hardware_keyboard(self.ctx))

        # SIGTERM/SIGINT → clean shutdown. We don't trap SIGHUP; sway's
        # input-reconfigure path doesn't send one, and systemd (if we
        # ever get supervised there) uses SIGTERM by default.
        def _on_term(_signum, _frame):
            self.stop_event.set()

        signal.signal(signal.SIGTERM, _on_term)
        signal.signal(signal.SIGINT, _on_term)

        udev_thread = threading.Thread(target=self._udev_loop, daemon=True,
                                       name="osk-udev")
        sock_thread = threading.Thread(target=self._socket_loop, daemon=True,
                                       name="osk-socket")
        udev_thread.start()
        sock_thread.start()

        try:
            while not self.stop_event.wait(timeout=1.0):
                with self.lock:
                    proc = self.state.proc
                    if proc is not None and proc.poll() is not None:
                        logging.warning("wvkbd exited (rc=%s); respawning",
                                        proc.returncode)
                        self._spawn_wvkbd(self.state.hw_kbd_present)
        finally:
            logging.info("shutting down")
            with self.lock:
                if self._debounce_timer is not None:
                    self._debounce_timer.cancel()
                self._reap_wvkbd()
            sock_thread.join(timeout=2.0)
            # The udev thread blocks on monitor.poll(); closing the
            # context from under it is the cleanest way to unblock, but
            # Python's pyudev doesn't expose that. It's a daemon
            # thread, so leave it to exit with the process.
        return 0


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("OSK_MANAGER_LOG", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return OSKManager().run()


if __name__ == "__main__":
    sys.exit(main())
