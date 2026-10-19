SUMMARY = "On-screen virtual keyboard for wlroots-based Wayland compositors"
DESCRIPTION = "wvkbd is a Wayland on-screen keyboard that renders itself as a \
zwlr_layer_shell surface and types into the focused client via \
zwp_virtual_keyboard_v1. The kiosk uses the 'deskintl' layout (a \
desktop-oriented variant that keeps a full letter grid on wide screens, \
instead of mobintl's phone-style stacked rows). wvkbd 0.20 adds a \
built-in --auto mode that drives show/hide from zwp_input_method_v2 \
focus events, so osk-manager just has to pick wvkbd's startup flags \
based on whether a hardware keyboard is connected."
HOMEPAGE = "https://github.com/jjsullivan5196/wvkbd"
LICENSE = "GPL-3.0-only"
LIC_FILES_CHKSUM = "file://LICENSE;md5=1ebbd3e34237af26da5dc08a4e440464"

SRC_URI = "git://github.com/jjsullivan5196/wvkbd.git;protocol=https;branch=master"

# v0.20 tag — the newest tag at recipe-authoring time. master is already
# on an unreleased 0.21 (config.mk VERSION bump), so pinning to a tag
# avoids a floating head.
SRCREV = "6b41504a0cb58fd1163fa44692398fbd61f8905f"
PV = "0.20"

S = "${WORKDIR}/git"

# Upstream's PKGS line (Makefile):  wayland-client xkbcommon pangocairo.
# pangocairo pulls pango + cairo + their deps transitively through
# pkg-config; depend on both explicitly so the sstate hash is stable.
# wayland-scanner is a build-time tool from wayland-native; wayland-protocols
# contributes nothing here (wvkbd ships its own proto/*.xml under proto/),
# so it is NOT a dependency. scdoc builds the manpage.
DEPENDS = " \
    wayland \
    wayland-native \
    libxkbcommon \
    pango \
    cairo \
    scdoc-native \
"

# Upstream Makefile reads $PKG_CONFIG at build time (`PKG_CONFIG ?= pkg-config`)
# to resolve the --cflags/--libs for wayland-client, xkbcommon, and
# pangocairo. Without `inherit pkgconfig` the target bin isn't on PATH
# and every $(PKG_CONFIG) invocation shells out to a missing binary;
# the compile then falls back to flagless gcc and chokes on
# `pango/pangocairo.h: No such file or directory`. pkgconfig inheritance
# puts pkgconfig-native into DEPENDS and PATH, and exports
# PKG_CONFIG_PATH pointing at the recipe sysroot's .pc files.
inherit pkgconfig


# Upstream Makefile adds `-g` to CFLAGS unconditionally, which is fine
# in isolation — Yocto exports ${DEBUG_PREFIX_MAP} inside the CFLAGS
# env var, so `-fdebug-prefix-map=…` entries should rewrite the DWARF
# paths. But `config.mk` does `CFLAGS = -DVERSION=…` (plain `=`, not
# `+=`), which inside the main Makefile silently clobbers the inherited
# env value before any `+=` line gets a chance to run. The result is a
# build with -g but no prefix-map, which trips do_package_qa's
# `buildpaths` check on the stripped /usr/bin/.debug/wvkbd-deskintl.
#
# Flip that one line to `+=` so the Yocto-exported CFLAGS survives
# and config.mk's defines (-DVERSION, -D_XOPEN_SOURCE) stack on top.
do_configure() {
    sed -i 's/^CFLAGS *= */CFLAGS += /' ${S}/config.mk
}

# Build target picks the layout. Upstream Makefile encodes the layout as
# BIN=wvkbd-${LAYOUT}, so overriding LAYOUT at the make line is enough.
# config.deskintl.h / keymap.deskintl.h / layout.deskintl.h are shipped
# at the repo root.
WVKBD_LAYOUT = "deskintl"

# The Makefile reads $PREFIX from config.mk (default /usr/local). Override
# via the environment on the make line so `install` lands under /usr/bin
# instead of /usr/local/bin.
EXTRA_OEMAKE = "LAYOUT=${WVKBD_LAYOUT} PREFIX=${prefix} MANPREFIX=${mandir} CC='${CC}'"

do_compile() {
    oe_runmake
}

do_install() {
    oe_runmake install DESTDIR=${D}
}

FILES:${PN} = " \
    ${bindir}/wvkbd-${WVKBD_LAYOUT} \
    ${mandir}/man1/wvkbd.1* \
"
