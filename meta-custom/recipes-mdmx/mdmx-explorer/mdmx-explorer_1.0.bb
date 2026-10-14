SUMMARY = "Mission-DMX graphical file explorer"
DESCRIPTION = "PySide6 file browser surfacing recently-used show files, the \
operator's home directory, automounted USB sticks and user-mounted SMB / NFS \
/ sshfs network shares. Hands show files off to mdmx-editor on double-click."
HOMEPAGE = "https://github.com/Mission-DMX/os-integration"
LICENSE = "GPL-3.0-or-later"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/GPL-3.0-only;md5=c79ff39f19dfec6d293b95dea7b07891"

SRC_URI = " \
    file://mdmx_explorer \
    file://main.py \
    file://pysidedeploy.spec \
    file://pyproject.toml \
    file://50-mdmx-explorer.rules \
    file://mdmx-explorer-mount.sh \
    file://mdmx-explorer.desktop \
    file://mdmx-explorer.png \
"

S = "${WORKDIR}/sources"
UNPACKDIR = "${S}"

inherit pyside6-nuitka-deploy

PYSIDE6_INSTALL_PREFIX = "/opt/MissionDMX/explorer"
# pyside6-deploy names the output dir after [app].title in pysidedeploy.spec
# (→ bin/mdmx-explorer.dist/) while Nuitka itself still names the binary
# after the main script's stem (→ main.bin). We rename main.bin to
# `explorer` in pyside6_post_deploy.
PYSIDE6_DIST_DIR = "mdmx-explorer.dist"
PYSIDE6_BIN_NAME = "explorer"

do_install:append() {
    # Icon at the standard hicolor path.
    install -d ${D}${datadir}/icons/hicolor/256x256/apps
    install -m 0644 ${S}/mdmx-explorer.png \
        ${D}${datadir}/icons/hicolor/256x256/apps/mdmx-explorer.png

    # Fuzzel/application-launcher entry.
    install -d ${D}${datadir}/applications
    install -m 0644 ${S}/mdmx-explorer.desktop \
        ${D}${datadir}/applications/mdmx-explorer.desktop

    # Polkit rule allowing uid 1000 (user "user") to pkexec the mount
    # helper without an auth prompt. Install under the polkit vendor dir
    # /usr/share/polkit-1/rules.d/ (not /etc/polkit-1/rules.d/, which
    # polkit owns as 0700 polkitd:root — packaging a file there would
    # conflict with the polkit package). Same pattern as 50-mdmx-updater.
    install -d -m 0755 ${D}${datadir}/polkit-1/rules.d
    install -m 0644 ${S}/50-mdmx-explorer.rules \
        ${D}${datadir}/polkit-1/rules.d/50-mdmx-explorer.rules

    # Privileged mount helper, root-owned, 0755.
    install -d ${D}${libexecdir}
    install -m 0755 ${S}/mdmx-explorer-mount.sh \
        ${D}${libexecdir}/mdmx-explorer-mount
}

FILES:${PN} += " \
    ${datadir}/applications/mdmx-explorer.desktop \
    ${datadir}/icons/hicolor/256x256/apps/mdmx-explorer.png \
    ${datadir}/polkit-1/rules.d/50-mdmx-explorer.rules \
    ${libexecdir}/mdmx-explorer \
"

RDEPENDS:${PN} += " \
    polkit \
    cifs-utils \
    nfs-utils-client \
    sshfs-fuse \
    xdg-utils \
    mdmx-editor \
    mdmx-docviewer \
    fontconfig \
    ttf-dejavu-sans \
    ttf-dejavu-sans-mono \
    mesa \
    wayland \
    libxkbcommon \
    dbus \
"
