# flatpak_1.16.0.bb RDEPENDS on flatpak-xdg-utils, which ships
# /usr/bin/xdg-open and /usr/bin/xdg-email — the same paths provided by
# the regular xdg-utils already pulled into the image. Having both
# packages installed fails do_rootfs with a file-collision transaction
# error.
#
# flatpak-xdg-utils is intended to live INSIDE a Flatpak sandbox: its
# xdg-open detects /.flatpak-info and forwards URL opens to the host via
# xdg-desktop-portal. On the host rootfs (where no sandbox marker
# exists), its forwarder behavior isn't useful — native apps want the
# real xdg-utils to spawn a browser/opener directly. Sandboxed apps get
# their own copy of flatpak-xdg-utils baked into their runtime image, so
# dropping it from the host RDEPENDS does not affect flatpak app
# execution.
RDEPENDS:${PN}:remove = "flatpak-xdg-utils"
