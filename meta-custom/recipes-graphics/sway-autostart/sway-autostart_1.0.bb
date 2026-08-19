SUMMARY = "Autostart sway Wayland compositor on the graphical console at boot"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

S = "${UNPACKDIR}"

SRC_URI = " \
    file://sway.service \
    file://50-waybar.conf \
    file://waybar-config \
    file://waybar-style.css \
"

inherit allarch systemd

SYSTEMD_SERVICE:${PN} = "sway.service"
SYSTEMD_AUTO_ENABLE = "enable"

RDEPENDS:${PN} = "sway xkeyboard-config waybar dbus"

do_install() {
    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${S}/sway.service ${D}${systemd_system_unitdir}/

    install -d ${D}${sysconfdir}/sway/config.d
    install -m 0644 ${S}/50-waybar.conf ${D}${sysconfdir}/sway/config.d/

    install -d ${D}${sysconfdir}/sway/waybar
    install -m 0644 ${S}/waybar-config ${D}${sysconfdir}/sway/waybar/config
    install -m 0644 ${S}/waybar-style.css ${D}${sysconfdir}/sway/waybar/style.css
}

FILES:${PN} = " \
    ${systemd_system_unitdir}/sway.service \
    ${sysconfdir}/sway/config.d/50-waybar.conf \
    ${sysconfdir}/sway/waybar/config \
    ${sysconfdir}/sway/waybar/style.css \
"
