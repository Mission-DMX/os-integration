export XDG_RUNTIME_DIR=/run/sway
export WAYLAND_DISPLAY=wayland-1
export SWAYSOCK=$(find /run/sway -name "sway-ipc*" 2>/dev/null | head -1)
