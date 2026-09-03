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

# The generated mission-dmx.desktop declares
# MimeType=application/x-mdmx-showfile — Yocto's QA insists on
# mime-xdg to wire desktop-database and mime-database updates into
# the package's postinst/postrm.
inherit mime-xdg

# python3-native gives us Python 3.13 (matching pyproject.toml). We had
# hoped to drive the install with pdm as upstream requests, but Yocto's
# python3-native ships a sysconfig hard-coded to STAGING_LIBDIR — every
# venv/pdm path resolves to the recipe sysroot instead of the project's
# .venv/. See do_compile for the full rationale; net effect is we're
# stuck with pip + `--prefix`, which does explicitly override sysconfig.
DEPENDS = "python3-native python3-pip-native desktop-file-utils"

# BUILD HOST REQUIREMENTS (Debian/Ubuntu — installed via apt):
#   python3.13          — Nuitka's cc compiles a binary that dlopens the
#                         host libpython3.13.so.1.0 at runtime.
#   python3.13-dev      — Nuitka needs Python.h to compile the generated
#                         C code (even with --static-libpython=no).
#   libglib2.0-0        — dlopen'd by Qt6 during pyside6-deploy's
#                         compile-time introspection.
#   libxkbcommon0 libxcb1 libdbus-1-3
#                       — same story, transitive Qt6 deps.
# We can't express these through DEPENDS since they're host-side
# packages, not Yocto recipes. Missing any of them surfaces as a
# specific FATAL from Nuitka or PySide6 during do_compile.

# Nuitka emits a native binary and PySide6 is only shipped as x86_64 /
# aarch64 wheels on PyPI. Restrict this recipe to x86_64 targets — which
# is what our qemux86-64 / genericx86-64 image uses — so we can rely on
# the build host to be an x86_64 machine as well.
COMPATIBLE_HOST = "(x86_64).*-linux"

# pdm sync pulls ~1 GB of wheels from PyPI (Qt6, opencv, aiortc,
# onnxruntime-openvino, ...). Enumerating each wheel as a SRC_URI entry
# would be unmaintainable — grant network access to do_compile instead.
do_compile[network] = "1"

# Everything Nuitka links against is already inside the bundle. Skip the
# Yocto QA checks that don't apply to a self-contained /opt/ install of
# manylinux2014 blobs.
INSANE_SKIP:${PN} += "already-stripped ldflags rpaths textrel arch libdir file-rdeps buildpaths dev-so staticdev"
INHIBIT_PACKAGE_STRIP = "1"
INHIBIT_PACKAGE_DEBUG_SPLIT = "1"
INHIBIT_SYSROOT_STRIP = "1"

# Nuitka's --standalone bundle ships private copies of libpython3.13,
# libcrypto, libssl, libffi, libexpat, libuuid, liblzma, all of Qt6,
# ffmpeg, brotli, openssl 1.1 blobs from manylinux2014 wheels, ...
# Left alone, Yocto's automatic ELF analysis would (a) register these
# .so files as another provider of system-owned sonames (→ "Multiple
# shlib providers"), and (b) via RPM's file-deps generator, synthesise
# Requires: entries with mangled sonames like libcrypto-5409cd36.so.
# 1.1.1k that dnf can't resolve.
#
# We solve (a) with PRIVATE_LIBS — populated dynamically by scanning
# the bundle for SONAMEs so the shlib generator treats every bundled
# library as private (not registered as a provider, and not required
# externally when other bundled binaries link against it). External
# DT_NEEDED entries (libgssapi_krb5.so.2, libbrotlidec.so.1, ...) fall
# through to Yocto's shlib provider DB, which maps them back to the
# packages that install them and adds those to RDEPENDS automatically.
#
# We solve (b) by leaving SKIP_FILEDEPS on for RPM's own generator;
# Yocto's shlib RDEPENDS already covers the same libs from a saner
# source, so RPM's mangled-soname Requires: are pure noise here.
SKIP_FILEDEPS:${PN} = "1"

