#!/usr/bin/python3
"""
fish-monitor - supervise the realtime-fish daemon.

Runs inside a foot terminal (app_id=fish-terminal). Spawns fish, forwards
stdout/stderr to the containing terminal, watches for exit, and on crash
cleans up leftover sockets and restarts. A JSON status file at
$XDG_RUNTIME_DIR/fish-monitor/status.json is written for waybar to
consume via its custom module. A libnotify notification is sent whenever
fish crashes.
"""

import glob
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

FISH_BIN = "/usr/bin/fish"
FISH_SOCKET_GLOB = "/tmp/fish.sock*"
# Sway runs as the unprivileged `user`, so /run/fish-monitor isn't
# writable (root-owned tmpfs). $XDG_RUNTIME_DIR is per-user, gets set
# up by the sway service (RuntimeDirectory=sway → /run/sway) and is
# already the mount point waybar's custom/fish exec block reads from.
# Fall back to /tmp only if XDG_RUNTIME_DIR is unset (headless / debug).
_RUNTIME_DIR = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
STATUS_DIR = Path(_RUNTIME_DIR) / "fish-monitor"
STATUS_FILE = STATUS_DIR / "status.json"
RESTART_DELAY_SECONDS = 3


def write_status(state: str, detail: str = "") -> None:
    """Write a waybar-consumable JSON status snapshot."""
    labels = {
        "starting": (" ", "starting", "Fish: starting"),
        "running":  (" ", "running",  "Fish: running"),
        "crashed":  (" ", "crashed",  f"Fish crashed: {detail}"),
        "stopped":  (" ", "stopped",  "Fish: stopped"),
    }
    text, css_class, tooltip = labels.get(state, (" ", "unknown", "Fish: ?"))
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    STATUS_FILE.write_text(json.dumps({
        "text": text,
        "class": css_class,
        "tooltip": tooltip,
    }))


def cleanup_sockets() -> None:
    for path in glob.glob(FISH_SOCKET_GLOB):
        try:
            os.unlink(path)
            print(f"[fish-monitor] removed stale {path}", flush=True)
        except OSError as exc:
            print(f"[fish-monitor] could not remove {path}: {exc}",
                  file=sys.stderr, flush=True)


def notify(summary: str, body: str = "") -> None:
    try:
        subprocess.run(
            ["notify-send", "--urgency=critical", "--app-name=fish-monitor",
             summary, body],
            check=False, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        print(f"[fish-monitor] notify-send unavailable: {exc}",
              file=sys.stderr, flush=True)


def main() -> int:
    child: subprocess.Popen | None = None

    def _shutdown(signum, _frame):
        print(f"[fish-monitor] received signal {signum}, shutting down",
              flush=True)
        if child and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
        write_status("stopped")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    while True:
        cleanup_sockets()
        write_status("starting")
        print(f"[fish-monitor] starting {FISH_BIN}", flush=True)

        try:
            child = subprocess.Popen([FISH_BIN])
        except FileNotFoundError:
            write_status("crashed", f"{FISH_BIN} not installed")
            notify("Fish not installed",
                   f"{FISH_BIN} was not found; retrying in "
                   f"{RESTART_DELAY_SECONDS}s")
            time.sleep(RESTART_DELAY_SECONDS)
            continue

        write_status("running")
        rc = child.wait()

        if rc == 0:
            write_status("stopped")
            print("[fish-monitor] fish exited normally", flush=True)
            try:
                input("\nFish exited. Press ENTER to restart, "
                      "or Ctrl+D to quit: ")
            except EOFError:
                print("", flush=True)
                return 0
            continue

        write_status("crashed", f"exit code {rc}")
        print(f"[fish-monitor] fish crashed with exit code {rc}",
              file=sys.stderr, flush=True)
        notify("Fish crashed",
               f"realtime-fish exited with code {rc}. "
               f"Restarting in {RESTART_DELAY_SECONDS}s.")
        time.sleep(RESTART_DELAY_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
