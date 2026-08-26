SUMMARY = "MissionDMX default network configuration"
DESCRIPTION = "Pulls in systemd-networkd + systemd-resolved and drops a \
wired-DHCP profile matching en*/eth* interfaces. On first boot both \
services get enabled and /etc/resolv.conf gets symlinked to resolved's \
stub, so IP + DNS come up automatically on the qemu test image or any \
hardware image with a wired NIC."

LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

S = "${UNPACKDIR}"

SRC_URI = " \
    file://20-wired.network \
    file://20-mdmx-network.preset \
"

inherit allarch

# Only systemd-networkd is split into its own subpackage; the resolved
# binary + unit ship inside the base ${systemd} package, which is
# always installed on a systemd-init image. So we only need to
# explicitly pull in systemd-networkd here.
RDEPENDS:${PN} = "systemd-networkd"

do_install() {
    install -d ${D}${sysconfdir}/systemd/network
    install -m 0644 ${S}/20-wired.network \
        ${D}${sysconfdir}/systemd/network/20-wired.network

    # Preset file — systemd's Yocto build runs `systemctl preset-all`
    # during rootfs assembly, which reads these files to decide which
    # services should be enabled by default. Both networkd and resolved
    # ship disabled by default; this flips them on.
    install -d ${D}${systemd_unitdir}/system-preset
    install -m 0644 ${S}/20-mdmx-network.preset \
        ${D}${systemd_unitdir}/system-preset/20-mdmx-network.preset
}

FILES:${PN} = " \
    ${sysconfdir}/systemd/network/20-wired.network \
    ${systemd_unitdir}/system-preset/20-mdmx-network.preset \
"
