
This project build firmware based on yocto for an embedded system with touch screens attached.

## General instructions
Avoid adding new dependencies globally but add them to existing recipies first if possible.
If you add or modify a recipe, document the usage, intent, behavior and quirks in a recipe-local README.md file.

The root filesystem must never be addressed by filesystem UUID (e.g. `root=UUID=…` on the kernel cmdline, `UUID=…` in fstab, or systemd units that resolve `/` via `/dev/disk/by-uuid/…`). Both rootfs slots A and B carry the same ext4 blob (rootfsB is populated via `wic`'s `rawcopy` of the same `.ext4` file as rootfsA), so their filesystem UUIDs are identical and anything using UUID for the rootfs would resolve ambiguously. Always use PARTLABEL (`PARTLABEL=rootfsA` / `PARTLABEL=rootfsB`) for the rootfs — this matches `mdmx-grub.cfg`, `rauc/system.conf`, and the firstboot script.

## Tool usage
The image can be testes using make debug on the local host. This spawns a GDB server that can be attached to as well as a console.
Use the following tools through ssh on the host 141.83.158.129 within the os-integration directory. The local changes to the recipies are automatically synced to this host.
Use `make build` to build the image.
Use `make clean` to clean the entire image.
Use `bash -c "cd poky && source oe-init-build-env ../build && bitbake -c cleansstate <package>"` to clean a specific `<package>`.


