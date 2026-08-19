SRC_URI += "file://defconfig"
KERNEL_DEFCONFIG = "${WORKDIR}/defconfig"
FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

# The Intel Xe GPU driver generates xe_wa_oob.h with a hardcoded build path.
# This is a known upstream issue; skip the buildpaths QA check for the -src package.
INSANE_SKIP:${PN}-src += "buildpaths"

