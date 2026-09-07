SUMMARY = "DBus-controlled transient network configuration for MissionDMX"
DESCRIPTION = "Runs as a system-bus daemon on org.mission_dmx.networking_ctrl. \
On an ApplyConfiguration call, materialises the JSON payload described in \
NetworkControlProtocol.md as /run/systemd/network drop-ins that override the \
default DHCP profile shipped by mdmx-network, then restarts systemd-networkd \
+ systemd-resolved. An empty payload clears the drop-ins and hands the \
network back to DHCP."

LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

S = "${UNPACKDIR}"

SRC_URI = " \
    file://mdmx-network-ctrl.py \
    file://mdmx-network-ctrl.service \
    file://mdmx-network-ctrl.conf \
"

inherit allarch systemd

SYSTEMD_SERVICE:${PN} = "mdmx-network-ctrl.service"
SYSTEMD_AUTO_ENABLE:${PN} = "enable"

# Runtime chain:
#   * python3-core           — interpreter + stdlib (json, ipaddress, subprocess, logging)
#   * python3-dbus           — dbus.service / dbus.mainloop.glib
#   * python3-pygobject      — gi.repository.GLib for the main loop
#   * python3-jinja2         — .network/.netdev/.conf template rendering
#   * dbus                   — the system bus itself (mdmx-network-ctrl.conf lives under
#                              /usr/share/dbus-1/system.d, which is read at daemon start)
#   * systemd                — systemctl restart of networkd + resolved
#   * mdmx-network           — supplies the shipped DHCP profile the daemon overrides;
#                              also pulls in systemd-networkd itself
RDEPENDS:${PN} = " \
    python3-core \
    python3-json \
    python3-dbus \
    python3-pygobject \
    python3-jinja2 \
    dbus \
    systemd \
    mdmx-network \
"

do_install() {
    install -d ${D}${bindir}
    install -m 0755 ${S}/mdmx-network-ctrl.py ${D}${bindir}/mdmx-network-ctrl

    install -d ${D}${systemd_unitdir}/system
    install -m 0644 ${S}/mdmx-network-ctrl.service \
        ${D}${systemd_unitdir}/system/mdmx-network-ctrl.service

    # dbus-1 system-bus policy. /usr/share is the vendor location that
    # dbus reads at boot; /etc is reserved for local overrides, which
    # we don't ship (the rootfs is read-only anyway).
    install -d ${D}${datadir}/dbus-1/system.d
    install -m 0644 ${S}/mdmx-network-ctrl.conf \
        ${D}${datadir}/dbus-1/system.d/mdmx-network-ctrl.conf
}

FILES:${PN} = " \
    ${bindir}/mdmx-network-ctrl \
    ${systemd_unitdir}/system/mdmx-network-ctrl.service \
    ${datadir}/dbus-1/system.d/mdmx-network-ctrl.conf \
"
