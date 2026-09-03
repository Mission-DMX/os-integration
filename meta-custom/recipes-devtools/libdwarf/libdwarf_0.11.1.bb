SUMMARY = "Library to access DWARF debugging information"
DESCRIPTION = "libdwarf reads DWARF debug information from ELF binaries and \
is required by cpptrace among others."
HOMEPAGE = "https://github.com/davea42/libdwarf-code"
LICENSE = "LGPL-2.1-or-later"
LIC_FILES_CHKSUM = "file://COPYING;md5=16ea26ea5a08cadb982cc10c28a521fd"

SRC_URI = "git://github.com/davea42/libdwarf-code.git;protocol=https;branch=main"
SRCREV = "c7b6535ce28850db00877c069af137cfa6ff5bf7"
PV = "0.11.1"

DEPENDS = "zlib zstd"

inherit cmake pkgconfig

EXTRA_OECMAKE = " \
    -DBUILD_SHARED=ON \
    -DBUILD_NON_SHARED=OFF \
    -DBUILD_DWARFDUMP=OFF \
    -DENABLE_DECOMPRESSION=ON \
"