python populate_private_libs() {
    import subprocess
    from pathlib import Path

    dist = Path(d.getVar('D')) / 'opt' / 'MissionDMX'
    if not dist.exists():
        return

    sonames = set()
    for so in dist.rglob('*.so*'):
        if not so.is_file():
            continue
        soname = None
        try:
            out = subprocess.run(
                ['readelf', '-d', str(so)],
                capture_output=True, text=True, check=False,
            )
            for line in out.stdout.splitlines():
                if 'SONAME' in line and '[' in line and ']' in line:
                    soname = line[line.rfind('[') + 1:line.rfind(']')]
                    break
        except Exception:
            pass
        # Fall back to the filename for libs Nuitka mangles per
        # manylinux2014 convention (soname == filename in those cases).
        sonames.add(soname or so.name)

    pn = d.getVar('PN')
    bb.note("populate_private_libs: %d sonames marked private" % len(sonames))
    d.setVar('PRIVATE_LIBS:%s' % pn, ' '.join(sorted(sonames)))
}

do_package[prefuncs] += "populate_private_libs"

# Nuitka calls the C compiler directly; we want the *host* toolchain, not
# Yocto's cross-gcc that leaks into PATH via the recipe-sysroot. Nudge PATH
# and env vars back to the build machine's system defaults before invoking
# pip / pyside6-deploy.
export HOME = "${WORKDIR}/pip-home"

python_venv_env() {
    unset CC CXX CPP AR AS LD NM OBJCOPY OBJDUMP RANLIB READELF STRIP
    unset CFLAGS CXXFLAGS CPPFLAGS LDFLAGS
    unset PKG_CONFIG PKG_CONFIG_PATH PKG_CONFIG_LIBDIR PKG_CONFIG_SYSROOT_DIR
    export PATH="/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin"
}

