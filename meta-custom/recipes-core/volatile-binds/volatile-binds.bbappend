# local.conf sets VOLATILE_BINDS = "" so none of the tmpfs bind services get
# generated (they would shadow the userdata bind mounts of /var and /home
# managed by mdmx-firstboot). But volatile-binds's do_install still runs
# `install -d ${D}${systemd_system_unitdir}` unconditionally, and its
# FILES:${PN} only globs *.service — the resulting empty
# /usr/lib/systemd/system directory trips do_package's installed-vs-shipped
# QA check. Prune the empty directory chain so nothing is shipped.
do_install:append() {
    if [ -d ${D}${systemd_system_unitdir} ]; then
        rmdir --ignore-fail-on-non-empty -p ${D}${systemd_system_unitdir} || true
    fi
}
