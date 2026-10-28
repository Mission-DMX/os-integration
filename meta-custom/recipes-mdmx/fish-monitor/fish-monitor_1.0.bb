SUMMARY = "Wrapper daemon that supervises realtime-fish and integrates it with sway/waybar"
DESCRIPTION = "Spawns fish in a floating scratchpad foot terminal, restarts it \
on crash, notifies via libnotify, cleans up stale /tmp/fish.sock files, and \
exposes a status file for waybar's custom module."
LICENSE = "BSD-3-Clause"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/BSD-3-Clause;md5=550794465ba0ec5312d6919e203a55f9"

S = "${UNPACKDIR}"

SRC_URI = " \
    file://fish-monitor.py \
    file://70-fish-monitor.conf \
    file://fish-terminal-icon.svg \
    file://fish-terminal-icon.png \
"

inherit allarch gtk-icon-cache

RDEPENDS:${PN} = " \
    python3-core \
    foot \
    sway \
    libnotify \
    realtime-fish \
"

do_install() {
    install -d ${D}${bindir}
    install -m 0755 ${S}/fish-monitor.py ${D}${bindir}/fish-monitor

    install -d ${D}${sysconfdir}/sway/config.d
    install -m 0644 ${S}/70-fish-monitor.conf ${D}${sysconfdir}/sway/config.d/

    install -d ${D}${datadir}/icons/hicolor/scalable/apps
    install -m 0644 ${S}/fish-terminal-icon.svg ${D}${datadir}/icons/hicolor/scalable/apps/fish-terminal.svg

    install -d ${D}${datadir}/icons/hicolor/32x32/apps
    install -m 0644 ${S}/fish-terminal-icon.png ${D}${datadir}/icons/hicolor/32x32/apps/fish-terminal.png
}

FILES:${PN} = " \
    ${bindir}/fish-monitor \
    ${sysconfdir}/sway/config.d/70-fish-monitor.conf \
    ${datadir}/icons/hicolor/scalable/apps/fish-terminal.svg \
    ${datadir}/icons/hicolor/32x32/apps/fish-terminal.png \
"
