SRC_URI += "file://defconfig"
KERNEL_DEFCONFIG = "${WORKDIR}/defconfig"
FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

# Per-concern config fragments. linux-yocto's kern-tools pipeline merges
# anything from SRC_URI whose basename ends in .cfg into .config after
# the defconfig load. Keeps additions discoverable (one file per topic)
# instead of hiding them inside the 676-line defconfig.
SRC_URI += "file://rauc-verity.cfg"

# The Intel Xe GPU driver generates xe_wa_oob.h with a hardcoded build path.
# This is a known upstream issue; skip the buildpaths QA check for the -src package.
INSANE_SKIP:${PN}-src += "buildpaths"

