SUMMARY = "Reset A/B boot try counter after a healthy boot"
DESCRIPTION = "Placeholder for rauc-mark-good until meta-rauc is added. \
A systemd oneshot wired into graphical.target reads rauc.slot= from the \
kernel command line and clears ${slot}_TRY in the ESP grubenv, so GRUB's \
next boot picks the same slot instead of falling through to the fallback."

LICENSE = "BSD-3-Clause"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/BSD-3-Clause;md5=550794465ba0ec5312d6919e203a55f9"

S = "${UNPACKDIR}"

SRC_URI = " \
    file://mdmx-bootcheck.sh \
    file://mdmx-bootcheck.service \
"

inherit allarch systemd

RDEPENDS:${PN} = "grub-editenv"

do_install() {
    install -d ${D}${sbindir}
    install -m 0755 ${S}/mdmx-bootcheck.sh ${D}${sbindir}/mdmx-bootcheck.sh

    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${S}/mdmx-bootcheck.service ${D}${systemd_system_unitdir}/mdmx-bootcheck.service
}

SYSTEMD_PACKAGES = "${PN}"
SYSTEMD_SERVICE:${PN} = "mdmx-bootcheck.service"
SYSTEMD_AUTO_ENABLE = "enable"

FILES:${PN} = " \
    ${sbindir}/mdmx-bootcheck.sh \
    ${systemd_system_unitdir}/mdmx-bootcheck.service \
"
