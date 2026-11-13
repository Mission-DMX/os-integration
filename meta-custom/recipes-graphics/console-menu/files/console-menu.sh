#!/bin/sh
# Waybar-triggered session menu. sway runs as an unprivileged user
# (see mdmx-user + sway.service), so this is how the operator reaches
# lock/reboot/shutdown without a keyboard.
#
# Powered by fuzzel --dmenu, matching the visual style of
# application-launcher so the operator sees a consistent overlay.

LOGFILE=/tmp/console-menu.log

log() {
    printf '%s %s\n' "$(date +%FT%T)" "$*" >>"$LOGFILE"
}

log "invoked (pid=$$)"

# swaymsg exec inherits sway's env; keep fallbacks for out-of-band runs.
: "${XDG_RUNTIME_DIR:=/run/sway}"
: "${WAYLAND_DISPLAY:=wayland-1}"
export XDG_RUNTIME_DIR WAYLAND_DISPLAY

# Guard against a stale fuzzel instance (application-launcher uses the
# same pkill trick — they share the fuzzel binary but not the config).
if pgrep -x fuzzel >/dev/null 2>&1; then
    log "existing fuzzel found — killing"
    pkill -x fuzzel 2>/dev/null
    sleep 0.1
fi

# mdmx-updater writes ~/.cache/mdmx-updater/pending.json after a
# successful download+verify. Show the install entry only when that
# marker is present, so the menu doesn't advertise an action that would
# immediately fail with "no pending update".
UPDATE_MARKER="${HOME:-/home/user}/.cache/mdmx-updater/pending.json"

entries="Lock Screen
Change PIN"
if [ -f "$UPDATE_MARKER" ]; then
    ts=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('build_timestamp',''))" "$UPDATE_MARKER" 2>/dev/null || true)
    if [ -n "$ts" ]; then
        entries="$entries
Install Update ($ts)"
    else
        entries="$entries
Install Update"
    fi
fi
entries="$entries
Reboot
Shutdown
Cancel"

choice=$(printf '%s\n' "$entries" \
  | /usr/bin/fuzzel --dmenu \
        --config=/etc/console-menu/fuzzel.ini \
        --prompt='> ')
rc=$?
log "fuzzel exited rc=$rc choice='$choice'"

case "$choice" in
    "Lock Screen")
        exec /usr/bin/console-lock
        ;;
    "Change PIN")
        exec /usr/bin/console-lock --change-pin
        ;;
    "Install Update"*)
        log "update install requested"
        # Hand off to the GUI installer. It takes exclusive control of
        # the compositor via gtk-session-lock (same mechanism as
        # console-lock), so a second waybar tap can't trigger a parallel
        # install, shows progress parsed from rauc(1)'s stdout, and
        # reboots into the new slot on success. pkexec elevation and
        # the polkit-whitelisted install helper stay the same —
        # mdmx-update-installer is the user-facing wrapper around them.
        exec /usr/bin/mdmx-update-installer
        ;;
    "Reboot")
        log "reboot requested"
        exec /bin/systemctl reboot
        ;;
    "Shutdown")
        log "poweroff requested"
        exec /bin/systemctl poweroff
        ;;
    *)
        exit 0
        ;;
esac
