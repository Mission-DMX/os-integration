SUMMARY = "MediaMTX ready-to-use RTSP/RTMP/HLS/WebRTC/SRT server and proxy"
DESCRIPTION = "Go-based media server by bluenviron, shipped in the image \
but not started at boot. Operators run it on demand via `systemctl start \
mediamtx` or by invoking `/usr/bin/mediamtx` directly from a shell. \
Default listeners: RTSP 8554, RTMP 1935, HLS 8888, WebRTC 8889, SRT 8890, \
control API 9997 (all > 1024 so no CAP_NET_BIND_SERVICE)."
HOMEPAGE = "https://github.com/bluenviron/mediamtx"

LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://src/${GO_IMPORT}/LICENSE;md5=77fd2623bd5398430be5ce60489c2e81"

GO_IMPORT = "github.com/bluenviron/mediamtx"
GO_INSTALL = "${GO_IMPORT}"

# Pin to v1.14.0: this is the last MediaMTX release whose go.mod declares
# `go 1.24.x`. v1.15.0+ bumped the directive to 1.25+ and v1.21.3 to
# 1.27, neither of which the in-tree go_1.24.6.bb can satisfy under a
# strict GOTOOLCHAIN. Bumping PV past 1.14 requires a matching Go
# toolchain bump in poky first.
SRC_URI = " \
    git://${GO_IMPORT};protocol=https;nobranch=1;tag=v${PV};destsuffix=${BPN}-${PV}/src/${GO_IMPORT} \
    https://github.com/video-dev/hls.js/releases/download/v${HLSJS_VERSION}/release.zip;name=hlsjs;subdir=hlsjs \
    file://mediamtx.service \
"
SRCREV = "c80220eb7c91b74a828ca231b27412005db51f68"

# hls.js version + release-zip sha256 pinned by MediaMTX v1.14.0 at
# internal/servers/hls/hlsjsdownloader/{VERSION,HASH}. Check both files
# when bumping PV; if either changed, update HLSJS_VERSION and the
# hlsjs.sha256sum accordingly.
HLSJS_VERSION = "1.6.9"
SRC_URI[hlsjs.sha256sum] = "747b842f8868cc59783b2e2695ee56ccc248ff295035b49c2ad0fc7378a933cc"

inherit go-mod systemd features_check

REQUIRED_DISTRO_FEATURES = "systemd"

export GOPROXY = "https://proxy.golang.org,direct"

# Dependency resolution happens at compile-time (matches influxdb/etcd
# pattern in meta-oe). Yocto's offline-build model allows this because
# do_fetch itself does not touch the proxy — only the compile step does.
do_compile[network] = "1"

SYSTEMD_PACKAGES = "${PN}"
SYSTEMD_SERVICE:${PN} = "mediamtx.service"
# Disabled by default — the whole point of this recipe. Unit is still
# registered so `systemctl start/stop/status mediamtx` works ad-hoc;
# `systemctl enable mediamtx` on a running system persists it for
# operators who want that.
SYSTEMD_AUTO_ENABLE = "disable"

go_do_compile:prepend() {
    # Upstream feeds two //go:embed inputs via `go generate` in their
    # CI pipeline; the Yocto Go fetch doesn't trigger that step, so
    # `go install` fails with "pattern <...>: no matching files found".
    # Produce both files inline before go install runs:
    #   * internal/core/VERSION — upstream's versiongetter walks
    #     ../../.git via go-git and writes `git describe --tags`.
    #     Write the PV-derived string directly: avoids depending on
    #     the fetcher preserving a usable .git under ${S}/src/${GO_IMPORT}.
    #   * internal/servers/hls/hls.min.js — upstream's hlsjsdownloader
    #     pulls a pinned hls.js release zip from github.com/video-dev
    #     and extracts dist/hls.min.js. The SRC_URI entry above does
    #     the equivalent via bitbake's native fetcher (same sha256 the
    #     downloader would have verified), so we just copy the file
    #     into place. Running the downloader via `go run` would fail
    #     here because the Yocto cross-compile env would build it for
    #     the target and then fail to exec it.
    cp ${UNPACKDIR}/hlsjs/dist/hls.min.js \
        ${S}/src/${GO_IMPORT}/internal/servers/hls/hls.min.js
    echo "v${PV}" > ${S}/src/${GO_IMPORT}/internal/core/VERSION
}

do_install:append() {
    # Default config ships at /etc/mediamtx.yml — upstream includes it
    # at the repo root. The read-only rootfs makes this file immutable;
    # operators who want a custom config pass its path as the first
    # positional argument to the binary.
    install -d ${D}${sysconfdir}
    install -m 0644 ${S}/src/${GO_IMPORT}/mediamtx.yml ${D}${sysconfdir}/mediamtx.yml

    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${UNPACKDIR}/mediamtx.service \
        ${D}${systemd_system_unitdir}/mediamtx.service
}

FILES:${PN} += " \
    ${sysconfdir}/mediamtx.yml \
    ${systemd_system_unitdir}/mediamtx.service \
"

CONFFILES:${PN} = "${sysconfdir}/mediamtx.yml"
