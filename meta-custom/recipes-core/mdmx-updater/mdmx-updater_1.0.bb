SUMMARY = "MissionDMX OS update checker and install helper"
DESCRIPTION = "Periodically polls the update server configured in \
~/.config/console-settings.ini under [update] url=, downloads any RAUC \
bundle whose build_timestamp is strictly greater than /etc/mdmx-build-timestamp, \
verifies its detached hybrid CMS signature (RSA-4096 + ML-DSA-65) against \
/etc/rauc/mdmx-keyring.pem, and writes a pending marker into the user's cache. \
Installation itself is user-initiated: console-menu shows an 'Install Update' \
entry when a pending marker exists, and invokes the shipped install helper via \
pkexec — a polkit rule restricts that exact command path to the desktop user."

LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

S = "${UNPACKDIR}"

SRC_URI = " \
    file://mdmx-updater.py \
    file://mdmx-updater.service \
    file://mdmx-updater.timer \
    file://mdmx-updater-install \
    file://50-mdmx-updater.rules \
"

inherit allarch systemd features_check

# openssl-bin gives us the openssl(1) CLI the checker shells out to for
# CMS verification. rauc pulls in the D-Bus service the install helper
# talks to. polkit backs the pkexec grant for the install helper.
REQUIRED_DISTRO_FEATURES = "polkit systemd"

RDEPENDS:${PN} = " \
    python3-core \
    python3-json \
    python3-netclient \
    openssl-bin \
    rauc \
    polkit \
    coreutils \
"

SYSTEMD_PACKAGES = "${PN}"
# Enable both units: the timer schedules runs; the service is enabled
# WantedBy=multi-user.target so `systemctl start mdmx-updater.service`
# can be invoked ad-hoc (from the console menu's manual "Check for
# Updates" entry) without needing extra plumbing.
SYSTEMD_SERVICE:${PN} = "mdmx-updater.service mdmx-updater.timer"
SYSTEMD_AUTO_ENABLE = "enable"

do_install() {
    install -d ${D}${bindir}
    install -m 0755 ${S}/mdmx-updater.py ${D}${bindir}/mdmx-updater

    # libexec: the install helper is not a user-facing tool. Hiding it
    # under /usr/libexec keeps it off $PATH so no one accidentally
    # invokes it directly (they'd hit the PKEXEC_UID check anyway, but
    # signalling "internal" through the layout is the polite move).
    install -d ${D}${libexecdir}/mdmx-updater
    install -m 0755 ${S}/mdmx-updater-install \
        ${D}${libexecdir}/mdmx-updater/mdmx-updater-install

    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${S}/mdmx-updater.service \
        ${D}${systemd_system_unitdir}/mdmx-updater.service
    install -m 0644 ${S}/mdmx-updater.timer \
        ${D}${systemd_system_unitdir}/mdmx-updater.timer

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
    ${libexecdir}/mdmx-updater/mdmx-updater-install \
    ${systemd_system_unitdir}/mdmx-updater.service \
    ${systemd_system_unitdir}/mdmx-updater.timer \
    ${datadir}/polkit-1/rules.d/50-mdmx-updater.rules \
"
