SUMMARY = "Install Postboot init script"
DESCRIPTION = "This script performs various initializations after boot, especially taking care of first run setup"
LICENSE = "GPLv3"
SRC_URI = " \
    file://user-init.sh \
    file://user-init.service \
"

do_compile () {
}

do_install () {
    install -d ${D}/${sbindir}
    install -m 0755 ${WORKDIR}/user-init.sh ${D}/${sbindir}
    install -d ${D}${systemd_unitdir}/system/
    install -m 0644 ${WORKDIR}/user-init.service ${D}${systemd_unitdir}/system
}

NATIVE_SYSTEMD_SUPPORT = "1"
SYSTEMD_PACKAGES = "${PN}"
SYSTEMD_SERVICE_${PN} = "user-init.service"
inherit allarch systemd
