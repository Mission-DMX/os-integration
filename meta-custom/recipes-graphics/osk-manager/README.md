# osk-manager

Lifecycle manager and control surface for the kiosk's on-screen
keyboard. `osk-manager` owns the `wvkbd-deskintl` process; `oskctl` is
the one-shot client that waybar's tray module and the sway `$mod+k`
keybinding talk to.

## What this recipe ships

| Target path                               | Source            | Purpose                                                           |
| ----------------------------------------- | ----------------- | ----------------------------------------------------------------- |
| `/usr/bin/osk-manager`                    | `osk-manager.py`  | Daemon that spawns wvkbd and listens on the control socket.       |
| `/usr/bin/oskctl`                         | `oskctl`          | CLI client — `show`, `hide`, `toggle`, `status`.                  |
| `/etc/sway/config.d/70-osk.conf`          | `70-osk.conf`     | Autostarts `osk-manager`; binds `$mod+k` to `oskctl toggle`.      |

## Behaviour

### Hardware-keyboard-dependent flags

`osk-manager` chooses the `wvkbd` invocation flags based on live
udev state:

* **No physical keyboard connected** → `wvkbd-deskintl --hidden --auto`.
  `--auto` makes wvkbd bind `zwp_input_method_v2` and show/hide itself
  from compositor focus events, which is what makes "tap a text field,
  OSK pops open" work on wlroots-based compositors.

* **Physical keyboard connected** → `wvkbd-deskintl --hidden`.
  `--auto` is deliberately dropped. With a hardware keyboard, the OSK
  only comes up when the user asks for it via the waybar button or the
  `$mod+k` binding; it does *not* pop open on every focused field.

The `--auto` flag can only be set at startup, so a change in the
hardware-keyboard set forces a wvkbd respawn. The udev monitor coalesces
events over `UDEV_DEBOUNCE_SEC` (400 ms) before rescanning — USB
keyboards announce themselves across several `input*` child devices
over ~100 ms, and a per-event respawn would blink the OSK every time.

### Hardware-keyboard detection

The daemon counts a device as a physical keyboard when udev's
`ID_INPUT_KEYBOARD=1` property is set on an `input` (parent) node.
That property is attached by systemd's `input_id` builtin only when the
device advertises a sufficiently complete alphanumeric key range — power
buttons, lid switches, and touchscreens all have `EV_KEY` but none of
them trip the flag, so this is a reliable primitive for "did somebody
plug in a real keyboard?" without hand-rolling an evdev capability walk.

Wayland `zwp_virtual_keyboard_v1` surfaces (wvkbd included) never
materialize as `/dev/input/*` nodes, so no extra filter is needed to
exclude the OSK from counting itself.

### Control socket

`osk-manager` creates `$XDG_RUNTIME_DIR/osk.sock` (mode 0660,
user:usergroup) and accepts single-line commands:

| Command | wvkbd signal   | Effect                                 |
| ------- | -------------- | -------------------------------------- |
| `show`  | SIGUSR2        | Force the keyboard visible.            |
| `hide`  | SIGUSR1        | Force the keyboard hidden.             |
| `toggle`| SIGRTMIN       | Toggle visibility.                     |
| `status`| —              | Reply with daemon/wvkbd state as JSON. |

Replies are always one JSON line (`{"ok": true, ...}`), so `oskctl`
re-emits them unchanged for easy consumption from waybar or scripts.

If wvkbd has died by the time a signal arrives (OOM, user-sent
`pkill`, upstream crash), the signal path transparently respawns it
and retries once. This is the single point of recovery for an
unexpected wvkbd exit; the main loop additionally watchdogs the
process every second and respawns if `poll()` reports an exit.

### Why not a systemd unit

sway starts as `User=user` through `sway.service` and sets
`XDG_RUNTIME_DIR=/run/sway` directly, bypassing `pam_systemd` and
therefore the per-user `systemd --user` instance (see the audio-stack
notes in `sway-autostart/README.md` for the full chain). Launching
`osk-manager` from `/etc/sway/config.d/70-osk.conf` keeps it inside the
sway session so `$XDG_RUNTIME_DIR`, `$WAYLAND_DISPLAY`, and the login
user's input-group membership are all already set — the same reason
mako, waybar, and console-settings-daemon are started via sway's
config.d rather than a systemd user unit.

## Verifying on a running image

```sh
# Daemon up?
pgrep -af osk-manager          # should show the Python invocation
ls -l "$XDG_RUNTIME_DIR"/osk.sock   # 0660 user:user

# Does the signal path work?
oskctl status                  # prints {"ok": true, "hw_keyboard": …, …}
oskctl toggle                  # keyboard should blink in/out
oskctl show; oskctl hide

# Does hw-kbd detection react?
# Plug in a USB keyboard — pgrep -af wvkbd should respawn without --auto;
# unplug — it should come back with --auto.
```

If `oskctl status` reports `wvkbd_running: false` despite the daemon
being up, re-check the `wvkbd` RDEPENDS: the daemon aborts at startup
if `wvkbd-deskintl` is not on `$PATH`, so this most often means the
`wvkbd` recipe failed to install.
