# mediamtx

Packages [MediaMTX](https://github.com/bluenviron/mediamtx) — the Go-based
RTSP / RTMP / HLS / WebRTC / SRT streaming server and proxy by bluenviron
— into the image, but **disabled at boot**. The binary and a hardened
systemd unit ship on every rootfs; the operator starts and stops the
server on demand.

## Why it's in the image

No other media server is present. Operator workflows that need to expose
a camera feed or restream an inbound stream temporarily (debugging a
fixture control signal, pulling a diagnostic capture off a touchscreen
rig, …) previously had nothing on the image to do it. Shipping MediaMTX
and leaving it stopped keeps the attack surface at zero on normal boots
— no listening sockets, no process — while putting the full set of
RTSP/RTMP/HLS/WebRTC/SRT listeners one `systemctl start` away.

## What the recipe ships

| Target path                               | Source              | Purpose                                                                |
| ----------------------------------------- | ------------------- | ---------------------------------------------------------------------- |
| `/usr/bin/mediamtx`                       | upstream Go build   | The server binary; takes an optional config-file path as `$1`.         |
| `/etc/mediamtx.yml`                       | upstream repo root  | Default configuration (all listeners enabled, no auth, log to stderr). |
| `/lib/systemd/system/mediamtx.service`    | `files/`            | Hardened systemd unit (`DynamicUser=yes`, strict sandbox).             |

## Build quirks

- **Source build via `go-mod` with network at compile-time.** The recipe
  inherits `go-mod` (poky's `classes-recipe/go-mod.bbclass`) and sets
  `do_compile[network] = "1"` + `GOPROXY = "https://proxy.golang.org,direct"`.
  Module resolution hits proxy.golang.org *during* `do_compile`, not
  `do_fetch`, which is Yocto's sanctioned pattern for Go modules (see
  `meta-openembedded/meta-oe/recipes-dbs/influxdb/influxdb_1.8.10.bb` for
  the canonical example). The build host therefore needs outbound HTTPS
  — if `do_compile` is quarantined off-network, switch to a vendor
  tarball approach (not implemented here).
- **Version pinned to v1.14.0 because of the Go toolchain gate.**
  `poky/meta/recipes-devtools/go/go_1.24.6.bb` provides Go 1.24.6 to the
  build. MediaMTX ≥ v1.15.0 declares `go 1.25.0` in `go.mod` (v1.19.0 →
  `go 1.26`, v1.21.3 → `go 1.27`), and Go's toolchain directive will
  refuse the build with a 1.24 host. v1.14.0 declares `go 1.24.0` and
  is the latest compatible release. To bump past 1.14, upgrade the
  in-tree Go recipe first.
- **No `COMPATIBLE_HOST` restriction.** `goarch.bbclass` cross-compiles
  for whatever machine the image targets. No hard-coded amd64 asset
  means re-targeting the image (e.g. to arm64) does not break this
  recipe.
- **No `RDEPENDS` list.** Go statically links its own dependencies; the
  resulting ELF's `NEEDED` entries (libc, libpthread) are picked up by
  Yocto's shared-library tracking automatically.
- **`//go:embed` inputs are generated at compile-time.** Upstream's CI
  runs `go generate` before `go build`, which populates two files the
  Go compiler needs for `//go:embed` directives but are not committed
  to the repo: `internal/core/VERSION` (version string) and
  `internal/servers/hls/hls.min.js` (the hls.js player bundle).
  `go_do_compile:prepend` writes `VERSION` directly from `PV` and
  copies `hls.min.js` from a release zip fetched by a separate
  `SRC_URI` entry pointing at `github.com/video-dev/hls.js`
  (version and sha256 pinned to match upstream's
  `internal/servers/hls/hlsjsdownloader/{VERSION,HASH}`). The
  alternative — running upstream's `hlsjsdownloader` via `go run` —
  doesn't work in Yocto: the cross-compile env makes `go run` build a
  target-architecture binary and then fail to `fork/exec` it on the
  host.
- **`CONFFILES`** marks `/etc/mediamtx.yml` as a configuration file so
  package-manager upgrades will not clobber operator edits (academic on
  a read-only rootfs, but future-proofs the recipe if `/etc` ever
  becomes writable).

## Default state & running it

- **Boot default:** service registered, not started —
  `systemctl status mediamtx` prints
  `Loaded: loaded (/lib/systemd/system/mediamtx.service; disabled; ...)`
  and `Active: inactive (dead)`.
- **Start now:** `systemctl start mediamtx`. Logs: `journalctl -u mediamtx -b`.
- **Persist across reboots:** `systemctl enable mediamtx` (power-user
  path; the recipe sets `SYSTEMD_AUTO_ENABLE = "disable"` so the image
  ships with the unit *not* symlinked into `multi-user.target.wants/`).
- **Ad-hoc with a custom config:** `mediamtx /path/to/custom.yml` from a
  shell. The read-only rootfs makes editing `/etc/mediamtx.yml` in place
  impossible, but a copy under `/home/user/` works.
- **Verifying ports:** before start, `ss -tlnp | grep -E '8554|1935|8888|8889|9997'`
  returns nothing. After start, port 8554 (RTSP) and the others listed in
  the config appear.
- **Control API:** `curl -s http://127.0.0.1:9997/v3/config/global/get`
  returns JSON once the service is running.

## Updating

1. Pick the new upstream tag (`v${PV}`) and check that its `go.mod`
   `go` directive is still satisfied by `poky/meta/recipes-devtools/go/go_*.bb`.
   If not, bump the Go recipe (or stay on the current `PV`).
2. Rename the recipe file (`mediamtx_${OLD}.bb` → `mediamtx_${NEW}.bb`)
   and set `SRCREV` to the commit the new tag points at
   (`git ls-remote --tags https://github.com/bluenviron/mediamtx v${NEW}`).
3. Re-run `md5sum` over the new tag's `LICENSE` and update
   `LIC_FILES_CHKSUM`.
4. Check `internal/servers/hls/hlsjsdownloader/VERSION` and `.../HASH`
   at the new tag. If either changed, update `HLSJS_VERSION` and
   `SRC_URI[hlsjs.sha256sum]` to match (otherwise the fetch will
   mismatch the version that the `//go:embed` site expects or the
   sha256 check will fail).
5. Diff the shipped `mediamtx.yml` against the previous version — the
   MediaMTX config schema has renamed top-level keys mid-1.x before
   (`rtspAddress` → `rtsp.address`, etc.); if the service unit's
   `ExecStart` arguments or the listener-port verification steps above
   assume a specific key, follow the rename.
