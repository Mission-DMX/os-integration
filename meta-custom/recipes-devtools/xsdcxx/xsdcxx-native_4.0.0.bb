SUMMARY = "CodeSynthesis XSD: W3C XML Schema to C++ data binding compiler (native only)"
DESCRIPTION = "xsdcxx generates C++ classes from XML Schema files. \
Required by the realtime-fish build. Installed only in the native \
sysroot; not shipped on the target."
HOMEPAGE = "https://www.codesynthesis.com/products/xsd/"

# xsd is dual-licensed: GPL v2 for the compiler, plus the FLOSSE (Free
# Libraries for Open Source Software Exception) for its runtime.
LICENSE = "GPL-2.0-only & FLOSSE"
LIC_FILES_CHKSUM = " \
    file://GPLv2;md5=eb723b61539feef013de476e68b5c50a \
    file://FLOSSE;md5=42d25a3b4b2b4178d3cb0f434fccfb68 \
    file://LICENSE;md5=79e31466c4d9f3a85f2f987c11ebcd83 \
"

# FLOSSE (Free Libraries for Open Source Software Exception) is
# CodeSynthesis-specific and not in Yocto's generic license set. Point
# SPDX generation at the FLOSSE file shipped in the tarball.
NO_GENERIC_LICENSE[FLOSSE] = "FLOSSE"

# CodeSynthesis publishes a stock x86_64 Linux binary tarball for xsdcxx.
# Building the compiler from source with their own build2/build system is
# non-trivial, and since this is a native-only tool needed only during
# realtime-fish's build, the pre-built binary is the pragmatic choice.
SRC_URI = "https://www.codesynthesis.com/download/xsd/4.0/linux-gnu/x86_64/xsd-4.0.0-x86_64-linux-gnu.tar.bz2"
SRC_URI[sha256sum] = "d01060cbf4b3a1e462a5c5ad1a5a6773b541766dbbb98e50c9efb8f2a2dd55b7"

S = "${WORKDIR}/xsd-4.0.0-x86_64-linux-gnu"

inherit native

# The pre-built tarball contains ready-made binaries and headers; nothing
# to compile. Just place them into the native sysroot.
do_configure[noexec] = "1"
do_compile[noexec] = "1"

do_install() {
    # The 4.0.0 tarball ships the compiler as bin/xsd. realtime-fish's
    # Makefile invokes it as `xsdcxx`, so install under both names.
    install -d ${D}${bindir}
    install -m 0755 ${S}/bin/xsd ${D}${bindir}/xsd
    ln -sf xsd ${D}${bindir}/xsdcxx

    install -d ${D}${includedir}
    cp -a ${S}/libxsd/xsd ${D}${includedir}/

    install -d ${D}${mandir}/man1
    install -m 0644 ${S}/doc/xsd.1 ${D}${mandir}/man1/xsd.1 || true
}

# This is host-side only; the target arch is x86_64 by definition of the tarball.
COMPATIBLE_HOST = "x86_64.*-linux"

# Skip the standard native QA checks that don't apply to a pre-built binary.
INSANE_SKIP:${PN} += "already-stripped ldflags textrel"
