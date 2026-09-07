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

choice=$(printf '%s\n' \
    "Lock Screen" \
    "Change PIN" \
    "Reboot" \
    "Shutdown" \
    "Cancel" \
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
