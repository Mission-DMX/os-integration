SUMMARY = "Powerful paging program similar to less (based on S-Lang)"
DESCRIPTION = "most is a paging program that displays, one windowful at a time, \
the contents of a file on a terminal. It pauses after each windowful and prints \
the file name, current line number, and the percentage of the file so far \
displayed in a status line. Unlike less, most can display multiple windows at \
once and natively handles binary, text and wrap modes."
HOMEPAGE = "https://www.jedsoft.org/most/"
SECTION = "console/utils"

LICENSE = "GPL-2.0-or-later"
LIC_FILES_CHKSUM = "file://COPYING;md5=18810669f13b87348459e611d31ab760"

# slang does the actual terminal handling; most just links -lslang.
# most's configure sets TERMCAP="" (no -ltermcap) whenever a terminfo dir
# exists on the build host — always true on a Yocto build host — so most
# itself does not link ncurses. Runtime terminfo lookups happen inside
# libslang.so, whose own NEEDED entry pulls ncurses into the target rootfs.
DEPENDS = "slang"

SRC_URI = "https://www.jedsoft.org/releases/most/most-${PV}.tar.gz \
           file://most.sh \
          "
SRC_URI[sha256sum] = "9455aeb8f826fa8385c850dc22bf0f22cf9069b3c3423fba4bf2c6f6226d9903"

UPSTREAM_CHECK_URI = "https://www.jedsoft.org/releases/most/"

S = "${UNPACKDIR}/most-${PV}"

# most's configure is autoconf-generated but JD_INIT aborts with
# "This software does not support configuring from another directory"
# unless pwd matches $srcdir — so S must equal B. autotools-brokensep
# keeps S == B while still giving us the standard do_configure that
# passes --prefix, --host, CC, CFLAGS, etc.
inherit autotools-brokensep

# Point the slang probe at the cross sysroot so configure doesn't scan
# /usr/lib / /usr/include on the build host. --without-x avoids a hard
# dep on X11 just for optional X selection-paste support, which this
# image (Wayland-only via sway) can't use anyway.
EXTRA_OECONF = " \
    --without-x \
    --with-slanginc=${STAGING_INCDIR} \
    --with-slanglib=${STAGING_LIBDIR} \
"

# RPATH='' matches how slang's own recipe neutralises most/slang's habit
# of baking -rpath=$libdir into the binary (yocto handles RUNPATH itself).
EXTRA_OEMAKE = "RPATH=''"

do_configure:prepend() {
    # Three patches to src/Makefile.in that upstream only gets right for
    # native builds — all three fire via the same sed invocation:
    #
    # 1) `$(INSTALL) -s` in the install rule invokes whatever `strip` is on
    #    PATH (host strip) during cross-builds, which can corrupt the target
    #    binary. Dropping -s lets yocto's package_do_split_debug handle it.
    #
    # 2) The $(EXEC) target depends on `slangversion`, which compiles
    #    chkslang as a target-arch binary and then tries to execute it from
    #    the build host to verify SLANG_VERSION >= 20000. That's impossible
    #    when cross-compiling. slang 2.3.3 from poky already satisfies the
    #    minimum, so drop the dep edge entirely — slangversion's own rule
    #    and the $(OBJDIR)/chkslang rule stay in place but become unreachable.
    #
    # 3) Belt-and-suspenders: also replace the chkslang invocation line
    #    inside slangversion's own recipe so that if any future target
    #    reintroduces the dep, it doesn't resurrect the cross-compile break.
    sed -i \
        -e 's/\$(INSTALL) -s/\$(INSTALL)/' \
        -e 's/^\(\$(EXEC):.*\) slangversion /\1 /' \
        -e 's|^\t\$(OBJDIR)/chkslang .*|\t@echo "skipping chkslang (cross-compile)"|' \
        ${S}/src/Makefile.in
}

do_install:append() {
    # most compiles MOST_SYSTEM_INITFILE=/etc/most.conf into the binary
    # and silently ignores a missing file at runtime, but shipping an
    # empty placeholder gives operators a well-known override location
    # without them having to guess where it lives.
    install -d ${D}${sysconfdir}
    touch ${D}${sysconfdir}/most.conf

    # /etc/profile.d/most.sh sets PAGER=most + MANPAGER=most so every
    # bash login (console or sway terminal) uses most without per-user
    # dotfile edits. Owned by this package so removing most also removes
    # the env exports — otherwise a stale PAGER=most would make shells
    # error out with "most: command not found" on every login.
    install -d ${D}${sysconfdir}/profile.d
    install -m 0644 ${UNPACKDIR}/most.sh ${D}${sysconfdir}/profile.d/most.sh
}

FILES:${PN} += " \
    ${sysconfdir}/most.conf \
    ${sysconfdir}/profile.d/most.sh \
"
