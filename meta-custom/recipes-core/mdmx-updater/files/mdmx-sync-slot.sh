#!/bin/sh
# mdmx-sync-slot: after a fresh update has booted successfully and been
# marked good, install the SAME RAUC bundle onto the other slot so both
# A and B end up carrying the current firmware version. This is the
# "both slots on current firmware" convergence step — after this runs
# the device has A == B == current, and the next scheduled update again
# writes to the inactive slot, reboots to validate, and only then
# brings the stale slot into line.
#
# Runs as a systemd oneshot after mdmx-bootcheck has handed off. Gates
# itself on three checks:
#   1) There IS a pending.json. No pending → nothing to do.
#   2) The pending bundle's build_timestamp matches /etc/mdmx-build-timestamp.
#      That proves we're the "just-booted-the-update" slot, not an
#      earlier version that happened to find a leftover marker.
#   3) The bundle file referenced by pending.json still exists on disk.
#
# Progress feedback is routed back to the running sway session via
# notify-send. We run as root from the systemd service, so wrap the
# notify calls with runuser(1) and pre-set DBUS_SESSION_BUS_ADDRESS /
# XDG_RUNTIME_DIR so libnotify finds the user's dbus daemon (runuser
# only switches identity, it does NOT seed environment for the target
# process; without these the notification silently goes nowhere).

set -eu

USER_NAME="user"
USER_UID=1000
USER_RUN="/run/user/${USER_UID}"
PENDING="/home/${USER_NAME}/.cache/mdmx-updater/pending.json"

log() { echo "mdmx-sync-slot: $*" >&2; }

if [ ! -f "$PENDING" ]; then
    log "no pending marker; nothing to do"
    exit 0
fi

# Resolve the three fields we care about via python3's json parser —
# ad-hoc sed/awk would choke on quoted paths that happen to contain the
# delimiter character. python3 is already a hard dep of mdmx-updater.
if ! bundle=$(python3 -c \
        "import json,sys; print(json.load(open(sys.argv[1]))['bundle_path'])" \
        "$PENDING" 2>/dev/null); then
    log "pending.json is malformed; clearing and bailing"
    rm -f "$PENDING"
    exit 0
fi
target_ts=$(python3 -c \
    "import json,sys; print(json.load(open(sys.argv[1]))['build_timestamp'])" \
    "$PENDING" 2>/dev/null || echo "")

current_ts=$(cat /etc/mdmx-build-timestamp 2>/dev/null || echo "")
if [ -z "$current_ts" ] || [ "$target_ts" != "$current_ts" ]; then
    log "pending targets '$target_ts' but current build is '$current_ts'; skipping"
    exit 0
fi

if [ ! -f "$bundle" ]; then
    log "bundle $bundle no longer exists; clearing marker"
    rm -f "$PENDING"
    exit 0
fi

notify() {
    # runuser -u $USER_NAME -- env ... notify-send ...
    # notify-send exits non-zero if the user's bus isn't up (e.g. they
    # haven't logged into sway yet); treat that as best-effort so an
    # unattended install still runs even without an active session.
    runuser -u "$USER_NAME" -- env \
        DBUS_SESSION_BUS_ADDRESS="unix:path=${USER_RUN}/bus" \
        XDG_RUNTIME_DIR="${USER_RUN}" \
        notify-send "$@" >/dev/null 2>&1 || true
}

log "installing $bundle onto the inactive slot"
notify --icon=system-software-update \
    "Updating backup slot" \
    "Installing version ${target_ts} onto the inactive slot…"

if /usr/bin/rauc install "$bundle"; then
    log "install OK; clearing pending marker"

    # rauc's grub bootloader handler always sets ORDER=<newly-written>
    # <other>, which would silently promote the inactive slot to
    # primary. Both slots now carry the same firmware so functionally
    # it doesn't matter, but the user installed onto the OTHER slot
    # and rebooted here — they expect the next boot to land here too.
    # Restore ORDER accordingly. (Also a safety net: if a later update
    # cycle breaks the just-synced slot, we still boot the proven-good
    # one.)
    booted=""
    for tok in $(cat /proc/cmdline); do
        case "$tok" in
            rauc.slot=A) booted=A ;;
            rauc.slot=B) booted=B ;;
        esac
    done
    grubenv="/boot/efi/EFI/BOOT/grubenv"
    if [ -n "$booted" ] && [ -f "$grubenv" ]; then
        case "$booted" in
            A) grub-editenv "$grubenv" set ORDER="A B" ;;
            B) grub-editenv "$grubenv" set ORDER="B A" ;;
        esac
    fi

    notify --icon=emblem-ok \
        "Backup slot updated" \
        "Both slots now run version ${target_ts}."
    # Clear the marker and the on-disk bundle — the convergence step is
    # complete and the next update cycle will download a fresh bundle.
    rm -f "$PENDING" "$bundle" "${bundle}.sig"
else
    rc=$?
    log "rauc install failed with exit code $rc"
    notify --icon=dialog-error --urgency=critical \
        "Backup slot update failed" \
        "See journalctl -u mdmx-sync-slot for details."
    exit "$rc"
fi