do_compile() {
    python_venv_env

    cd ${S}
    mkdir -p ${HOME}

    # Yocto's python3-native has a sysconfig patched to hard-code
    # LIBDIR at ${STAGING_LIBDIR} (see poky's python3_%.bb, the sed
    # over _sysconfigdata). That defeats the venv-relative install
    # destination logic in Python's own venv, pdm-installer, and pip's
    # --python re-exec: every wheel ends up under recipe-sysroot-native
    # instead of the project's .venv/, and .venv/bin/pyside6-deploy is
    # never generated. We can't drive the install through `pdm sync`
    # for the same reason.
    #
    # What we CAN still do is use pdm as the resolver: `pdm export`
    # only reads pdm.lock and prints a requirements.txt — it never
    # touches sysconfig — so the version pins that upstream ships stay
    # authoritative even when they change. The actual install goes
    # through `pip install --prefix`, which is documented to override
    # sysconfig's install layout, and .venv/bin/python is fronted by
    # a shell wrapper so pysidedeploy.spec's `python_path = .venv/bin/
    # python` reference stays working (nuitka spawns it during
    # compile).
    mkdir -p ${S}/.venv/bin ${S}/.pdm-runner

    # Bootstrap pdm into a scratch dir; --target is a flat drop and
    # bypasses sysconfig, so it doesn't hit the STAGING_LIBDIR bug.
    ${STAGING_BINDIR_NATIVE}/python3-native/python3 -m pip install \
        --no-cache-dir --target ${S}/.pdm-runner pdm

    # Translate pdm.lock into a plain requirements.txt via pdm's own
    # resolver output. `-G build` opts the [dependency-groups.build]
    # entries (Nuitka, patchelf) in alongside the default project deps.
    PYTHONPATH="${S}/.pdm-runner" \
        ${STAGING_BINDIR_NATIVE}/python3-native/python3 -m pdm export \
            --format requirements \
            --without-hashes \
            --group build \
            --output ${S}/.venv-requirements.txt

    # Substitute opencv-python -> opencv-python-headless: pdm.lock pins
    # the GUI variant which pulls libGL/libQt at import time, and
    # nuitka's anti-bloat plugin fails during compile-time cv2
    # introspection when libGL.so.1 isn't dlopen-able. The editor only
    # uses cv2 for image processing (autotrack), never for cv2.imshow,
    # so the headless variant (same API, same version numbers) is a
    # drop-in replacement.
    sed -i 's/^opencv-python==/opencv-python-headless==/' \
        ${S}/.venv-requirements.txt

    # Materialise the pdm-resolved versions into .venv/.
    # --ignore-installed forces a fresh install into --prefix regardless
    # of what's already present in the base interpreter's site-packages.
    # Without it, pip tries to "upgrade" packages Yocto's python3-pip-
    # native staged into the recipe sysroot (e.g. packaging 24.2), and
    # then fails on uninstall because those Yocto-staged packages don't
    # ship RECORD files.
    ${STAGING_BINDIR_NATIVE}/python3-native/python3 -m pip install \
        --no-cache-dir \
        --ignore-installed \
        --prefix ${S}/.venv \
        --requirement ${S}/.venv-requirements.txt

    # Nuitka's default is to link libpython statically, which needs
    # python3-dev headers on the build host. Rather than adding that as
    # a host requirement, tell nuitka to link libpython dynamically. The
    # target image already installs `python3`, so libpython3.13.so.1.0
    # is present at runtime.
    sed -i 's/^extra_args = /extra_args = --static-libpython=no /' pysidedeploy.spec

    # Wrapper for .venv/bin/python — runs the *host* python3 with our
    # site-packages injected via PYTHONPATH. pyside6-deploy will
    # subprocess-invoke this path during nuitka's compile.
    #
    # Why host python3 rather than python3-native: PySide6's Qt libs
    # dlopen a swath of system libs (glib, X11, dbus, libGL, ...) that
    # aren't part of Yocto's uninative sysroot. We can't cleanly mix
    # uninative libc with host system libs (the previous attempt with
    # LD_LIBRARY_PATH augmentation segfaulted on ABI drift). The host
    # already has a self-consistent x86_64 Linux environment with all
    # of those libs, so we use it for the compile stage. This does
    # require the build host to have Python 3.13 available at
    # /usr/bin/python3 — matching the pyproject.toml requires-python.
    # rm -f first so a leftover file from a previous failed compile
    # can't block the redirect with "Permission denied".
    rm -f ${S}/.venv/bin/python ${S}/.venv/bin/python3 ${S}/.venv/bin/python3.13
    cat > ${S}/.venv/bin/python <<WRAPPER_EOF
#!/bin/sh
PYTHONPATH="${S}/.venv/lib/python3.13/site-packages\${PYTHONPATH:+:\$PYTHONPATH}" \\
    exec /usr/bin/python3 "\$@"
WRAPPER_EOF
    chmod +x ${S}/.venv/bin/python
    ln -sf python ${S}/.venv/bin/python3
    ln -sf python ${S}/.venv/bin/python3.13

    # Kick off pyside6-deploy / nuitka using the host interpreter.
    # LD_LIBRARY_PATH points at Debian's multi-arch lib dirs so
    # nuitka's compile-time PySide6 introspection subprocess can dlopen
    # libglib-2.0 / libX11 / libdbus (Qt6's transitive deps). Yocto's
    # own LD_LIBRARY_PATH (pointing at uninative) is dropped for this
    # invocation to keep host Qt libs consistent with host glibc.
    # VIRTUAL_ENV is set so pyside6-deploy's is_venv() check (which
    # literally just does `os.environ.get("VIRTUAL_ENV")`) skips its
    # interactive "install deploy deps?" prompt.
    # .venv/bin on PATH lets Nuitka find the `patchelf` shim from the
    # pypi patchelf wheel during --standalone mode.
    PATH="${S}/.venv/bin:${PATH}" \
    LD_LIBRARY_PATH="/usr/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu" \
    PYTHONPATH="${S}/.venv/lib/python3.13/site-packages" \
    VIRTUAL_ENV="${S}/.venv" \
        /usr/bin/python3 - <<PYEOF
import sys
sys.argv = ["pyside6-deploy", "-c", "pysidedeploy.spec"]
from PySide6.scripts.pyside_tool import deploy
sys.exit(deploy())
PYEOF
    cp -rL src/resources bin/MissionDMX-Editor.dist/
    cp -rL src/configs   bin/MissionDMX-Editor.dist/
    mv bin/MissionDMX-Editor.dist/main.bin bin/MissionDMX-Editor.dist/editor
}

