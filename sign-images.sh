#!/usr/bin/env bash
# Sign the generated (compressed) factory and update images with a
# PQC-hybrid CMS signature that a future RAUC updater can verify.
#
# Output format: one DER-encoded, detached CMS SignedData per image
# containing two SignerInfos — a classical RSA-4096/SHA-384 signature
# and a post-quantum ML-DSA-65 (FIPS 204) signature. This is RAUC's
# native ".sig" format; multi-signer CMS is standard and lets the
# updater enforce "both must verify" (hybrid AND) once both certs are
# in its keyring. Verification degrades gracefully — a keyring with
# only one of the two certs still authenticates that signer.
#
# Requires OpenSSL >= 3.5 (native ML-DSA/SLH-DSA in the default
# provider — no oqs-provider install needed).
#
# Usage:
#   ./sign-images.sh                          # sign auto-detected artifacts
#   ./sign-images.sh --verify                 # re-verify existing signatures
#   ./sign-images.sh --stage-keyring          # generate keys + stage keyring only
#   ./sign-images.sh --factory PATH.wic.xz    # override factory image
#   ./sign-images.sh --update  PATH.ext4[.xz] # override update image
#   ./sign-images.sh --bundle  PATH.raucb     # override RAUC bundle
#   ./sign-images.sh --keys-dir DIR           # override keys/ location
#   ./sign-images.sh --regen-keys             # rotate dev keys
#
# The RAUC bundle (mdmx-rauc-bundle → *.raucb) is auto-detected in the
# deploy dir when present; its detached hybrid CMS sidecar (.raucb.sig)
# is what mdmx-updater on the target verifies before invoking `rauc
# install`, on top of RAUC's own embedded RSA signature.
#
# Dev keys are auto-generated on first run into keys/signing/ (which is
# gitignored). For production, replace them with keys/certs issued by
# your real CA before running.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR_DEFAULT="${REPO_ROOT}/build/tmp/deploy/images/qemux86-64"
KEYS_DIR="${REPO_ROOT}/keys/signing"
KEYRING_STAGING="${REPO_ROOT}/build/tmp/deploy/images/qemux86-64/keyring"

FACTORY_IMAGE=""
UPDATE_IMAGE=""
BUNDLE_IMAGE=""
MODE="sign"
REGEN_KEYS=0

# Print the top-of-file comment block until the first blank line after
# the last `# ...` line, so extending the help block doesn't require
# also bumping a hard-coded line range here.
usage() { awk '/^#/{print; next} {exit}' "$0"; exit "${1:-0}"; }

log()  { printf '\033[1;34m[sign-images]\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33m[sign-images]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[sign-images]\033[0m %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --verify)         MODE="verify";        shift ;;
        --stage-keyring)  MODE="stage-keyring"; shift ;;
        --factory)        FACTORY_IMAGE="$2";   shift 2 ;;
        --update)         UPDATE_IMAGE="$2";    shift 2 ;;
        --bundle)         BUNDLE_IMAGE="$2";    shift 2 ;;
        --keys-dir)       KEYS_DIR="$2";        shift 2 ;;
        --regen-keys)     REGEN_KEYS=1;         shift ;;
        -h|--help)        usage 0 ;;
        *)                warn "unknown argument: $1"; usage 1 ;;
    esac
done

command -v openssl >/dev/null || die "openssl not found in PATH"
command -v xz      >/dev/null || die "xz not found in PATH"

OSSL_VER=$(openssl version | awk '{print $2}')
case "$OSSL_VER" in
    3.5.*|3.[6-9].*|[4-9].*) : ;;
    *) die "openssl $OSSL_VER is too old; need >= 3.5 for native ML-DSA" ;;
esac
openssl list -signature-algorithms 2>/dev/null | grep -q ML-DSA-65 \
    || die "openssl $OSSL_VER does not expose ML-DSA-65 in the default provider"


# ---------------------------------------------------------------------------
# Locate the images.
# The factory image is the compressed WIC (flashable end-to-end).
# The update image is the rootfs ext4 that RAUC will drop into an inactive
# slot. If only the raw .ext4 exists, compress it to .ext4.xz so shipping
# and signing both operate on the same artifact.
# ---------------------------------------------------------------------------

