# wvkbd

Packages the [wvkbd](https://github.com/jjsullivan5196/wvkbd) on-screen
keyboard for the kiosk. wvkbd is a Wayland-native virtual keyboard that
renders through `zwlr_layer_shell_v1` and types into the focused client
via `zwp_virtual_keyboard_v1`. It is the OSK the kiosk shows when the
user taps a text field without a hardware keyboard plugged in.

## What this recipe ships

| Target path                 | Source           | Purpose                                      |
| --------------------------- | ---------------- | -------------------------------------------- |
| `/usr/bin/wvkbd-deskintl`   | upstream build   | The keyboard binary (desktop layout, intl).  |
| `/usr/share/man/man1/wvkbd.1` | upstream build | Manpage for `--auto`, signals, flags, etc.   |

The runtime lifecycle (spawn, respawn on hardware-keyboard changes,
show/hide socket, waybar wiring) is owned by the `osk-manager` recipe —
this one just builds and installs the binary.

## Why `wvkbd-deskintl` instead of upstream's default `wvkbd-mobintl`

Upstream wvkbd's `config.mk` sets `LAYOUT=mobintl`, which produces
`wvkbd-mobintl` — a phone-style stacked layout tuned for narrow screens.
The repo also ships a parallel `deskintl` set (`layout.deskintl.h`,
`keymap.deskintl.h`, `config.deskintl.h`), which lays out a full desktop
keyboard grid (QWERTY row, dedicated digits row, modifier row) that
reads naturally on the kiosk's landscape touchscreens. We override
`LAYOUT` via `EXTRA_OEMAKE` so `make` resolves `BIN=wvkbd-${LAYOUT}` to
`wvkbd-deskintl`; the install target then drops that single binary into
`${bindir}`.

### Quirk: `deskintl` is not the upstream default and has no CI

The `deskintl` layout files are present in the repo but the upstream
Makefile's `LAYOUT=mobintl` default and `.build.yml` CI script both target
`mobintl` exclusively. In practice this means:

* `deskintl` can occasionally lag `mobintl` on API breakage inside
  `keyboard.c` / `keymap.h` — if a wvkbd bump breaks `do_compile`, check
  whether the breakage reproduces with `LAYOUT=mobintl` before blaming
  the recipe.
* There is no upstream guarantee that `deskintl` will keep building on
  future releases. If it ever gets dropped, fall back to
  `WVKBD_LAYOUT = "mobintl"` here and set the kiosk's default layer via
  `-l` on osk-manager's wvkbd invocation.

## Runtime notes (also referenced by `osk-manager`)

* **`--auto` is required for text-focus-triggered pop-up.** With
  `--auto` wvkbd binds `zwp_input_method_v2` and show/hide follows the
  compositor's text-input focus events. Without it the keyboard only
  responds to signals.
* **Signals** (wvkbd 0.20): `SIGUSR1` hides, `SIGUSR2` shows,
  `SIGRTMIN` toggles. `osk-manager`'s socket commands lower to these.
* **`--hidden`** boots invisible — always combine it with `--auto` or
  with a signal/`oskctl show` to make the keyboard reachable.

## Verifying on a running image

```sh
# Does the binary install and link?
wvkbd-deskintl --list-layers       # should print the deskintl layer set

# Does --auto wire up zwp_input_method_v2?
wvkbd-deskintl --hidden --auto &   # starts hidden; tap a text field in
                                   # foot/mdmx-editor to make it appear
```

If `--list-layers` prints a mobile-looking set (`abc_lower`, `abc_upper`,
`numbers`, `symbols` with no dedicated row for digits), the recipe was
accidentally built with `LAYOUT=mobintl` — recheck `EXTRA_OEMAKE`.
