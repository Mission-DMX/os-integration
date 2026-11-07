SUMMARY = "Hack typeface — a typeface designed for source code"
DESCRIPTION = "Hack is an open-source typeface from source-foundry \
designed for source code. Four weights: Regular, Bold, Italic, \
BoldItalic. Shipped as /usr/share/fonts/truetype/hack so foot's \
`font=Hack:size=11` default resolves without the user having to \
install anything."
HOMEPAGE = "https://sourcefoundry.org/hack/"

LICENSE = "MIT"
# Upstream's LICENSE.md is MIT with some bitmap bytecode paragraphs
# the project's own README summarises as MIT-equivalent. We vendor the
# TTF tarball which doesn't include LICENSE.md, so point at the common
# MIT template that ships with poky.
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = "https://github.com/source-foundry/Hack/releases/download/v${PV}/Hack-v${PV}-ttf.tar.gz"
SRC_URI[sha256sum] = "7f592d091cbd2472f39af96e6c280cde3c27cab50a9c88746feb42918aa1888f"

# Keep S / UNPACKDIR distinct so the tarball lands in S and nothing
# contests ${WORKDIR}. Upstream tarball ships ttf/*.ttf flat.
S = "${WORKDIR}/sources"
UNPACKDIR = "${S}"

SECTION = "fonts"
INHIBIT_DEFAULT_DEPS = "1"

inherit allarch fontcache

do_install() {
    install -d ${D}${datadir}/fonts/truetype/hack
    install -m 0644 ${S}/ttf/Hack-Regular.ttf    ${D}${datadir}/fonts/truetype/hack/
    install -m 0644 ${S}/ttf/Hack-Bold.ttf       ${D}${datadir}/fonts/truetype/hack/
    install -m 0644 ${S}/ttf/Hack-Italic.ttf     ${D}${datadir}/fonts/truetype/hack/
    install -m 0644 ${S}/ttf/Hack-BoldItalic.ttf ${D}${datadir}/fonts/truetype/hack/
}

FILES:${PN} = "${datadir}/fonts/truetype/hack"
