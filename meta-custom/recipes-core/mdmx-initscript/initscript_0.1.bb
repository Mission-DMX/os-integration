SUMMARY = "Install Postboot init script"
DESCRIPTION = "This script performs various initializations after boot, especially taking care of first run setup"
LICENSE = "GPLv3"
LIC_FILES_CHKSUM = "file://LICENSE;md5=1ebbd3e34237af26da5dc08a4e440464"
SRC_URI = " \
    file://user-init.sh \
    file://user-init.service \
"

LICENSE_PATH += "${LAYERDIR}/"

do_compile () {
    bbwarn "Init script recipe is being executed"
}

do_install () {
    install -d ${D}/${sbindir}
    install -m 0755 ${WORKDIR}/user-init.sh ${D}/${sbindir}

    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${WORKDIR}/user-init.service ${D}${systemd_system_unitdir}/system
}

NATIVE_SYSTEMD_SUPPORT = "1"
SYSTEMD_PACKAGES = "${PN}"
SYSTEMD_SERVICE:${PN} = "user-init.service"
inherit allarch systemd
