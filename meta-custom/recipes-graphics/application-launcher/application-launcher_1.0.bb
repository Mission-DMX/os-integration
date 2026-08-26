SUMMARY = "Touch-friendly application launcher for MissionDMX systems"
DESCRIPTION = "Small wrapper around fuzzel plus a touch-tuned config. \
Invoked by the waybar tray icon in sway-autostart, so the operator can \
launch the MissionDMX editor (or any other .desktop entry) without a \
keyboard."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

S = "${UNPACKDIR}"

SRC_URI = " \
    file://application-launcher.sh \
    file://fuzzel.ini \
"

inherit allarch

RDEPENDS:${PN} = "fuzzel foot pulseaudio-server pulseaudio-misc"

do_install() {
    install -d ${D}${bindir}
    install -m 0755 ${S}/application-launcher.sh ${D}${bindir}/application-launcher

    # Private config path so we don't clash with the upstream fuzzel
    # recipe which already ships /etc/xdg/fuzzel/fuzzel.ini. The
    # application-launcher wrapper passes this file to fuzzel with --config=.
    install -d ${D}${sysconfdir}/application-launcher
    install -m 0644 ${S}/fuzzel.ini ${D}${sysconfdir}/application-launcher/fuzzel.ini
}

FILES:${PN} = " \
    ${bindir}/application-launcher \
    ${sysconfdir}/application-launcher/fuzzel.ini \
"
