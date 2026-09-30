FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

# mount.sh is already in the base recipe's SRC_URI; FILESEXTRAPATHS above
# makes bitbake resolve it from our files/ dir first, so we ship our own
# copy that mounts vfat/exfat/ntfs/hfs with uid=gid=1000 for the UI user.

MOUNT_BASE = "/run/media"
MOUNT_GROUP = "user"
