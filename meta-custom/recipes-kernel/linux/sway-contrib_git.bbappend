SRC_URI += "file://defconfig"
KERNEL_DEFCONFIG = "${WORKDIR}/defconfig"
FILESEXTRAPATHS:prepend := "${THISDIR}/files"

