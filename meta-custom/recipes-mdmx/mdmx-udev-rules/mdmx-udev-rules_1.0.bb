SUMMARY = "MissionDMX udev rules for DMX adapters"
DESCRIPTION = "Grants the desktop 'user' account (dialout group) direct \
access to USB-attached DMX adapters so the realtime-fish engine does \
not need to run as root. Currently covers the Enttec DMX USB Pro (FTDI \
FT232 VID:PID 0403:6001) — fish opens the device through libftdi1 / \
libusb1, not /dev/ttyUSB*, so the GROUP= needs to land on the raw USB \
node under /dev/bus/usb/."

LICENSE = "BSD-3-Clause"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/BSD-3-Clause;md5=550794465ba0ec5312d6919e203a55f9"

S = "${UNPACKDIR}"

SRC_URI = "file://70-mdmx-usb-dmx.rules"

inherit allarch

do_install() {
    install -d ${D}${sysconfdir}/udev/rules.d
    install -m 0644 ${S}/70-mdmx-usb-dmx.rules \
        ${D}${sysconfdir}/udev/rules.d/70-mdmx-usb-dmx.rules
}

FILES:${PN} = "${sysconfdir}/udev/rules.d/70-mdmx-usb-dmx.rules"

RDEPENDS:${PN} = "udev"
