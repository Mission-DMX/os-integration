#!/bin/sh
# Waybar-triggered launcher entry point. Kept out-of-band from
# /etc/xdg/fuzzel/fuzzel.ini so it doesn't collide with the upstream
# fuzzel recipe.

LOGFILE=/tmp/application-launcher.log

log() {
    printf '%s %s\n' "$(date +%FT%T)" "$*" >>"$LOGFILE"
}

log "invoked (pid=$$, tty=$(tty 2>/dev/null || echo none))"
log "env: WAYLAND_DISPLAY=$WAYLAND_DISPLAY XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR"

# Sway boots with XDG_RUNTIME_DIR=/run/sway (see sway.service) and
# WAYLAND_DISPLAY=wayland-1. When this script is invoked via `swaymsg
# exec` waybar's process env is bypassed and we get sway's ambient env
# instead, but keep the explicit fallbacks in case the operator ever
# invokes this outside sway's exec pipeline.
: "${XDG_RUNTIME_DIR:=/run/sway}"
: "${WAYLAND_DISPLAY:=wayland-1}"
export XDG_RUNTIME_DIR WAYLAND_DISPLAY

# Guard against double-tap re-opens by closing any existing instance
# before spawning a new one. -x matches exact process name; fuzzel exits
# on focus-loss so this is normally a no-op.
if pgrep -x fuzzel >/dev/null 2>&1; then
    log "existing fuzzel found — killing"
    pkill -x fuzzel 2>/dev/null
    # Give the compositor a moment to reap the layer-shell surface.
    sleep 0.1
fi

log "launching fuzzel"
/usr/bin/fuzzel --config=/etc/application-launcher/fuzzel.ini \
    >>"$LOGFILE" 2>&1
rc=$?
log "fuzzel exited rc=$rc"
exit $rc
