SUMMARY = "Mission-DMX Project Editor (Nuitka-compiled)"
DESCRIPTION = "Qt/PySide6 desktop editor for the Mission-DMX lighting-show format. \
Built the same way upstream ships releases: pyside6-deploy drives Nuitka in \
standalone mode (see pysidedeploy.spec) and emits a self-contained bundle."
HOMEPAGE = "https://github.com/Mission-DMX/Project-Editor"
LICENSE = "GPL-3.0-or-later"
LIC_FILES_CHKSUM = "file://LICENSE;md5=1ebbd3e34237af26da5dc08a4e440464"

# gitsm (git + submodules) is required — src/resources/ contains
# symlinks into submodules/resources/, notably logo.png that Nuitka's
# --linux-icon flag reads. Without submodules the symlinks are dangling
# and the compile aborts on "icon path does not exist".
SRC_URI = "gitsm://github.com/Mission-DMX/Project-Editor.git;protocol=https;branch=main;name=editor"

SRCREV = "8cf57d94d6d5a4e7ec1a6dd54569d101176c9c77"
PV = "1.3.0+git${SRCPV}"

S = "${WORKDIR}/git"

inherit pyside6-nuitka-deploy

# Keep the editor installed flat under /opt/MissionDMX/ (unchanged from
# before the bbclass refactor) so the .desktop Exec path, hard-coded
# references, and the mdmx-explorer launcher's target all stay valid.
PYSIDE6_INSTALL_PREFIX = "/opt/MissionDMX"
PYSIDE6_DIST_DIR = "MissionDMX-Editor.dist"
PYSIDE6_BIN_NAME = "editor"

# Editor-specific: ship resources/ and configs/ next to the compiled
# binary (upstream reads them via relative paths at startup).
pyside6_post_deploy() {
    cp -rL src/resources bin/${PYSIDE6_DIST_DIR}/
    cp -rL src/configs   bin/${PYSIDE6_DIST_DIR}/
    mv bin/${PYSIDE6_DIST_DIR}/${PYSIDE6_BIN_SRC_NAME} \
       bin/${PYSIDE6_DIST_DIR}/${PYSIDE6_BIN_NAME}
}

do_install:append() {
    # Icon at the standard hicolor path so waybar/wofi/fuzzel can render it.
    if [ -f ${S}/src/resources/logo.png ]; then
        install -d ${D}${datadir}/icons/hicolor/256x256/apps
        install -m 0644 ${S}/src/resources/logo.png \
            ${D}${datadir}/icons/hicolor/256x256/apps/mdmx-editor.png
    fi

    # Generate the .desktop entry with upstream's own build_files/
    # build_desktop.py so the name/version/description track pyproject.toml
    # instead of drifting from a hand-copied template.
    install -d ${D}${datadir}/applications
    cd ${S} && ${S}/.venv/bin/python - <<PYEOF
import sys
from pathlib import Path
sys.path.insert(0, "build_files")
from build_desktop import write_desktop
from extract_metadata import load_metadata
write_desktop(
    load_metadata(),
    Path("${D}${datadir}/applications/mission-dmx.desktop"),
    Path("mdmx-editor"),
)
PYEOF

    # Show file / project cache paths the editor writes to at runtime.
    # /usr/local is on the read-only rootfs, so the show-file directory
    # has to live on the userdata partition; /var is bind-mounted from
    # userdata by mdmx-firstboot. A compatibility symlink keeps any
    # hard-coded /usr/local/share/missionDMX references working.
    install -d -m 0777 ${D}/var/lib/missionDMX
    install -d -m 0777 ${D}/var/cache/missionDMX
    install -d ${D}/usr/local/share
    ln -s /var/lib/missionDMX ${D}/usr/local/share/missionDMX
}

FILES:${PN} += " \
    ${datadir}/applications/mission-dmx.desktop \
    ${datadir}/icons/hicolor/256x256/apps/mdmx-editor.png \
    /usr/local/share/missionDMX \
    /var/lib/missionDMX \
    /var/cache/missionDMX \
"

RDEPENDS:${PN} = " \
    libnotify \
    fontconfig \
    ttf-dejavu-sans \
    ttf-dejavu-sans-mono \
    mesa \
    wayland \
    libxkbcommon \
    dbus \
    libgssapi-krb5 \
    brotli \
    libsdl2 \
    tzdata-core \
    tzdata-europe \
    tzdata-americas \
    tzdata-asia \
    tzdata-pacific \
"

# The shlib scan can only resolve an external soname to an RDEPENDS
# package if that package has actually been built. Listing libgssapi-krb5,
# brotli etc. here forces them into the build graph so their shlibs data
# is available for auto-resolution. libsdl2 is a special case: pysdl2
# loads it via ctypes.CDLL at import time, not as a DT_NEEDED entry, so
# no static analysis catches it.

RRECOMMENDS:${PN} = "realtime-fish"
