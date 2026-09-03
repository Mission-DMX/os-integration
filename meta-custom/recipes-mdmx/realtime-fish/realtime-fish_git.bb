SUMMARY = "Mission-DMX realtime lighting engine (fish)"
DESCRIPTION = "The realtime backend of Mission-DMX. Translates the user's \
lighting show into DMX/Art-Net output in hard real time."
HOMEPAGE = "https://github.com/Mission-DMX/realtime-fish"
LICENSE = "GPL-3.0-or-later"
LIC_FILES_CHKSUM = "file://LICENSE;md5=1ebbd3e34237af26da5dc08a4e440464"

SRC_URI = "gitsm://github.com/Mission-DMX/realtime-fish.git;protocol=https;branch=main"
SRCREV = "56f0e68b708e7e9ca3626e1aa146c2ba19d2a909"
PV = "0.1+git${SRCPV}"

# The upstream .gitmodules file references some submodules over SSH
# (git@github.com: / ssh://git@github.com/), which requires SSH
# credentials configured on every builder. Rewrite those to anonymous
# HTTPS so the fetch works on any machine. Mirrors bitbake's default
# FETCHCMD_git (see bb/fetch2/git.py) plus two insteadOf entries.
FETCHCMD_git = "git \
    -c gc.autoDetach=false \
    -c core.pager=cat \
    -c safe.bareRepository=all \
    -c clone.defaultRemoteName=origin \
    -c url.https://github.com/.insteadOf=ssh://git@github.com/ \
    -c url.https://github.com/.insteadOf=git@github.com:"

# Native build tools + target libraries
DEPENDS = " \
    protobuf-native \
    xsdcxx-native \
    libxsd \
    protobuf \
    libnl \
    libev \
    spdlog \
    xerces-c \
    libusb1 \
    libftdi \
    lua \
    alsa-lib \
    libeigen \
    fftw \
    sox \
    pulseaudio \
    libsamplerate0 \
    fmt \
    cpptrace \
    libdwarf \
"

inherit pkgconfig

# The upstream Makefile hard-codes -march=native and -mavx2, which is bad
# for cross-compilation. Neutralise the machine-tune flags and let Yocto's
# CFLAGS/CXXFLAGS drive optimisation.
EXTRA_OEMAKE = "MARCH_ARGS='' BUILD_MODE=Release"

do_configure() {
    # Yocto's libusb1 and libftdi recipes provide pkg-config modules
    # named 'libusb-1.0' and 'libftdi1' respectively; the upstream
    # Makefile asks for the old 'libusb' / 'libftdi' names via the
    # ${PKG_TOOL} variable, so match on the --cflags/--libs arguments.
    sed -i 's|--cflags libusb\b|--cflags libusb-1.0|g' ${S}/Makefile
    sed -i 's|--libs libusb\b|--libs libusb-1.0|g' ${S}/Makefile
    sed -i 's|--cflags libftdi\b|--cflags libftdi1|g' ${S}/Makefile
    sed -i 's|--libs libftdi\b|--libs libftdi1|g' ${S}/Makefile

    # -I/usr/local/include is host-side and trips Yocto's
    # -Werror=poison-system-directories cross-compilation guard.
    sed -i 's| -I/usr/local/include||g' ${S}/Makefile

    # The upstream Makefile never threads LDFLAGS into its link commands
    # (every link is "${CXX} ... ${LFLAGS}"), which drops two things
    # Yocto's TARGET_LDFLAGS supplies: --hash-style=gnu (triggers the
    # 'ldflags: missing GNU_HASH' QA error) and -fdebug-prefix-map=... (the
    # LTO backend re-emits debug info at link time, so without the map the
    # workdir path leaks into .debug/fish and trips the 'buildpaths' QA).
    # Inject $(LDFLAGS) into LFLAGS before the first LFLAGS assignment so
    # both flag groups reach every ${CXX} link invocation.
    sed -i '0,/^LFLAGS += /{s|^LFLAGS += |LFLAGS += $(LDFLAGS)\nLFLAGS += |}' ${S}/Makefile
}

do_compile() {
    oe_runmake -j${@oe.utils.cpu_count()}
}

do_install() {
    install -d ${D}${bindir}
    install -m 0755 ${S}/bin/fish ${D}${bindir}/fish

    if [ -d ${S}/bin/tools ]; then
        install -d ${D}${libexecdir}/fish
        for tool in sample_xml_generator cmhelpdatagen ftdi_test ioboardctrl; do
            if [ -x ${S}/bin/tools/${tool} ]; then
                install -m 0755 ${S}/bin/tools/${tool} ${D}${libexecdir}/fish/${tool}
            fi
        done
    fi
}

FILES:${PN} += "${libexecdir}/fish"
