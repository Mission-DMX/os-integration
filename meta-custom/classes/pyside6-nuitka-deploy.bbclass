# Shared machinery for PySide6 apps shipped as Nuitka --standalone bundles.
# Extracted from the original mdmx-editor_git.bb so sibling apps (explorer,
# future tools) can inherit the same pdm-resolver / pip-prefix / patchelf
# pipeline without copy-pasting ~250 lines of workarounds.
#
# A consuming recipe must set:
#   PYSIDE6_INSTALL_PREFIX  — where the Nuitka bundle lands, e.g.
#                             "/opt/MissionDMX" (editor, flat) or
#                             "/opt/MissionDMX/explorer" (nested).
#   PYSIDE6_DIST_DIR        — basename of the pyside6-deploy output, as
#                             configured in that app's pysidedeploy.spec,
#                             e.g. "MissionDMX-Editor.dist".
#   PYSIDE6_BIN_NAME        — final binary name under PYSIDE6_INSTALL_PREFIX,
#                             e.g. "editor" or "explorer".
#   PYSIDE6_BIN_SRC_NAME    — Nuitka's pre-rename output; defaults to
#                             "main.bin" which is what pyside6-deploy
#                             produces for a `main_file = ...` of main.py.
#
# A consuming recipe is expected to:
#   - set SRC_URI / SRCREV / S as usual
#   - add any recipe-specific files (icons, .desktop, polkit) via
#     do_install:append — this class only lays down the Nuitka bundle.
#   - append to FILES:${PN} / RDEPENDS:${PN} for its extras.

inherit mime-xdg

PYSIDE6_BIN_SRC_NAME ?= "main.bin"

# python3-native supplies the interpreter Nuitka runs under; its version
# tracks poky's python3 recipe, which also becomes the target's python3 —
# so libpython versions between build and target stay in sync without
# pinning anything to the build host. The remaining DEPENDS are the system
# libs PySide6's Qt6 wheels dlopen during compile-time introspection.
DEPENDS = " \
    python3-native \
    python3-pip-native \
    desktop-file-utils \
    glib-2.0-native \
    libxkbcommon-native \
    libxcb-native \
    dbus-native \
    mesa-native \
    libx11-native \
    wayland-native \
    fontconfig-native \
"

# Nuitka emits a native binary and PySide6 is only shipped as x86_64 /
# aarch64 wheels on PyPI. Restrict to x86_64 — matches our qemux86-64 /
# genericx86-64 target.
COMPATIBLE_HOST = "(x86_64).*-linux"

# pdm sync pulls ~1 GB of wheels from PyPI; grant network access.
do_compile[network] = "1"

# Everything Nuitka links against is already inside the bundle. Skip the
# Yocto QA checks that don't apply to a self-contained /opt/ install of
# manylinux2014 blobs.
INSANE_SKIP:${PN} += "already-stripped ldflags rpaths textrel arch libdir file-rdeps buildpaths dev-so staticdev"
INHIBIT_PACKAGE_STRIP = "1"
INHIBIT_PACKAGE_DEBUG_SPLIT = "1"
INHIBIT_SYSROOT_STRIP = "1"

# RPM's file-deps generator would synthesise unresolvable Requires: for
# mangled-soname manylinux blobs (libcrypto-5409cd36.so.1.1.1k etc.).
# Yocto's shlib RDEPENDS already covers the real system libs.
SKIP_FILEDEPS:${PN} = "1"

# Mark every bundled .so as PRIVATE so the shlib generator neither
# registers them as providers nor demands they come from another
# package when a bundled binary links to them.
python populate_private_libs() {
    import subprocess
    from pathlib import Path

    prefix = d.getVar('PYSIDE6_INSTALL_PREFIX')
    if not prefix:
        return
    dist = Path(d.getVar('D')) / prefix.lstrip('/')
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
        sonames.add(soname or so.name)

    pn = d.getVar('PN')
    bb.note("populate_private_libs: %d sonames marked private" % len(sonames))
    d.setVar('PRIVATE_LIBS:%s' % pn, ' '.join(sorted(sonames)))
}

do_package[prefuncs] += "populate_private_libs"

export HOME = "${WORKDIR}/pip-home"

# Strip the cross-toolchain env so Nuitka's C-compiler shell-outs use the
# host's plain gcc, but keep native-sysroot bins on PATH.
python_venv_env() {
    unset CC CXX CPP AR AS LD NM OBJCOPY OBJDUMP RANLIB READELF STRIP
    unset CFLAGS CXXFLAGS CPPFLAGS LDFLAGS
    unset PKG_CONFIG PKG_CONFIG_PATH PKG_CONFIG_LIBDIR PKG_CONFIG_SYSROOT_DIR
    export PATH="${STAGING_BINDIR_NATIVE}:${STAGING_BINDIR_NATIVE}/python3-native:/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin"
}

