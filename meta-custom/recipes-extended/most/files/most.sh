# MissionDMX: make `most` the default pager for interactive shells
# (bash reads this via /etc/profile.d/*.sh on login). MANPAGER overrides
# PAGER specifically for man(1) — otherwise man checks MANPAGER first,
# then PAGER, so setting both keeps behavior consistent even if a user
# later unsets one.
export PAGER=most
export MANPAGER=most
