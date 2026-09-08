# Point meta-rauc's rauc-conf recipe at the MissionDMX system.conf and the
# hybrid trust bundle produced by sign-images.sh. The bundle file is
# gitignored — running sign-images.sh in the top-level project stages a
# fresh copy here as `mdmx-keyring.pem`, so the recipe finds it via
# FILESEXTRAPATHS below.
FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

RAUC_KEYRING_FILE = "mdmx-keyring.pem"

# Snapshot the bbappend directory at parse time via `:=`. Anonymous
# python below runs after all bbappends have been parsed and merged;
# by then `${THISDIR}` has been rebound to the *base* recipe's dir
# (meta-rauc/recipes-core/rauc), which would make the existence check
# point at the wrong location. `:=` resolves THISDIR right here, while
# it still refers to this bbappend's own directory.
MDMX_KEYRING_STAGED := "${THISDIR}/files/mdmx-keyring.pem"

python __anonymous() {
    import os
    keyring = d.getVar('MDMX_KEYRING_STAGED')
    if not os.path.exists(keyring):
        bb.fatal(
            "RAUC keyring not staged at %s.\n"
            "Run './sign-images.sh' in the project root first — it emits\n"
            "the hybrid RSA + ML-DSA trust bundle used to authenticate\n"
            "downloaded update bundles." % keyring
        )
}