autodetect_factory() {
    local candidate
    for candidate in "$DEPLOY_DIR_DEFAULT"/*.rootfs.wic.xz; do
        [ -e "$candidate" ] || continue
        # Skip timestamped duplicates — prefer the stable symlink target.
        case "$candidate" in
            *-2[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]*.wic.xz) continue ;;
        esac
        printf '%s' "$candidate"
        return 0
    done
    return 1
}

autodetect_update() {
    local candidate
    for candidate in "$DEPLOY_DIR_DEFAULT"/*.rootfs.ext4; do
        [ -e "$candidate" ] || continue
        case "$candidate" in
            *-2[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]*.ext4) continue ;;
        esac
        printf '%s' "$candidate"
        return 0
    done
    return 1
}

# The RAUC bundle recipe writes into DEPLOY_DIR_IMAGE with the same
# BUNDLE_NAME layout as any other meta-rauc bundle: a versioned
# .raucb file plus a stable BUNDLE_LINK_NAME symlink pointing at the
# newest build. Prefer the symlink so re-signing is idempotent across
# rebuilds; missing symlink is fine (fresh clone before first bundle).
autodetect_bundle() {
    local candidate
    for candidate in "$DEPLOY_DIR_DEFAULT"/mdmx-rauc-bundle-*.raucb; do
        [ -e "$candidate" ] || continue
        [ -L "$candidate" ] || continue
        printf '%s' "$(readlink -f "$candidate")"
        return 0
    done
    for candidate in "$DEPLOY_DIR_DEFAULT"/mdmx-rauc-bundle-*.raucb; do
        [ -e "$candidate" ] || continue
        printf '%s' "$candidate"
        return 0
    done
    return 1
}

ensure_compressed_update() {
    local src="$1"
    case "$src" in
        *.xz|*.gz|*.zst) printf '%s' "$src"; return 0 ;;
    esac
    local out="${src}.xz"
    # xz --keep copies the source's mtime onto the output, so a strict
    # "-nt" newer-than test would re-trigger compression on every run.
    # Only recompress when the source is strictly newer.
    if [ -e "$out" ] && [ ! "$src" -nt "$out" ]; then
        log "update image already compressed: $(basename "$out")"
    else
        log "compressing update image: $(basename "$src") -> $(basename "$out")"
        xz -f -9 --keep --threads=0 "$src"
    fi
    printf '%s' "$out"
}

# Image discovery only makes sense when we're actually going to sign or
# verify. --stage-keyring is the Makefile's bootstrap path (fresh
# checkout, no images yet); requiring artifacts there would deadlock.
if [ "$MODE" != "stage-keyring" ]; then
    if [ -z "$FACTORY_IMAGE" ]; then
        FACTORY_IMAGE=$(autodetect_factory) \
            || die "no factory image (*.rootfs.wic.xz) under $DEPLOY_DIR_DEFAULT — run 'make build' first"
    fi
    if [ -z "$UPDATE_IMAGE" ]; then
        raw=$(autodetect_update) \
            || die "no update image (*.rootfs.ext4) under $DEPLOY_DIR_DEFAULT — run 'make build' first"
        UPDATE_IMAGE=$(ensure_compressed_update "$raw")
    else
        UPDATE_IMAGE=$(ensure_compressed_update "$UPDATE_IMAGE")
    fi

    # Bundle is optional — sign-images.sh predates mdmx-rauc-bundle and must
    # still work on trees where the bundle recipe hasn't been built yet.
    if [ -z "$BUNDLE_IMAGE" ]; then
        if BUNDLE_IMAGE=$(autodetect_bundle); then
            :
        else
            BUNDLE_IMAGE=""
        fi
    fi

    [ -e "$FACTORY_IMAGE" ] || die "factory image not found: $FACTORY_IMAGE"
    [ -e "$UPDATE_IMAGE" ]  || die "update image not found: $UPDATE_IMAGE"
    if [ -n "$BUNDLE_IMAGE" ] && [ ! -e "$BUNDLE_IMAGE" ]; then
        die "bundle image not found: $BUNDLE_IMAGE"
    fi
fi


# ---------------------------------------------------------------------------
# Key material. Dev-only: self-signed, 10-year validity. Replace with certs
# from a real CA for production. Layout mirrors what RAUC expects — a
# private key + X.509 signer cert per algorithm, plus a combined trust
# anchor bundle that installs onto the device as the RAUC keyring.
# ---------------------------------------------------------------------------

RSA_KEY="$KEYS_DIR/rsa.key"
RSA_CRT="$KEYS_DIR/rsa.cert.pem"
MLDSA_KEY="$KEYS_DIR/mldsa65.key"
MLDSA_CRT="$KEYS_DIR/mldsa65.cert.pem"
TRUST_BUNDLE="$KEYS_DIR/trust-bundle.pem"

gen_keys() {
    log "generating dev signing keys in $KEYS_DIR"
    install -d -m 0700 "$KEYS_DIR"
    umask 077

    openssl req -x509 -newkey rsa:4096 -sha384 -days 3650 -nodes \
        -keyout "$RSA_KEY" -out "$RSA_CRT" \
        -subj "/O=MissionDMX/CN=MissionDMX RAUC RSA-4096 (dev)" \
        -addext "keyUsage=critical,digitalSignature" \
        -addext "extendedKeyUsage=codeSigning" \
        2>/dev/null
    log "  wrote $RSA_CRT"

    openssl genpkey -algorithm ML-DSA-65 -out "$MLDSA_KEY" 2>/dev/null
    openssl req -x509 -new -key "$MLDSA_KEY" -days 3650 -nodes \
        -out "$MLDSA_CRT" \
        -subj "/O=MissionDMX/CN=MissionDMX RAUC ML-DSA-65 (dev)" \
        -addext "keyUsage=critical,digitalSignature" \
        -addext "extendedKeyUsage=codeSigning" \
        2>/dev/null
    log "  wrote $MLDSA_CRT"

    cat "$RSA_CRT" "$MLDSA_CRT" > "$TRUST_BUNDLE"
    log "  wrote $TRUST_BUNDLE"
}

if [ "$REGEN_KEYS" = 1 ]; then
    rm -f "$RSA_KEY" "$RSA_CRT" "$MLDSA_KEY" "$MLDSA_CRT" "$TRUST_BUNDLE"
fi

if [ ! -s "$RSA_KEY" ] || [ ! -s "$RSA_CRT" ] \
   || [ ! -s "$MLDSA_KEY" ] || [ ! -s "$MLDSA_CRT" ]; then
    if [ "$MODE" = "verify" ]; then
        die "missing signing keys in $KEYS_DIR and mode is --verify"
    fi
    gen_keys
elif [ ! -s "$TRUST_BUNDLE" ]; then
    cat "$RSA_CRT" "$MLDSA_CRT" > "$TRUST_BUNDLE"
fi


# ---------------------------------------------------------------------------
# Sign / verify. Signature format is DER-encoded, detached, multi-signer
# CMS SignedData — exactly the shape RAUC produces with `rauc bundle` and
# consumes with `rauc install`. Two SignerInfos share one CMS envelope so
# the pair travels together and can't be split apart in transit.
# ---------------------------------------------------------------------------

sign_image() {
    local img="$1"
    local sig="${img}.sig"
    local sum="${img}.sha384"

    log "signing $(basename "$img")"
    openssl cms -sign -binary \
        -in "$img" -out "$sig" -outform DER \
        -signer "$RSA_CRT"   -inkey "$RSA_KEY"   -md sha384 \
        -signer "$MLDSA_CRT" -inkey "$MLDSA_KEY" \
        -nosmimecap
    log "  wrote $(basename "$sig") ($(stat -c %s "$sig") bytes)"

    ( cd "$(dirname "$img")" && sha384sum "$(basename "$img")" > "$sum" )
    log "  wrote $(basename "$sum")"
}

verify_image() {
    local img="$1"
    local sig="${img}.sig"
    [ -e "$sig" ] || die "signature missing for $(basename "$img"): $sig"

    # Show which signature algorithms are actually present in the CMS —
    # cheap sanity check that we didn't accidentally ship a single-signer
    # signature.
    local algs
    algs=$(openssl cms -inform DER -in "$sig" -cmsout -print 2>/dev/null \
        | awk '/signerInfos:/{s=1} s && /signatureAlgorithm/{getline; print}' \
        | sed -E 's/^ *algorithm: //; s/ \(.*\)$//' \
        | paste -sd ', ' -)
    log "  algorithms: ${algs:-<none>}"

    # CMS -verify requires every SignerInfo to validate. Trust bundle
    # contains both certs, so a green result here means both the RSA and
    # the ML-DSA signature checked out against the payload.
    log "verifying $(basename "$img") (hybrid: RSA-4096 + ML-DSA-65)"
    if openssl cms -verify -binary -inform DER -in "$sig" \
        -content "$img" \
        -CAfile "$TRUST_BUNDLE" -partial_chain \
        -purpose any -out /dev/null 2>/tmp/sign-images.verify.$$; then
        log "  OK — both signers verified"
        rm -f /tmp/sign-images.verify.$$
    else
        cat /tmp/sign-images.verify.$$ >&2 || true
        rm -f /tmp/sign-images.verify.$$
        die "verification FAILED for $(basename "$img")"
    fi
}

stage_keyring() {
    install -d -m 0755 "$KEYRING_STAGING"
    install -m 0644 "$TRUST_BUNDLE" "$KEYRING_STAGING/rauc-keyring.pem"
    install -m 0644 "$RSA_CRT"      "$KEYRING_STAGING/rsa.cert.pem"
    install -m 0644 "$MLDSA_CRT"    "$KEYRING_STAGING/mldsa65.cert.pem"
    log "staged keyring at $KEYRING_STAGING/rauc-keyring.pem"

    # rauc-conf.bbappend loads the same bundle as the target keyring
    # (/etc/rauc/mdmx-keyring.pem) via FILESEXTRAPATHS. Keep the two in
    # lockstep — a stale copy inside meta-custom would leave the target
    # rejecting bundles the current keys signed.
    local recipe_files="${REPO_ROOT}/meta-custom/recipes-core/rauc/files"
    if [ -d "$recipe_files" ]; then
        install -m 0644 "$TRUST_BUNDLE" "$recipe_files/mdmx-keyring.pem"
        log "staged keyring for Yocto: $recipe_files/mdmx-keyring.pem"
    fi
}


if [ "$MODE" != "stage-keyring" ]; then
    log "factory image: $FACTORY_IMAGE"
    log "update image:  $UPDATE_IMAGE"
    if [ -n "$BUNDLE_IMAGE" ]; then
        log "rauc bundle:   $BUNDLE_IMAGE"
    else
        log "rauc bundle:   <none> (mdmx-rauc-bundle not built yet)"
    fi
fi
log "keys dir:      $KEYS_DIR"

case "$MODE" in
    sign)
        sign_image "$FACTORY_IMAGE"
        sign_image "$UPDATE_IMAGE"
        if [ -n "$BUNDLE_IMAGE" ]; then
            sign_image "$BUNDLE_IMAGE"
        fi
        stage_keyring
        log "signing complete — re-run with --verify to double-check"
        ;;
    verify)
        verify_image "$FACTORY_IMAGE"
        verify_image "$UPDATE_IMAGE"
        if [ -n "$BUNDLE_IMAGE" ]; then
            verify_image "$BUNDLE_IMAGE"
        fi
        log "verification complete"
        ;;
    stage-keyring)
        # Keys were generated (or reused) by the block above; publish
        # the trust bundle to both the RAUC deploy staging path and the
        # meta-custom recipe files/ directory, then stop. This is the
        # bootstrap path invoked by `make build` on a fresh checkout.
        stage_keyring
        log "keyring staged — no signatures produced"
        ;;
esac
