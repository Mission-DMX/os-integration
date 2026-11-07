# MissionDMX: ship a system-wide foot.ini that selects source-foundry
# Hack as the default. /etc/xdg/foot/foot.ini is where foot reads a
# system-wide config before falling back to compiled-in defaults
# (XDG_CONFIG_DIRS). A per-user ~/.config/foot/foot.ini still overrides
# this, which is intentional — the first-boot wizard writes user
# overrides when the operator picks a different font.
FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI += "file://foot.ini"

do_install:append() {
    install -d ${D}${sysconfdir}/xdg/foot
    install -m 0644 ${UNPACKDIR}/foot.ini ${D}${sysconfdir}/xdg/foot/foot.ini
}

FILES:${PN} += "${sysconfdir}/xdg/foot/foot.ini"

# ttf-hack ships /usr/share/fonts/truetype/hack/Hack-*.ttf so the
# default font= directive resolves via fontconfig without any extra
# user action. RDEPEND (not RRECOMMEND) because foot without Hack
# would silently fall through to a nameless monospace fallback and
# defeat the whole point of this bbappend.
RDEPENDS:${PN} = "ncurses-terminfo ttf-hack"
