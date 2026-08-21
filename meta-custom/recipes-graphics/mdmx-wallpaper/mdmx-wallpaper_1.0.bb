SUMMARY = "Mission-DMX branded wallpaper: assets and generator script"
DESCRIPTION = "Ships the base linen and logo images plus a Python script that \
sway invokes on startup to generate and set a resolution-matched wallpaper."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

S = "${UNPACKDIR}"

SRC_URI = " \
    file://60-wallpaper.conf \
    file://generate_wallpaper.py \
    file://desktop-linen.png \
    file://logo.png \
"

inherit allarch

RDEPENDS:${PN} = "sway python3-core python3-json python3-pillow"

do_install() {
    install -d ${D}${bindir}
    install -m 0755 ${S}/generate_wallpaper.py ${D}${bindir}/generate_wallpaper

    install -d ${D}${datadir}/backgrounds/sway
    install -m 0644 ${S}/desktop-linen.png ${D}${datadir}/backgrounds/sway/
    install -m 0644 ${S}/logo.png ${D}${datadir}/backgrounds/sway/

    install -d ${D}${sysconfdir}/sway/config.d
    install -m 0644 ${S}/60-wallpaper.conf ${D}${sysconfdir}/sway/config.d/
}

FILES:${PN} = " \
    ${bindir}/generate_wallpaper \
    ${datadir}/backgrounds/sway/desktop-linen.png \
    ${datadir}/backgrounds/sway/logo.png \
    ${sysconfdir}/sway/config.d/60-wallpaper.conf \
"
