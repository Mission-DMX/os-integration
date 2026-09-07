SUMMARY = "Touch-friendly session menu (lock / reboot / shutdown) for MissionDMX"
DESCRIPTION = "Waybar-triggered fuzzel menu that lets the operator lock the \
screen, change the lock PIN, reboot, or shut down. sway.service runs as an \
unprivileged user with no logind session, so this recipe also ships a polkit \
JS rule granting that user the login1 power-off / reboot actions. \
The lock screen is a small PyGObject app built on gtk-session-lock, which \
speaks the Wayland ext-session-lock-v1 protocol so the compositor hides \
every other client and refuses to unlock until we say so — bypassable \
overlay-layer approaches (gtk-layer-shell, etc.) don't apply. \
PIN stored in ~/.config/console-settings.ini (default 0000)."

LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

S = "${UNPACKDIR}"

SRC_URI = " \
    file://console-menu.sh \
    file://console-lock.py \
    file://fuzzel.ini \
    file://50-console-menu.rules \
"

inherit allarch features_check

# The runtime chain below transitively pulls in gtk-session-lock (which
# declares REQUIRED_DISTRO_FEATURES="wayland gobject-introspection")
# and python3-pygobject (which needs gobject-introspection-data on the
# target for the typelibs to load). Listing both flags here surfaces a
# missing DISTRO feature as a clear parse-time error instead of a
# cryptic runtime "namespace not found".
REQUIRED_DISTRO_FEATURES = "wayland polkit gobject-introspection gobject-introspection-data"

# Runtime chain:
#   * fuzzel          — dmenu backend for the menu itself
#   * systemd         — target of `systemctl reboot|poweroff`
#   * polkit          — enforces the JS rule shipped here
#   * python3-core    — locker script (argparse/configparser are core)
#   * python3-pygobject + gtk+3 + gtk-session-lock + gobject-introspection
#                     — GTK3 + ext-session-lock-v1 binding via GI. GTK3
#                       (not 4) because gtk-session-lock only targets 3.
#                       Package is named "gtk+3" at the recipe level even
#                       though debian.bbclass renames the on-disk rpm to
#                       "libgtk-3.0"; bitbake RDEPENDS resolves against
#                       the recipe name, not the debian-renamed one.
#   * ttf-dejavu-sans — matches the fuzzel/waybar fonts already in use
RDEPENDS:${PN} = " \
    fuzzel \
    systemd \
    polkit \
    python3-core \
    python3-pygobject \
    gtk+3 \
    gtk-session-lock \
    gobject-introspection \
    ttf-dejavu-sans \
"

do_install() {
    install -d ${D}${bindir}
    install -m 0755 ${S}/console-menu.sh  ${D}${bindir}/console-menu
    install -m 0755 ${S}/console-lock.py  ${D}${bindir}/console-lock

    install -d ${D}${sysconfdir}/console-menu
    install -m 0644 ${S}/fuzzel.ini ${D}${sysconfdir}/console-menu/fuzzel.ini

    # Ship the polkit rule under ${datadir} rather than ${sysconfdir}:
    #   * /etc/polkit-1/rules.d is chmod 0700 polkitd:root by the polkit
    #     recipe (it's the local-admin override location), so a second
    #     package claiming it as 0755 root:root would fail rpm's dir
    #     ownership check with "conflicts between …" at do_rootfs;
    #   * /usr/share/polkit-1/rules.d is 0755 root:root — the same mode
    #     the polkit-group-rule-* recipes in meta-oe use, and polkit's
    #     JS engine reads *.rules from both directories at daemon start
    #     (with /etc taking precedence).
    install -m 0755 -d ${D}${datadir}/polkit-1/rules.d
    install -m 0644 ${S}/50-console-menu.rules \
        ${D}${datadir}/polkit-1/rules.d/50-console-menu.rules
}

FILES:${PN} = " \
    ${bindir}/console-menu \
    ${bindir}/console-lock \
    ${sysconfdir}/console-menu/fuzzel.ini \
    ${datadir}/polkit-1/rules.d/50-console-menu.rules \
"
