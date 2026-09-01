#! /bin/sh
# Write the MOTD into /var so it survives firmware updates (root partitions
# are treated as read-only from an update-safety perspective). /etc/motd is
# a symlink → /var/motd installed by the recipe.
echo "MissionDMX - Welcome" > /var/motd
