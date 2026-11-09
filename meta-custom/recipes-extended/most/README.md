# most

Terminal pager by John E. Davis (https://www.jedsoft.org/most/), packaged
for MissionDMX and wired in as the system-wide default pager.

## Why it's in the image

`less` is not installed (not pulled by any existing recipe or image
feature we enable), so without a dedicated pager both `man` and anything
that invokes `$PAGER` would fall back to `more` from util-linux —
which can't scroll backwards and mangles colored output from tools like
`systemctl status`. `most` is a small S-Lang pager that handles both
cleanly and additionally supports multiple windows and binary mode.

## What the recipe ships

- `/usr/bin/most` — the pager binary itself.
- `/etc/most.conf` — empty placeholder; `most` compiles this path in as
  `MOST_SYSTEM_INITFILE` and reads keybinding/color overrides from it
  on startup, so shipping the file lets operators drop in site-wide
  tweaks without needing to recreate the path.
- `/etc/profile.d/most.sh` — exports `PAGER=most` and `MANPAGER=most`
  for every bash login shell (console gettys + foot terminals under
  sway both source `/etc/profile`). Owned by this package so removing
  the package also removes the env exports — otherwise a stale
  `PAGER=most` would make every new login shell error out.
- `/usr/share/man/man1/most.1` and docs under `/usr/share/doc/most/`.

## Build quirks

- Upstream's `configure` is autoconf-generated but `JD_INIT` hard-fails
  if `$srcdir` differs from `pwd`. We inherit `autotools-brokensep` so
  the build directory equals the source directory and that check passes.
- `src/Makefile.in`'s install rule invokes `$(INSTALL) -s`, which calls
  whatever `strip` is on PATH — host strip during a cross build, which
  would silently corrupt the target binary. `do_configure:prepend`
  sed-removes the `-s` flag before configure runs, so yocto's own
  `package_do_split_debug` handles stripping into a `-dbg` subpackage.
- `--with-slanginc` / `--with-slanglib` are pointed at the cross
  sysroot to stop configure from probing the host's `/usr/include` for
  `slang.h`.
- `--without-x` drops the optional X11 selection-paste integration;
  this image is Wayland-only (sway) so an X dep would be pure dead
  weight even if it built.

## Dependencies

- Build: `slang` only (already provided by
  `poky/meta/recipes-extended/slang/slang_2.3.3.bb`). `most`'s configure
  auto-detects that terminfo dirs exist on the build host and drops
  `-ltermcap`, so most does not link ncurses directly.
- Runtime: libslang.so's own NEEDED entry pulls in libtinfo/libncurses
  via shared-library dep tracking; no explicit `RDEPENDS` needed.

## Changing the default pager

If a future image needs a different pager, remove `most` from
`IMAGE_INSTALL` in `config/local.conf` *and* make sure no other recipe
ships `/etc/profile.d/most.sh` — the env exports are the pager
selection, the binary install only makes the command available.
