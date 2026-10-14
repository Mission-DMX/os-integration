#!/bin/sh
#
# mdmx-explorer-mount — privileged mount helper reached via pkexec.
#
# Argv: <fstype> <source> <mountpoint> <options>
#   fstype:     cifs | nfs4 | fuse.sshfs | umount
#   source:     fstype-specific syntax (ignored for umount)
#   mountpoint: must match /run/media/net.<NAME>/ where NAME is [A-Za-z0-9_-]+
#   options:    comma-separated mount options; must not contain shell meta
#
# The polkit rule 50-mdmx-explorer.rules authorises pkexec for user "user"
# only when the invoked program is exactly this script, so the input is
# untrusted from the user's perspective but trusted enough to come from
# our own UI. Validation here is still performed because an attacker who
# can exec pkexec with our argv could otherwise mount anywhere.

set -eu

usage() {
    echo "usage: $0 <fstype> <source> <mountpoint> <options>" >&2
    exit 2
}

[ $# -eq 4 ] || usage

FSTYPE="$1"
SOURCE="$2"
MOUNTPOINT="$3"
OPTIONS="$4"

case "$MOUNTPOINT" in
    /run/media/net.*) ;;
    *) echo "mountpoint must be under /run/media/net.*" >&2; exit 3 ;;
esac

# Strip leading /run/media/net. and verify the remainder is a safe name.
NAME="${MOUNTPOINT#/run/media/net.}"
case "$NAME" in
    *[!A-Za-z0-9_-]* | "") echo "invalid mount name: $NAME" >&2; exit 3 ;;
esac

# No shell metacharacters in the free-form options string. The user's
# own UI should never pass such characters; this is a backstop.
case "$OPTIONS" in
    *[\;\&\|\$\`\<\>\(\)\"\'\\]* ) echo "forbidden chars in options" >&2; exit 3 ;;
esac

case "$FSTYPE" in
    cifs|nfs4|fuse.sshfs)
        mkdir -p "$MOUNTPOINT"
        if [ -n "$OPTIONS" ]; then
            exec mount -t "$FSTYPE" "$SOURCE" "$MOUNTPOINT" -o "$OPTIONS"
        else
            exec mount -t "$FSTYPE" "$SOURCE" "$MOUNTPOINT"
        fi
        ;;
    umount)
        exec umount "$MOUNTPOINT"
        ;;
    *)
        echo "unsupported fstype: $FSTYPE" >&2
        exit 3
        ;;
esac
