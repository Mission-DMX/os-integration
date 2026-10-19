SUMMARY = "First-launch configurator for keyboard layout, timezone, and touchscreen mapping"
DESCRIPTION = "Autostarted by sway via /etc/sway/config.d. Reads \
~/.config/console-settings.ini for the saved xkb layout/variant, system \
timezone, and per-output touchscreen mapping; when complete it pushes \
everything into sway via i3ipc (plus timedatectl for the clock) and exits \
in under a second. If anything is missing it opens a GTK3 wizard: a layout \
dropdown parsed from xkb's base.lst, a timezone dropdown populated from \
`timedatectl list-timezones`, then a per-output 'tap-here' calibrator \
anchored with gtk-layer-shell whose device identification is done via \
evdev (sway's identifier collapses on duplicate touchscreen models). On \
commit the wizard writes a libinput quirks file via a pkexec helper so \
each physical touchscreen gets a distinct kernel name based on its stable \
udev ID_PATH, then restarts sway so libinput reads the new overrides. \
The rootfs is read-only, so the quirks file is stored under \
/var/lib/console-settings/ (bind-mounted from userdata); \
/etc/libinput/local-overrides.quirks is a symlink into that writable \
directory, created by tmpfiles.d on first boot."

LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

S = "${UNPACKDIR}"

SRC_URI = " \
    file://console-settings-daemon.py \
    file://install-touch-quirks \
    file://60-console-settings.conf \
    file://50-console-settings.rules \
    file://console-settings-tmpfiles.conf \
"

inherit allarch features_check

# wayland + gobject-introspection[-data] for the GTK3 wizard; polkit for
# the pkexec helper that writes /var/lib/console-settings/.
REQUIRED_DISTRO_FEATURES = "wayland polkit gobject-introspection gobject-introspection-data"

# Runtime chain:
#   * python3-pygobject + gtk+3 + gtk-layer-shell + gobject-introspection
#                        — GTK3 overlay windows anchored per-output via
#                          zwlr_layer_shell (required because xdg-shell
#                          clients can't bind themselves to a specific
#                          sway output).
#   * python-i3ipc       — talks to sway over $SWAYSOCK for get_outputs,
#                          get_inputs, and the `input ... map_to_output`
#                          command. Reused from python3 image.
#   * python3-pyudev + python3-evdev
#                        — identifying touch events by the firing
#                          /dev/input/eventN at wizard time (sway's IPC
#                          identifier collapses on duplicate models).
#                          The `user` is already in the input group via
#                          mdmx-user, so no root/udev-rules handling here.
#   * xkeyboard-config   — ships /usr/share/X11/xkb/rules/base.lst, which
#                          the wizard parses to populate the layout combo.
#   * libinput + sway    — target of the quirks file and of swaymsg.
#   * polkit             — enforces the JS rule shipped here.
#   * systemd            — provides timedatectl (used read-only for
#                          list-timezones to populate the wizard dropdown
#                          and show --property=Timezone as a fallback for
#                          the current-zone lookup) and the manage-units
#                          polkit action for restarting sway.service. The
#                          set-timezone path is unused on this image —
#                          the rootfs is RO so timedate1 can't rewrite
#                          /etc/localtime; the saved zone travels via
#                          the TZ env var set by sway-autostart's
#                          mdmx-tz.sh instead.
#   * tzdata             — /usr/share/zoneinfo so timedatectl list-timezones
#                          and $TZ lookups resolve zone names (yocto
#                          installs tzdata-core by default on systemd
#                          distros but keep it explicit).
RDEPENDS:${PN} = " \
    python3-core \
    python3-pygobject \
    python3-pyudev \
    python3-evdev \
    python-i3ipc \
    gtk+3 \
    gtk-layer-shell \
    gobject-introspection \
    polkit \
    xkeyboard-config \
    libinput \
    sway \
    systemd \
    tzdata \
    ttf-dejavu-sans \
"

do_install() {
    install -d ${D}${bindir}
    install -m 0755 ${S}/console-settings-daemon.py ${D}${bindir}/console-settings-daemon

    # libexec: the quirks writer is not user-facing — same reasoning as
    # mdmx-updater's install helper. Hiding it under /usr/libexec keeps
    # it off $PATH; the polkit rule only grants pkexec on this exact path.
    install -d ${D}${libexecdir}/console-settings-daemon
    install -m 0755 ${S}/install-touch-quirks \
        ${D}${libexecdir}/console-settings-daemon/install-touch-quirks

    install -d ${D}${sysconfdir}/sway/config.d
    install -m 0644 ${S}/60-console-settings.conf \
        ${D}${sysconfdir}/sway/config.d/60-console-settings.conf

    # Vendor polkit location — the rationale under console-menu_1.0.bb:67-78
    # applies verbatim: /etc/polkit-1/rules.d is chmod 0700 polkitd:root
    # and claiming it 0755 root:root would collide at do_rootfs.
    install -d -m 0755 ${D}${datadir}/polkit-1/rules.d
    install -m 0644 ${S}/50-console-settings.rules \
        ${D}${datadir}/polkit-1/rules.d/50-console-settings.rules

    # Writable location for the libinput quirks file. The rootfs is RO so
    # the real file lives in /var/lib/console-settings/ (bind-mounted from
    # the userdata partition); the /etc entry is just a symlink. The
    # target doesn't exist at image-build time; libinput tolerates a
    # dangling symlink as "no overrides", and the pkexec helper creates
    # the file on first wizard commit.
    install -d ${D}${sysconfdir}/libinput
    ln -sf /var/lib/console-settings/local-overrides.quirks \
        ${D}${sysconfdir}/libinput/local-overrides.quirks

    # tmpfiles.d entry lives under /usr/lib/tmpfiles.d (vendor location,
    # read by systemd-tmpfiles alongside /etc/tmpfiles.d) so we don't
    # claim a path under RO /etc.
    install -d ${D}${nonarch_libdir}/tmpfiles.d
    install -m 0644 ${S}/console-settings-tmpfiles.conf \
        ${D}${nonarch_libdir}/tmpfiles.d/console-settings.conf
}

FILES:${PN} = " \
    ${bindir}/console-settings-daemon \
    ${libexecdir}/console-settings-daemon/install-touch-quirks \
    ${sysconfdir}/sway/config.d/60-console-settings.conf \
    ${sysconfdir}/libinput/local-overrides.quirks \
    ${datadir}/polkit-1/rules.d/50-console-settings.rules \
    ${nonarch_libdir}/tmpfiles.d/console-settings.conf \
"
