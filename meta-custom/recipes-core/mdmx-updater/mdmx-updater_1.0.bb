SUMMARY = "MissionDMX OS update checker and install helper"
DESCRIPTION = "Periodically polls the update server configured in \
~/.config/console-settings.ini under [update] url=, downloads any RAUC \
bundle whose build_timestamp is strictly greater than /etc/mdmx-build-timestamp, \
verifies its detached hybrid CMS signature (RSA-4096 + ML-DSA-65) against \
/etc/rauc/mdmx-keyring.pem, and writes a pending marker into the user's cache. \
Installation itself is user-initiated: console-menu shows an 'Install Update' \
entry when a pending marker exists, and invokes the shipped install helper via \
pkexec — a polkit rule restricts that exact command path to the desktop user."

LICENSE = "BSD-3-Clause"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/BSD-3-Clause;md5=550794465ba0ec5312d6919e203a55f9"

S = "${UNPACKDIR}"

SRC_URI = " \
    file://mdmx-updater.py \
    file://mdmx-updater.service \
    file://mdmx-updater.timer \
    file://mdmx-updater-install \
    file://mdmx-update-installer.py \
    file://mdmx-sync-slot.sh \
    file://mdmx-sync-slot.service \
    file://50-mdmx-updater.rules \
"

inherit allarch systemd features_check

# openssl-bin gives us the openssl(1) CLI the checker shells out to for
# CMS verification. rauc pulls in the D-Bus service the install helper
# talks to. polkit backs the pkexec grant for the install helper.
# glibc-utils provides getent(1), which the install helper uses to
# resolve the launching user's $HOME by PKEXEC_UID (pkexec scrubs the
# environment, so we can't trust $HOME from the caller). wayland +
# gobject-introspection[-data] gate mdmx-update-installer's GTK3 /
# gtk-session-lock / PyGObject stack (same as console-menu) — missing
# any of those turns an obscure runtime "namespace not found" into a
# clear parse-time error.
REQUIRED_DISTRO_FEATURES = "polkit systemd wayland gobject-introspection gobject-introspection-data"

RDEPENDS:${PN} = " \
    python3-core \
    python3-json \
    python3-netclient \
    python3-pygobject \
    gtk+3 \
    gtk-session-lock \
    gobject-introspection \
    libnotify \
    openssl-bin \
    rauc \
    polkit \
    coreutils \
    glibc-utils \
    util-linux-runuser \
"

SYSTEMD_PACKAGES = "${PN}"
# Enable the timer (periodic manifest polling) and the sync-slot
# oneshot (fires at boot, gated on pending.json). mdmx-updater.service
# deliberately has no [Install] section — it's driven by the timer and
# by ad-hoc `systemctl start`, not by a target.
SYSTEMD_SERVICE:${PN} = "mdmx-updater.timer mdmx-sync-slot.service"
SYSTEMD_AUTO_ENABLE = "enable"

do_install() {
    install -d ${D}${bindir}
    install -m 0755 ${S}/mdmx-updater.py ${D}${bindir}/mdmx-updater
    # GUI progress installer launched by the console menu's "Install
    # Update" entry. Runs as the desktop user; the pkexec call inside
    # elevates for the actual rauc install.
    install -m 0755 ${S}/mdmx-update-installer.py \
        ${D}${bindir}/mdmx-update-installer

    # libexec: the install helper is not a user-facing tool. Hiding it
    # under /usr/libexec keeps it off $PATH so no one accidentally
    # invokes it directly (they'd hit the PKEXEC_UID check anyway, but
    # signalling "internal" through the layout is the polite move).
    install -d ${D}${libexecdir}/mdmx-updater
    install -m 0755 ${S}/mdmx-updater-install \
        ${D}${libexecdir}/mdmx-updater/mdmx-updater-install

    # sbin: sync-slot is an admin-facing script invoked by its systemd
    # oneshot and not expected to be run by hand.
    install -d ${D}${sbindir}
    install -m 0755 ${S}/mdmx-sync-slot.sh ${D}${sbindir}/mdmx-sync-slot.sh

    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${S}/mdmx-updater.service \
        ${D}${systemd_system_unitdir}/mdmx-updater.service
    install -m 0644 ${S}/mdmx-updater.timer \
        ${D}${systemd_system_unitdir}/mdmx-updater.timer
    install -m 0644 ${S}/mdmx-sync-slot.service \
        ${D}${systemd_system_unitdir}/mdmx-sync-slot.service

    # Same reasoning as console-menu: /etc/polkit-1/rules.d is
    # chmod 0700 polkitd:root by the polkit recipe, so a package that
    # claims it as 0755 root:root fights rpm's dir-ownership check.
    # /usr/share/polkit-1/rules.d is polkit's vendor location and works.
    install -d -m 0755 ${D}${datadir}/polkit-1/rules.d
    install -m 0644 ${S}/50-mdmx-updater.rules \
        ${D}${datadir}/polkit-1/rules.d/50-mdmx-updater.rules
}

FILES:${PN} = " \
    ${bindir}/mdmx-updater \
    ${bindir}/mdmx-update-installer \
    ${libexecdir}/mdmx-updater/mdmx-updater-install \
    ${sbindir}/mdmx-sync-slot.sh \
    ${systemd_system_unitdir}/mdmx-updater.service \
    ${systemd_system_unitdir}/mdmx-updater.timer \
    ${systemd_system_unitdir}/mdmx-sync-slot.service \
    ${datadir}/polkit-1/rules.d/50-mdmx-updater.rules \
"
