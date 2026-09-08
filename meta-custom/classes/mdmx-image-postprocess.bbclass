# Image rootfs post-processing for MissionDMX. Applied via
# `IMAGE_CLASSES += "mdmx-image-postprocess"` in local.conf so only image
# recipes inherit it (INHERIT globally would try to add DEPENDS to every
# recipe, including natives, which is wrong).
#
# Runs at rootfs assembly time (after all packages are installed) and:
#   1. Copies the deployed initramfs cpio.gz into /boot/initrd inside the
#      rootfs so GRUB can load it via `initrd /boot/initrd` from the
#      selected slot's rootfs. Skipped for the initramfs image itself
#      (PN == INITRAMFS_IMAGE) — the cpio.gz doesn't exist yet during
#      its own do_rootfs, and shipping an initrd inside an initrd would
#      be circular anyway.
#   2. Replaces the plain /etc/motd shipped by base-files with a symlink
#      to /var/motd. /var is bind-mounted from the userdata partition
#      by the initramfs firstboot module, so the MOTD survives firmware
#      updates and stays writable even if the root filesystem is later
#      remounted read-only. Skipped when the image has no /etc/motd
#      (i.e. no base-files, e.g. initramfs).

# The main image's do_image_wic references ${DEPLOY_DIR_IMAGE}/grubenv
# via IMAGE_EFI_BOOT_FILES; declare an explicit build-time dep so the
# grubenv is present before wic runs. Setting WKS_FILE_DEPENDS_BOOTLOADERS
# in local.conf doesn't work because image_types_wic.bbclass overrides it
# per-arch during class inheritance.
DEPENDS:append = " mdmx-grubenv"
do_image_wic[depends] += "mdmx-grubenv:do_deploy"

mdmx_install_initrd () {
    # Never install the initrd into the initramfs image itself — the
    # cpio.gz being packaged doesn't exist yet during our own do_rootfs
    # (we're the recipe that produces it), and shipping an initrd inside
    # an initrd is nonsensical anyway. Earlier this was gated on
    # "no /boot dir", but something in the initramfs's package set now
    # creates an empty /boot which trips that heuristic and produces a
    # spurious warning. Keying off PN is exact.
    if [ "${PN}" = "${INITRAMFS_IMAGE}" ]; then
        return
    fi
    # Some minimal container images also lack /boot; keep the fallback
    # check so we don't try to install into a nonexistent directory.
    if [ ! -d ${IMAGE_ROOTFS}/boot ]; then
        return
    fi
    if [ -e ${DEPLOY_DIR_IMAGE}/${INITRAMFS_IMAGE}-${MACHINE}.cpio.gz ]; then
        install -m 0644 ${DEPLOY_DIR_IMAGE}/${INITRAMFS_IMAGE}-${MACHINE}.cpio.gz ${IMAGE_ROOTFS}/boot/initrd
    else
        bbwarn "mdmx_install_initrd: no ${INITRAMFS_IMAGE} cpio.gz in ${DEPLOY_DIR_IMAGE}; /boot/initrd not installed"
    fi
}

mdmx_motd_symlink () {
    # Skip when /etc doesn't exist (initramfs images without base-files).
    if [ ! -d ${IMAGE_ROOTFS}${sysconfdir} ]; then
        return
    fi
    rm -f ${IMAGE_ROOTFS}${sysconfdir}/motd
    ln -sf /var/motd ${IMAGE_ROOTFS}${sysconfdir}/motd
}

# Pre-create mount points that the running system needs to write mounts onto.
# The rootfs is read-only at runtime (kernel boots with `ro`), so any mkdir
# attempted after switch_root — either by the initramfs firstboot moving
# /mnt/userdata into the rootfs, or by systemd creating /boot/efi from the
# fstab entry — would fail with EROFS. Creating these empty directories at
# rootfs assembly time is a build-time write that persists into the image.
mdmx_create_mountpoints () {
    if [ ! -d ${IMAGE_ROOTFS} ] || [ ! -e ${IMAGE_ROOTFS}/etc/fstab ]; then
        return
    fi
    install -d -m 0755 ${IMAGE_ROOTFS}/mnt/userdata
    install -d -m 0755 ${IMAGE_ROOTFS}/boot/efi
}

# Stamp the rootfs with its build timestamp. mdmx-updater on the target
# reads /etc/mdmx-build-timestamp and compares it against build_timestamp
# entries in the update server's manifest.json — anything strictly newer
# is a candidate for download. The lexical YYYYMMDDhhmmss format (matches
# bitbake's DATETIME) sorts identically to chronological order, so the
# comparison is a plain string test on both sides.
#
# The same value is also emitted as a deploy-dir sidecar so
# `make publish` can pick it up without having to peek inside the ext4;
# without the sidecar the publish flow would need `debugfs` (or worse, a
# root mount) to recover it, which we'd rather not require on the host.
# Skipped for images with no /etc (initramfs, minimal images).
mdmx_write_build_timestamp () {
    if [ ! -d ${IMAGE_ROOTFS}${sysconfdir} ]; then
        return
    fi
    printf '%s\n' "${DATETIME}" > ${IMAGE_ROOTFS}${sysconfdir}/mdmx-build-timestamp
    chmod 0644 ${IMAGE_ROOTFS}${sysconfdir}/mdmx-build-timestamp

    install -d ${DEPLOY_DIR_IMAGE}
    printf '%s\n' "${DATETIME}" > ${DEPLOY_DIR_IMAGE}/mdmx-build-timestamp
}
# DATETIME resolves per-task, so exclude it from vardeps — otherwise
# every wall-clock tick would appear as a signature change and burn the
# rootfs sstate cache without reason.
mdmx_write_build_timestamp[vardepsexclude] = "DATETIME"

ROOTFS_POSTPROCESS_COMMAND:append = " mdmx_install_initrd; mdmx_motd_symlink; mdmx_create_mountpoints; mdmx_write_build_timestamp;"
