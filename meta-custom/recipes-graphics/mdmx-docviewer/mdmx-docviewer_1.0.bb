SUMMARY = "Minimal document viewer for PDF, Markdown, and RTF"
DESCRIPTION = "Small GTK3 + Poppler viewer wired in as the XDG default \
handler for application/pdf, text/markdown and (application|text)/rtf. Not \
shown in launchers (NoDisplay=true) — invoked from other applications via \
xdg-open / gio-open. Ships its own tiny Markdown → Pango-markup translator \
and RTF parser because none of the layers in this distro provide a \
Markdown or RTF renderer, and pulling in WebKit / a GNOME viewer stack \
just for scene-notes display isn't worth the image size."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

S = "${UNPACKDIR}"

SRC_URI = " \
    file://mdmx-docviewer \
    file://mdmx-docviewer.desktop \
    file://mimeapps.list \
"

# mime-xdg wires update-mime-database + update-desktop-database into the
# package's postinst/postrm, so the .desktop's MimeType entries land in
# the on-disk XDG association cache at image-build time (rootfs is
# read-only at runtime).
inherit allarch mime-xdg

RDEPENDS:${PN} = " \
    python3-core \
    python3-html \
    python3-io \
    python3-pygobject \
    python3-pycairo \
    gtk+3 \
    pango \
    gdk-pixbuf \
    poppler \
    poppler-data \
"

# The gobject-introspection.bbclass drops every .typelib under
# ${libdir}/girepository-1.0 into FILES:${PN} — for poppler that's the
# "poppler" main package (which also carries the CLI tools like
# pdftotext), NOT the libpoppler-glib split which only ships
# libpoppler-glib.so.*. If we RDEPEND on libpoppler-glib alone,
# gi.require_version("Poppler", "0.18") fails at runtime with
# "Namespace Poppler not available" because Poppler-0.18.typelib was
# never installed. Depending on "poppler" pulls libpoppler-glib in
# transitively via the shlib scanner. The Gtk/Gdk/Pango/GdkPixbuf
# typelibs are all in their respective main packages (already listed
# above), so no analogous fix is needed for those.

do_install() {
    install -d ${D}${bindir}
    install -m 0755 ${S}/mdmx-docviewer ${D}${bindir}/mdmx-docviewer

    install -d ${D}${datadir}/applications
    install -m 0644 ${S}/mdmx-docviewer.desktop \
        ${D}${datadir}/applications/mdmx-docviewer.desktop

    # System-wide XDG default-handler map. Precedence per the MIME apps
    # spec: /etc/xdg/mimeapps.list overrides /usr/share/applications/
    # mimeapps.list but is overridden by any per-user file in
    # $XDG_CONFIG_HOME. That's what we want — operator sessions have no
    # persistent config yet, so this file is the effective default.
    install -d ${D}${sysconfdir}/xdg
    install -m 0644 ${S}/mimeapps.list \
        ${D}${sysconfdir}/xdg/mimeapps.list
}

FILES:${PN} = " \
    ${bindir}/mdmx-docviewer \
    ${datadir}/applications/mdmx-docviewer.desktop \
    ${sysconfdir}/xdg/mimeapps.list \
"
