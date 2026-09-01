SUMMARY = "First-boot user data partition setup (initramfs-framework module)"
DESCRIPTION = "Ships /init.d/95-mdmx-firstboot into the initramfs. On first \
boot it creates a 4th partition in the free space left on the flashed disk, \
formats it ext4 with label 'userdata', seeds /home and /var from the rootfs \
skeleton, and bind-mounts them onto the running root before switch_root."

LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

S = "${UNPACKDIR}"

SRC_URI = "file://firstboot"

inherit allarch

# Runtime deps land in the initramfs image alongside this script.
RDEPENDS:${PN} = " \
    initramfs-framework-base \
    initramfs-module-rootfs \
    initramfs-module-udev \
    gptfdisk \
    e2fsprogs-mke2fs \
    parted \
    util-linux-blockdev \
    coreutils \
"

do_install() {
    install -d ${D}/init.d
    # File name is "95-firstboot" (single word after the leading number)
    # because the framework's /init dispatcher takes cut -d'-' -f 2 of it
    # to derive the ${module}_enabled / ${module}_run callback names. See
    # the header of firstboot for the full explanation.
    install -m 0755 ${S}/firstboot ${D}/init.d/95-firstboot
}

FILES:${PN} = "/init.d/95-firstboot"
