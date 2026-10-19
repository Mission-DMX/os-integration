SUMMARY = "Autostart sway Wayland compositor on the graphical console at boot"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

S = "${UNPACKDIR}"

SRC_URI = " \
    file://sway.service \
    file://pulseaudio.service \
    file://50-system-server.conf \
    file://40-mako.conf \
    file://50-waybar.conf \
    file://60-keybindings.conf \
    file://61-windowmanagement.conf \
    file://waybar-config \
    file://waybar-style.css \
    file://sway-env.sh \
    file://mdmx-tz.sh \
"

inherit allarch systemd

# Both services are WantedBy=multi-user.target; pulseaudio.service orders
# itself Before=sway.service so the system-mode socket is up before any
# client sway spawns tries to connect.
SYSTEMD_SERVICE:${PN} = "sway.service pulseaudio.service"
SYSTEMD_AUTO_ENABLE = "enable"

RDEPENDS:${PN} = "sway xkeyboard-config waybar dbus mako locale-base-en-us pulseaudio-server mdmx-user console-menu console-settings-daemon"

do_install() {
    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${S}/sway.service ${D}${systemd_system_unitdir}/
    install -m 0644 ${S}/pulseaudio.service ${D}${systemd_system_unitdir}/

    install -d ${D}${sysconfdir}/sway/config.d
    install -m 0644 ${S}/40-mako.conf ${D}${sysconfdir}/sway/config.d/
    install -m 0644 ${S}/50-waybar.conf ${D}${sysconfdir}/sway/config.d/
    install -m 0644 ${S}/60-keybindings.conf ${D}${sysconfdir}/sway/config.d/
    install -m 0644 ${S}/61-windowmanagement.conf ${D}${sysconfdir}/sway/config.d/

    install -d ${D}${sysconfdir}/sway/waybar
    install -m 0644 ${S}/waybar-config ${D}${sysconfdir}/sway/waybar/config
    install -m 0644 ${S}/waybar-style.css ${D}${sysconfdir}/sway/waybar/style.css

    install -d ${D}${sysconfdir}/profile.d
    install -m 0644 ${S}/sway-env.sh ${D}${sysconfdir}/profile.d/sway-env.sh
    install -m 0644 ${S}/mdmx-tz.sh ${D}${sysconfdir}/profile.d/mdmx-tz.sh

    # client.conf.d drop-in — libpulse reads /etc/pulse/client.conf and
    # then every *.conf in /etc/pulse/client.conf.d/ (pa_config_parse's
    # use_dot_d=true in src/pulse/client-conf.c). This points clients at
    # the system-mode socket; without it pactl under sway hits a stale
    # XDG runtime path and errors out with "Connection refused".
    install -d ${D}${sysconfdir}/pulse/client.conf.d
    install -m 0644 ${S}/50-system-server.conf ${D}${sysconfdir}/pulse/client.conf.d/
}

FILES:${PN} = " \
    ${systemd_system_unitdir}/sway.service \
    ${systemd_system_unitdir}/pulseaudio.service \
    ${sysconfdir}/sway/config.d/40-mako.conf \
    ${sysconfdir}/sway/config.d/50-waybar.conf \
    ${sysconfdir}/sway/config.d/60-keybindings.conf \
    ${sysconfdir}/sway/config.d/61-windowmanagement.conf \
    ${sysconfdir}/sway/waybar/config \
    ${sysconfdir}/sway/waybar/style.css \
    ${sysconfdir}/profile.d/sway-env.sh \
    ${sysconfdir}/profile.d/mdmx-tz.sh \
    ${sysconfdir}/pulse/client.conf.d/50-system-server.conf \
"
