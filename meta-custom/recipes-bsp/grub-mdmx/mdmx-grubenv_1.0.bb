SUMMARY = "Factory GRUB environment block for A/B slot boot"
DESCRIPTION = "Produces a valid grubenv (1024-byte GRUB environment block) \
seeded with ORDER='A B', A_OK/B_OK=1, A_TRY/B_TRY=0. Deployed to \
DEPLOY_DIR_IMAGE so IMAGE_EFI_BOOT_FILES copies it onto the ESP alongside \
grub.cfg. RAUC's rauc-mark-good and rauc install will drive the same \
variables in-place from userland once RAUC is added."

LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

DEPENDS = "grub-native"

inherit deploy nopackages

do_compile() {
    # `grub-editenv create` writes an empty (all-`#`) 1024-byte block;
    # subsequent `set` calls patch key=value lines in place.
    grub-editenv ${B}/grubenv create
    grub-editenv ${B}/grubenv set ORDER="A B"
    grub-editenv ${B}/grubenv set A_OK=1
    grub-editenv ${B}/grubenv set B_OK=1
    grub-editenv ${B}/grubenv set A_TRY=0
    grub-editenv ${B}/grubenv set B_TRY=0
}

do_deploy() {
    install -d ${DEPLOYDIR}
    install -m 0644 ${B}/grubenv ${DEPLOYDIR}/grubenv
}

addtask do_deploy after do_compile before do_build
