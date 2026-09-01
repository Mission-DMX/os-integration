SUMMARY = "MissionDMX unprivileged desktop user"
DESCRIPTION = "Creates the 'user' account (UID 1000) that owns the graphical \
session. Sway is launched as this user by sway.service instead of running as \
root. Membership in video/input/render/audio/dialout gives Wayland the device \
access it needs; membership in seat lets libseat talk to seatd; wheel is kept \
so sudo works from the console."

LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

inherit useradd allarch

USERADD_PACKAGES = "${PN}"
# `render` isn't in base-passwd (unlike video, input, audio, dialout,
# wheel); create it explicitly here so useradd -G render succeeds.
# `seat` is created by seatd — see DEPENDS below.
GROUPADD_PARAM:${PN} = "-r render"
USERADD_PARAM:${PN} = "-u 1000 -d /home/user -m -s /bin/bash \
                      -G video,input,render,audio,dialout,seat,wheel user"

# Empty password so the console login (autologin path or manual) works out of
# the box, matching the existing empty-root-password dev posture in EXTRA_IMAGE_FEATURES.
pkg_postinst_ontarget:${PN}() {
    passwd -d user || true
}

# The seat group is created by the seatd recipe; make sure that runs first so
# useradd -G seat succeeds during rootfs assembly. USERADD_DEPENDS drives
# the offline useradd's ordering during package install; RDEPENDS ensures
# seatd is installed alongside mdmx-user (so the group actually exists).
USERADD_DEPENDS = "seatd"
RDEPENDS:${PN} += "seatd"

ALLOW_EMPTY:${PN} = "1"
