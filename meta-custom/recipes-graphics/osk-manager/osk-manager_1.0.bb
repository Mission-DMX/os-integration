SUMMARY = "Lifecycle manager and control surface for the wvkbd on-screen keyboard"
DESCRIPTION = "Spawns wvkbd-deskintl with flags selected from live hardware \
state (adds --auto when no physical keyboard is detected so text-input \
focus pops the OSK, drops it when a USB keyboard appears), respawns \
wvkbd when the keyboard set changes, and exposes a Unix socket at \
\$XDG_RUNTIME_DIR/osk.sock accepting show / hide / toggle / status \
one-shot commands. The waybar custom module and the sway \$mod+k \
binding both lower to oskctl calls on that socket."

LICENSE = "BSD-3-Clause"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/BSD-3-Clause;md5=550794465ba0ec5312d6919e203a55f9"

S = "${UNPACKDIR}"

SRC_URI = " \
    file://osk-manager.py \
    file://oskctl \
    file://70-osk.conf \
"

inherit allarch

# Runtime chain:
#   * python3-core        — base interpreter used by both scripts.
#   * python3-pyudev      — input-subsystem monitor for keyboard
#                           add/remove events; already pulled in by
#                           console-settings-daemon, listed explicitly
#                           so osk-manager stays installable without it.
#   * python3-threading   — Timer/RLock/Thread live in the stdlib's
#                           threading module; split out into its own
#                           package in Yocto's python3 split.
#   * python3-logging     — stdlib logging module, also split-packaged.
#   * python3-json        — stdlib json.dumps for the socket reply.
#   * wvkbd               — the actual OSK binary this daemon drives.
#                           Without this RDEPENDS osk-manager's startup
#                           check (shutil.which) aborts immediately.
#   * mdmx-user           — the kiosk `user` must be in `input` for
#                           pyudev's /dev/input/* walk to succeed.
RDEPENDS:${PN} = " \
    python3-core \
    python3-pyudev \
    python3-threading \
    python3-logging \
    python3-json \
    wvkbd \
    mdmx-user \
"

do_install() {
    install -d ${D}${bindir}
    install -m 0755 ${S}/osk-manager.py ${D}${bindir}/osk-manager
    install -m 0755 ${S}/oskctl         ${D}${bindir}/oskctl

    install -d ${D}${sysconfdir}/sway/config.d
    install -m 0644 ${S}/70-osk.conf    ${D}${sysconfdir}/sway/config.d/70-osk.conf
}

FILES:${PN} = " \
    ${bindir}/osk-manager \
    ${bindir}/oskctl \
    ${sysconfdir}/sway/config.d/70-osk.conf \
"
