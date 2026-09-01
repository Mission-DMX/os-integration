SUMMARY = "MissionDMX initramfs with A/B slot and user-data provisioning"
DESCRIPTION = "Custom initramfs image built on initramfs-framework. In \
addition to the standard rootfs mount step it runs mdmx-firstboot which \
creates the userdata partition and bind-mounts /home and /var before \
switch_root."

LICENSE = "MIT"

INITRAMFS_SCRIPTS ?= " \
    initramfs-framework-base \
    initramfs-module-udev \
    initramfs-module-e2fs \
    initramfs-module-rootfs \
    mdmx-firstboot \
"

PACKAGE_INSTALL = "${INITRAMFS_SCRIPTS} ${VIRTUAL-RUNTIME_base-utils} udev base-passwd ${ROOTFS_BOOTSTRAP_INSTALL}"

# Do not pollute the initramfs image with rootfs features
IMAGE_FEATURES = ""

# Don't allow the initramfs to contain a kernel (bundled kernel would be circular).
PACKAGE_EXCLUDE = "kernel-image-*"

IMAGE_NAME_SUFFIX ?= ""
IMAGE_LINGUAS = ""

IMAGE_FSTYPES = "${INITRAMFS_FSTYPES}"
# local.conf appends "wic wic.bmap" to IMAGE_FSTYPES globally so the
# main image ships as a WIC. That append also lands here — but building
# a WIC for the initramfs image would pull in linux-yocto:do_deploy,
# which depends on do_bundle_initramfs, which depends back on this
# image's do_image_complete. Strip wic so the loop is broken.
IMAGE_FSTYPES:remove = "wic wic.bmap"
inherit core-image

IMAGE_ROOTFS_SIZE = "32768"
IMAGE_ROOTFS_EXTRA_SPACE = "0"

COMPATIBLE_HOST = '(x86_64.*|i.86.*|arm.*|aarch64.*)-(linux.*|freebsd.*)'
