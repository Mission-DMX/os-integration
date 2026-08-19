SUMMARY = "Autostart sway Wayland compositor on the graphical console at boot"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

S = "${UNPACKDIR}"

SRC_URI = "file://sway.service"

inherit allarch systemd

SYSTEMD_SERVICE:${PN} = "sway.service"
SYSTEMD_AUTO_ENABLE = "enable"

RDEPENDS:${PN} = "sway xkeyboard-config"

do_install() {
    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${S}/sway.service ${D}${systemd_system_unitdir}/
}

FILES:${PN} = "${systemd_system_unitdir}/sway.service"
