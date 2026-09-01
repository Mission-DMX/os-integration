# Image rootfs post-processing for MissionDMX. Applied via
# `IMAGE_CLASSES += "mdmx-image-postprocess"` in local.conf so only image
# recipes inherit it (INHERIT globally would try to add DEPENDS to every
# recipe, including natives, which is wrong).
#
# Runs at rootfs assembly time (after all packages are installed) and:
#   1. Copies the deployed initramfs cpio.gz into /boot/initrd inside the
#      rootfs so GRUB can load it via `initrd /boot/initrd` from the
#      selected slot's rootfs. Skipped for the initramfs image itself
#      (no /boot directory there).
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
    # Skip when this image has no /boot (initramfs, minimal container images).
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

ROOTFS_POSTPROCESS_COMMAND:append = " mdmx_install_initrd; mdmx_motd_symlink;"
