SUMMARY = "Wrapper daemon that supervises realtime-fish and integrates it with sway/waybar"
DESCRIPTION = "Spawns fish in a floating scratchpad foot terminal, restarts it \
on crash, notifies via libnotify, cleans up stale /tmp/fish.sock files, and \
exposes a status file for waybar's custom module."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

S = "${UNPACKDIR}"

SRC_URI = " \
    file://fish-monitor.py \
    file://70-fish-monitor.conf \
"

inherit allarch

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
}

FILES:${PN} = " \
    ${bindir}/fish-monitor \
    ${sysconfdir}/sway/config.d/70-fish-monitor.conf \
"
