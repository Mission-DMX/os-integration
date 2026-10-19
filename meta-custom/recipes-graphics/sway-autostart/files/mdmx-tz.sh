# Sources TZ from the saved console-settings.ini so that libc's
# localtime() (and waybar's clock module, which goes through it) report
# wall-clock time instead of UTC.
#
# The rootfs is read-only, so `timedatectl set-timezone` can't update
# /etc/localtime (writes return EROFS and systemd-timedated fails). The
# TZ environment variable short-circuits /etc/localtime entirely in glibc
# and in Howard Hinnant's date library (which waybar's clock module uses
# via date::current_zone), so exporting it here is enough.
#
# Sourced from two places:
#   * sway.service ExecStart — so sway and every child (waybar, foot,
#     etc.) inherit TZ from the moment the compositor starts;
#   * /etc/profile.d/ as a login-shell drop-in — so interactive shells
#     reached outside sway (SSH, direct serial console) also get TZ.
#
# $HOME is set by sway.service (and by login), so the lookup works in
# both contexts without hardcoding /home/user.

if [ -r "$HOME/.config/console-settings.ini" ]; then
    # IANA zone names are a single whitespace-free token
    # ("Europe/Berlin", "America/Indiana/Indianapolis", …), so we extract
    # exactly one non-whitespace run after the = and drop anything
    # trailing. head -n1 shields against a (malformed) INI with multiple
    # `timezone =` lines.
    _mdmx_tz=$(sed -n 's/^[[:space:]]*timezone[[:space:]]*=[[:space:]]*\([^[:space:]]\{1,\}\).*$/\1/p' \
        "$HOME/.config/console-settings.ini" | head -n1)
    if [ -n "$_mdmx_tz" ]; then
        export TZ="$_mdmx_tz"
    fi
    unset _mdmx_tz
fi