# Build a .venv under ${S}/.venv/ via pdm-as-resolver + pip-with-prefix,
# because Yocto's python3-native sysconfig patch defeats venv-relative
# install destinations. See the long comment block in mdmx-editor's history
# for the full reasoning.
pyside6_prepare_venv() {
    mkdir -p ${S}/.venv/bin ${S}/.pdm-runner

    ${STAGING_BINDIR_NATIVE}/python3-native/python3 -m pip install \
        --no-cache-dir --target ${S}/.pdm-runner 'pdm<2.29'

    # Lock on demand: upstream repos that commit pdm.lock (editor) skip
    # this; recipes that vendor only pyproject.toml (explorer) need a
    # fresh resolve here. pdm lock is deterministic given a fixed PyPI
    # state, but drifts over time — fine for a sibling tool where strict
    # pinning would just mean regenerating by hand.
    if [ ! -f ${S}/pdm.lock ]; then
        PYTHONPATH="${S}/.pdm-runner" \
        PDM_PYTHON="${STAGING_BINDIR_NATIVE}/python3-native/python3" \
        PDM_PYTHON_USE_VENV=false \
            ${STAGING_BINDIR_NATIVE}/python3-native/python3 -m pdm lock
    fi

    PYTHONPATH="${S}/.pdm-runner" \
    PDM_PYTHON="${STAGING_BINDIR_NATIVE}/python3-native/python3" \
    PDM_PYTHON_USE_VENV=false \
        ${STAGING_BINDIR_NATIVE}/python3-native/python3 -m pdm export \
            --format requirements \
            --without-hashes \
            --group build \
            --output ${S}/.venv-requirements.txt

    # opencv-python -> headless (nuitka introspection fails without libGL).
    sed -i 's/^opencv-python==/opencv-python-headless==/' \
        ${S}/.venv-requirements.txt

    ${STAGING_BINDIR_NATIVE}/python3-native/python3 -m pip install \
        --no-cache-dir \
        --ignore-installed \
        --prefix ${S}/.venv \
        --requirement ${S}/.venv-requirements.txt

    # Link libpython dynamically; target image installs matching python3.
    sed -i 's/^extra_args = /extra_args = --static-libpython=no /' pysidedeploy.spec

    PYTHON_MM=$(${STAGING_BINDIR_NATIVE}/python3-native/python3 -c \
        'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')

    rm -f ${S}/.venv/bin/python ${S}/.venv/bin/python3 ${S}/.venv/bin/python$PYTHON_MM
    cat > ${S}/.venv/bin/python <<WRAPPER_EOF
#!/bin/sh
PYTHONPATH="${S}/.venv/lib/python$PYTHON_MM/site-packages\${PYTHONPATH:+:\$PYTHONPATH}" \\
LD_LIBRARY_PATH="${STAGING_LIBDIR_NATIVE}\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}" \\
    exec ${STAGING_BINDIR_NATIVE}/python3-native/python3 "\$@"
WRAPPER_EOF
    chmod +x ${S}/.venv/bin/python
    ln -sf python ${S}/.venv/bin/python3
    ln -sf python ${S}/.venv/bin/python$PYTHON_MM
}

pyside6_run_deploy() {
    PYTHON_MM=$(${STAGING_BINDIR_NATIVE}/python3-native/python3 -c \
        'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')

    PATH="${S}/.venv/bin:${PATH}" \
    LD_LIBRARY_PATH="${STAGING_LIBDIR_NATIVE}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
    PYTHONPATH="${S}/.venv/lib/python$PYTHON_MM/site-packages" \
    VIRTUAL_ENV="${S}/.venv" \
        ${STAGING_BINDIR_NATIVE}/python3-native/python3 - <<PYEOF
import sys
sys.argv = ["pyside6-deploy", "-c", "pysidedeploy.spec"]
from PySide6.scripts.pyside_tool import deploy
sys.exit(deploy())
PYEOF
}

# Default post-deploy hook: just rename the main binary. Recipes with
# extra assets to copy into the dist (editor's src/resources, src/configs)
# override via do_compile:append.
pyside6_post_deploy() {
    mv bin/${PYSIDE6_DIST_DIR}/${PYSIDE6_BIN_SRC_NAME} \
       bin/${PYSIDE6_DIST_DIR}/${PYSIDE6_BIN_NAME}
}

do_compile() {
    python_venv_env
    cd ${S}
    mkdir -p ${HOME}
    pyside6_prepare_venv
    pyside6_run_deploy
    pyside6_post_deploy
}

# Rewrite PT_INTERP on every ELF — Nuitka bakes Debian's loader path
# (/lib64/ld-linux-x86-64.so.2) and Yocto with usrmerge only ships the
# loader at /usr/lib/.
pyside6_patchelf_interp() {
    for f in $(find ${D}${PYSIDE6_INSTALL_PREFIX} -type f); do
        ${S}/.venv/bin/patchelf --set-interpreter \
            /usr/lib/ld-linux-x86-64.so.2 "$f" 2>/dev/null || true
    done
}

do_install() {
    python_venv_env

    install -d ${D}${PYSIDE6_INSTALL_PREFIX}
    # -rL (not cp -a) so target files get root:root under fakeroot
    # rather than the builder's uid/gid.
    cp -rL ${S}/bin/${PYSIDE6_DIST_DIR}/. ${D}${PYSIDE6_INSTALL_PREFIX}/
    chown -R 0:0 ${D}${PYSIDE6_INSTALL_PREFIX}
    chmod 0755 ${D}${PYSIDE6_INSTALL_PREFIX}/${PYSIDE6_BIN_NAME}

    pyside6_patchelf_interp
}

FILES:${PN} += "${PYSIDE6_INSTALL_PREFIX}"
