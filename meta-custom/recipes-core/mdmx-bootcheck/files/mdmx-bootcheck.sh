#!/bin/sh
# mdmx-bootcheck: mark the current boot slot as healthy once userland
# is up. We use `rauc status mark-good booted` so RAUC's own persistent
# slot-status store (/var/lib/rauc/*) and the grubenv ${SLOT}_TRY
# counter stay in sync. The earlier placeholder that just reset
# ${SLOT}_TRY via grub-editenv(1) left `rauc status` reporting the
# booted slot as "bad" indefinitely — grubenv was clean, RAUC's own
# view wasn't, and any subsequent `rauc install` refused to touch the
# slot.
#
# Fallback: if `rauc` can't talk to its D-Bus service (e.g. the service
# crashed, or we're in some early-boot edge case), fall back to the
# bare grub-editenv reset so GRUB at least doesn't skip the slot on the
# next boot.

set -eu

if command -v rauc >/dev/null 2>&1; then
    if rauc status mark-good booted; then
        exit 0
    fi
    echo "mdmx-bootcheck: rauc mark-good failed; falling back to grub-editenv" >&2
fi

# Slot is passed on the kernel command line as `rauc.slot=A` or =B.
slot=""
for tok in $(cat /proc/cmdline); do
    case "$tok" in
        rauc.slot=*)
            slot=${tok#rauc.slot=}
            ;;
    esac
done

if [ -z "$slot" ]; then
    echo "mdmx-bootcheck: rauc.slot not set on kernel cmdline; nothing to do" >&2
    exit 0
fi

grubenv="/boot/efi/EFI/BOOT/grubenv"
if [ ! -f "$grubenv" ]; then
    echo "mdmx-bootcheck: $grubenv missing; not writing" >&2
    exit 0
fi

case "$slot" in
    A|B) ;;
    *)
        echo "mdmx-bootcheck: rauc.slot='$slot' is not A/B; ignoring" >&2
        exit 0
        ;;
esac

grub-editenv "$grubenv" set "${slot}_TRY=0"
