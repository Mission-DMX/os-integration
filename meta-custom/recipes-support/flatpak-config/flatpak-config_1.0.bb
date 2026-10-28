SUMMARY = "MissionDMX Flatpak configuration: pulls in flatpak + wlroots portals, registers Flathub as a system remote on first boot, and extends sway's session environment so fuzzel discovers Flatpak-exported .desktop files."
LICENSE = "BSD-3-Clause"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/BSD-3-Clause;md5=550794465ba0ec5312d6919e203a55f9"

S = "${UNPACKDIR}"

SRC_URI = " \
    file://flathub.flatpakrepo \
    file://flatpak-flathub-setup.service \
    file://10-flatpak-xdg.conf \
    file://sway-portals.conf \
    file://70-portals.conf \
"

inherit allarch systemd features_check

REQUIRED_DISTRO_FEATURES = "polkit wayland"

# flatpak transitively brings bubblewrap, xdg-dbus-proxy, flatpak-xdg-utils,
# fuse3-utils, ca-certificates. glib-networking supplies the GIO TLS backend
# for libsoup/ostree fallback paths. The portal pair enables
# screenshot/screencast for sandboxed Flathub apps running under sway;
# pipewire is required by xdg-desktop-portal-wlr for screencast streams.
RDEPENDS:${PN} = " \
    flatpak \
    glib-networking \
    xdg-desktop-portal \
    xdg-desktop-portal-wlr \
    pipewire \
    sway-autostart \
"

SYSTEMD_PACKAGES = "${PN}"
SYSTEMD_SERVICE:${PN} = "flatpak-flathub-setup.service"
SYSTEMD_AUTO_ENABLE = "enable"

do_install() {
    install -d ${D}${sysconfdir}/flatpak/remotes
    install -m 0644 ${S}/flathub.flatpakrepo \
        ${D}${sysconfdir}/flatpak/remotes/flathub.flatpakrepo

    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${S}/flatpak-flathub-setup.service \
        ${D}${systemd_system_unitdir}/flatpak-flathub-setup.service

    install -d ${D}${systemd_system_unitdir}/sway.service.d
    install -m 0644 ${S}/10-flatpak-xdg.conf \
        ${D}${systemd_system_unitdir}/sway.service.d/10-flatpak-xdg.conf

    # xdg-desktop-portal picks a backend-per-interface based on
    # XDG_CURRENT_DESKTOP. Shipping sway-portals.conf makes screenshot/
    # screencast prefer the wlr backend; the drop-in above sets
    # XDG_CURRENT_DESKTOP=sway so this file is matched.
    install -d ${D}${sysconfdir}/xdg/xdg-desktop-portal
    install -m 0644 ${S}/sway-portals.conf \
        ${D}${sysconfdir}/xdg/xdg-desktop-portal/sway-portals.conf

    # Sway autostart hook: launches the pipewire daemon on session start
    # and pushes the Wayland/portals env into the dbus activation
    # environment so dbus-activated portal processes can connect.
    install -d ${D}${sysconfdir}/sway/config.d
    install -m 0644 ${S}/70-portals.conf \
        ${D}${sysconfdir}/sway/config.d/70-portals.conf
}

FILES:${PN} = " \
    ${sysconfdir}/flatpak/remotes/flathub.flatpakrepo \
    ${systemd_system_unitdir}/flatpak-flathub-setup.service \
    ${systemd_system_unitdir}/sway.service.d/10-flatpak-xdg.conf \
    ${sysconfdir}/xdg/xdg-desktop-portal/sway-portals.conf \
    ${sysconfdir}/sway/config.d/70-portals.conf \
"