do_install() {
    python_venv_env

    install -d ${D}/opt/MissionDMX
    # cp -a would preserve the builder's uid/gid on every file, which
    # trips Yocto's "host contamination" packaging QA (uid 1000 isn't a
    # valid target user). -rL copies without preserving ownership; the
    # subsequent chown -R re-stamps everything to root:root under
    # fakeroot.
    cp -rL ${S}/bin/MissionDMX-Editor.dist/. ${D}/opt/MissionDMX/
    chown -R 0:0 ${D}/opt/MissionDMX
    chmod 0755 ${D}/opt/MissionDMX/editor

    # Nuitka baked Debian's ELF interpreter path
    # (/lib64/ld-linux-x86-64.so.2) into the compiled binary, but Yocto
    # with usrmerge only ships the loader at /usr/lib/ld-linux-x86-64.so.2
    # (no /lib64 directory exists), so execve() fails on target with
    # "cannot execute: required file not found". Rewrite PT_INTERP on
    # every ELF that has one — mainly the top-level `editor` executable;
    # .so files have no PT_INTERP and patchelf will simply exit non-zero
    # on them, which we swallow.
    for f in $(find ${D}/opt/MissionDMX -type f); do
        ${S}/.venv/bin/patchelf --set-interpreter \
            /usr/lib/ld-linux-x86-64.so.2 "$f" 2>/dev/null || true
    done

    # Icon at the standard hicolor path so waybar/wofi/fuzzel can render it.
    if [ -f ${S}/src/resources/logo.png ]; then
        install -d ${D}${datadir}/icons/hicolor/256x256/apps
        install -m 0644 ${S}/src/resources/logo.png \
            ${D}${datadir}/icons/hicolor/256x256/apps/mdmx-editor.png
    fi

    # Generate the .desktop entry with upstream's own build_files/
    # build_desktop.py so the name/version/description track pyproject.toml
    # instead of drifting from a hand-copied template. The icon field is
    # passed as an icon-theme name ("mdmx-editor") — the PNG installed
    # above at hicolor/256x256/apps/mdmx-editor.png is what the desktop
    # environment will resolve it to.
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
    # /usr/local is on the read-only rootfs, so the show-file directory has
    # to live on the userdata partition; /var is bind-mounted from userdata
    # by mdmx-firstboot. The initial (empty) dir is created in the rootfs's
    # /var and gets seeded onto userdata on first boot. A compatibility
    # symlink at /usr/local/share/missionDMX -> /var/lib/missionDMX keeps
    # any hard-coded editor references working.
    install -d -m 0777 ${D}/var/lib/missionDMX
    install -d -m 0777 ${D}/var/cache/missionDMX
    install -d ${D}/usr/local/share
    ln -s /var/lib/missionDMX ${D}/usr/local/share/missionDMX
}

FILES:${PN} = " \
    /opt/MissionDMX \
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

# The shlib scan can only *resolve* an external soname to an RDEPENDS
# package if that package has actually been built — its shlibs data has
# to be present in Yocto's pkgdata/shlibs2/. If nothing else in the
# image pulls libgssapi-krb5 / brotli / … in, those recipes are never
# built and the scan silently fails to resolve. Listing them here
# forces them into the build graph, which makes their shlibs data
# available for auto-resolution *and* guarantees the shared libs are
# installed at runtime.
#
# libsdl2 is a special case: pysdl2 loads it via ctypes.CDLL at
# import time, not as a DT_NEEDED entry, so no static analysis catches
# it. These runtime dlopen deps have to be added by hand as they
# surface.

RRECOMMENDS:${PN} = "realtime-fish"
