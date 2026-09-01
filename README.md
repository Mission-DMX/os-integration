# os-integration
Repository to autmatically build Yocto deployments 

# Makefile targets
 * build         — build the release WIC image
 * build-debug   — build a WIC with `nokaslr` baked into GRUB's cmdline
 * run           — boot the WIC in QEMU under OVMF (EFI)
 * debug         — same as `run` but with `-s -S` for the qemu gdb stub
 * reset-nvram   — refresh the writable copy of OVMF NVRAM
 * clean         — wipe the build directory

## Prerequisites
QEMU boots the image through UEFI firmware (OVMF), so the host needs
OVMF installed:

    # Debian / Ubuntu
    sudo apt install ovmf
    # (Debian 13 ships /usr/share/OVMF/OVMF_{CODE,VARS}_4M.fd, which is
    # the default in the Makefile. Older Debian used the un-suffixed
    # OVMF_CODE.fd/OVMF_VARS.fd — pass overrides if needed:
    #   make run OVMF_CODE=/usr/share/OVMF/OVMF_CODE.fd \
    #            OVMF_VARS=/usr/share/OVMF/OVMF_VARS.fd )

    # Fedora — then pass overrides:
    #   make run OVMF_CODE=/usr/share/edk2/ovmf/OVMF_CODE.fd \
    #            OVMF_VARS=/usr/share/edk2/ovmf/OVMF_VARS.fd

## Flashing to real hardware
`make build` produces two useful artifacts under
`build/tmp/deploy/images/qemux86-64/`:

  * `core-image-minimal-qemux86-64.rootfs.wic.xz`  — the shippable
    xz-compressed image (expands to ~32 GiB with `rootfsB`
    mostly zero-filled). This is what you distribute or archive.
  * `core-image-minimal-qemux86-64.rootfs.wic.bmap` — sparse-block map;
    let `bmaptool` skip the empty slot instead of writing 16 GiB of
    zeros.

Preferred flow (fastest, decompresses + skips holes in one pass):

    sudo bmaptool copy \
        build/tmp/deploy/images/qemux86-64/core-image-minimal-qemux86-64.rootfs.wic.xz \
        /dev/sdX

Fallback with `dd`:

    xzcat build/tmp/deploy/images/qemux86-64/core-image-minimal-qemux86-64.rootfs.wic.xz \
        | sudo dd of=/dev/sdX bs=4M status=progress conv=fsync

Replace `/dev/sdX` with the target drive — this **wipes the whole disk**,
so double-check with `lsblk` first. After the first boot the initramfs
grows a 4th `userdata` partition into whatever free space is left on the
drive, so a larger drive gives you more room for `/home` and `/var`.

## Disk layout
The WIC written by `make build` has three fixed partitions:

  1. **esp**       — 128 MiB VFAT, GRUB-EFI + grubenv
  2. **rootfsA**   — 16 GiB ext4, active firmware slot at flash time
  3. **rootfsB**   — 16 GiB ext4, inactive/fallback slot (empty on first boot)

A fourth **userdata** partition is created on first boot by the
`mdmx-firstboot` initramfs module in whatever disk space is left after
flashing. `/home` and `/var` are bind-mounted from that partition so
they survive firmware updates.

GRUB uses RAUC-compatible `grubenv` variables (`ORDER`, `<slot>_OK`,
`<slot>_TRY`) to choose between slots. A userland oneshot
(`mdmx-bootcheck.service`) clears the try counter after a healthy boot;
this is a placeholder that `rauc-mark-good` will replace when meta-rauc
lands.

## Important
Revert sway.service pixman renderer once debugging on a non-Nvidia host.
