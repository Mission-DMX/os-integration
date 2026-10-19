# sway-autostart

Boots the device directly into a Sway Wayland session on tty1, configures the
status bar and notification daemon, and brings up the audio stack that lives
alongside the graphical session.

## What this recipe ships

| Target path                                         | Source                       | Purpose                                            |
| --------------------------------------------------- | ---------------------------- | -------------------------------------------------- |
| `/lib/systemd/system/sway.service`                  | `sway.service`               | Autologin-less sway launch on tty1 as `user`.      |
| `/lib/systemd/system/pulseaudio.service`            | `pulseaudio.service`         | PulseAudio in `--system` mode as the `pulse` user. |
| `/etc/sway/config.d/40-mako.conf`                   | `40-mako.conf`               | Starts mako notification daemon from sway.         |
| `/etc/sway/config.d/50-waybar.conf`                 | `50-waybar.conf`             | Starts waybar from sway.                           |
| `/etc/sway/config.d/60-keybindings.conf`            | `60-keybindings.conf`        | Window-management keybindings + tabbed default.    |
| `/etc/sway/waybar/{config,style.css}`               | `waybar-{config,style.css}`  | Bar layout and theming.                            |
| `/etc/profile.d/sway-env.sh`                        | `sway-env.sh`                | Login-shell env for `swaymsg`/IPC access.          |
| `/etc/pulse/client.conf.d/50-system-server.conf`    | `50-system-server.conf`      | Points libpulse clients at the system socket.      |

Both `sway.service` and `pulseaudio.service` are enabled via `SYSTEMD_SERVICE` /
`SYSTEMD_AUTO_ENABLE=enable`.

## On-screen keyboard wiring (`osk-manager` + `wvkbd`)

`waybar-config` ships a `custom/osk` module in the right-hand group that
calls `/usr/bin/oskctl toggle`; `#custom-osk` in `waybar-style.css`
matches the look of the power button on the opposite end. `osk-manager`
itself (started from its own `/etc/sway/config.d/70-osk.conf` drop-in)
owns the actual `wvkbd-deskintl` process. Those live in the dedicated
`osk-manager` and `wvkbd` recipes; sway-autostart just pulls them in via
RDEPENDS and renders the tray button.

## Audio stack notes

PulseAudio runs in `--system` mode, not per-user:

* **Why `--system`.** The graphical session is a single-user kiosk (`user`,
  uid 1000). A per-user daemon is managed by the user's `systemd --user`
  instance, which is in turn tied to a logind session. The sway service here
  intentionally does *not* go through pam_systemd (sway.service uses seatd
  directly and sets `XDG_RUNTIME_DIR=/run/sway`, not `/run/user/1000`), so no
  `systemd --user` is around to supervise a per-user pulseaudio. System mode
  side-steps the whole chain.

* **Why a dedicated systemd unit.** `--system` requires the daemon to be
  invoked as root so it can drop privileges to the `pulse` system user that
  poky's pulseaudio-server recipe creates. Starting it from sway's config via
  `exec` (a previous attempt, kept as `30-pulseaudio.conf` for reference)
  does not work because sway.service runs as `User=user` and pulseaudio
  refuses the non-root `--system` launch.

* **Why the client.conf.d drop-in.** libpulse's default search order checks
  `$XDG_RUNTIME_DIR/pulse/native` first. Under sway that resolves to
  `/run/sway/pulse/native`, which doesn't exist — the real socket lives at
  `/var/run/pulse/native` because the daemon is in system mode. The drop-in
  sets `default-server = unix:/var/run/pulse/native` and `autospawn = no`.
  libpulse supports `client.conf.d/*.conf` (via `pa_config_parse(...,
  use_dot_d=true, ...)` in `src/pulse/client-conf.c`).

* **Access group.** The upstream pulseaudio recipe is built with
  `-Daccess_group=audio`, so the native socket is owned by `pulse:audio` with
  group-read/write. The `user` account is a member of `audio` (added by
  `mdmx-user`), which is the sole permission requirement for `pactl` et al.

## Verifying on a running image

```sh
systemctl status pulseaudio.service          # should be active (running) as root → pulse
ls -l /var/run/pulse/native                  # srw-rw---- pulse audio
sudo -u user XDG_RUNTIME_DIR=/run/sway pactl info
```

The third command should print server info, not "Connection refused".
