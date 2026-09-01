#!/bin/sh
# mdmx-bootcheck: reset the RAUC-style boot try-counter for the current
# slot once userland is up. This is the placeholder for `rauc-mark-good`
# that will replace it when meta-rauc lands. Without this, GRUB would
# still see the counter at 1 on the next boot and would refuse to try
# the same slot again — which is exactly the fallback semantics we want
# for a *failed* boot, but not for a healthy one.

set -eu

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
