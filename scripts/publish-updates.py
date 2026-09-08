#!/usr/bin/env python3
"""Assemble build/updates/ for 1:1 upload to the OS update HTTP root.

Called by ``make publish``. Reads the RAUC bundle(s) written by the
``mdmx-rauc-bundle`` recipe out of the Yocto deploy dir, copies each
one — plus its ``.sig`` sidecar produced by ``sign-images.sh`` and the
hybrid trust bundle — into ``build/updates/``, and emits a
``manifest.json`` describing what's on offer.

Schema (mirrors what mdmx-updater.py on the target expects)::

    {
      "generated": "2026-09-08T12:34:56Z",
      "compatible": "MissionDMX",
      "bundles": [
        {
          "file":            "mdmx-rauc-bundle-qemux86-64-20260907202423.raucb",
          "sig":             "mdmx-rauc-bundle-qemux86-64-20260907202423.raucb.sig",
          "build_timestamp": "20260907202423",
          "sha384":          "…",
          "size":            123456789
        }
      ]
    }

Only bundles that have a matching ``.sig`` sidecar are listed — an
unsigned bundle is by definition not installable on the target because
mdmx-updater would refuse to verify it, so leaving it out of the
manifest keeps the "manifest entry ⇒ installable" invariant honest.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import sys
from pathlib import Path

CHUNK = 1024 * 1024
COMPATIBLE = "MissionDMX"


def sha384_of(path: Path) -> str:
    h = hashlib.sha384()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def find_build_timestamp(deploy_dir: Path) -> str:
    """Read the sidecar that mdmx-image-postprocess writes at rootfs assembly."""
    sidecar = deploy_dir / "mdmx-build-timestamp"
    if not sidecar.exists():
        raise SystemExit(
            f"publish: missing {sidecar}\n"
            "  Rebuild the image so ROOTFS_POSTPROCESS_COMMAND runs the\n"
            "  mdmx_write_build_timestamp step. (Was the class edit picked\n"
            "  up by the current bitbake process?)"
        )
    return sidecar.read_text().strip()


def collect_bundles(deploy_dir: Path) -> list[Path]:
    """Return the real .raucb files, dereferencing meta-rauc's link name."""
    bundles: dict[Path, Path] = {}
    for candidate in sorted(deploy_dir.glob("mdmx-rauc-bundle-*.raucb")):
        real = candidate.resolve()
        # Multiple names (link + timestamped) can point at one file;
        # only publish each unique payload once.
        bundles.setdefault(real, real)
    return sorted(bundles.values())


def stage_bundle(bundle: Path, dest_dir: Path) -> tuple[Path, Path]:
    sig = bundle.with_suffix(bundle.suffix + ".sig")
    if not sig.exists():
        raise SystemExit(
            f"publish: {bundle.name} has no {sig.name} sidecar — run\n"
            "  ./sign-images.sh first (it produces the hybrid RSA + ML-DSA CMS)."
        )
    out_bundle = dest_dir / bundle.name
    out_sig    = dest_dir / sig.name
    shutil.copy2(bundle, out_bundle)
    shutil.copy2(sig,    out_sig)
    return out_bundle, out_sig


def build_manifest(
    staged: list[tuple[Path, Path, str]],
    build_timestamp: str,
) -> dict:
    bundles = []
    for bundle_path, sig_path, sha in staged:
        bundles.append({
            "file":            bundle_path.name,
            "sig":             sig_path.name,
            "build_timestamp": build_timestamp,
            "sha384":          sha,
            "size":            bundle_path.stat().st_size,
        })
    return {
        "generated":  dt.datetime.now(dt.timezone.utc)
                       .replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "compatible": COMPATIBLE,
        "bundles":    bundles,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deploy-dir", required=True, type=Path,
                        help="Yocto DEPLOY_DIR_IMAGE (…/tmp/deploy/images/MACHINE)")
    parser.add_argument("--updates-dir", required=True, type=Path,
                        help="output directory (uploaded 1:1 to the HTTP root)")
    parser.add_argument("--trust-bundle", type=Path, default=None,
                        help="optional: hybrid trust bundle to publish alongside "
                             "(shipped for reference, not consumed by the client)")
    args = parser.parse_args()

    deploy_dir  = args.deploy_dir.resolve()
    updates_dir = args.updates_dir.resolve()

    if not deploy_dir.is_dir():
        raise SystemExit(f"publish: deploy dir not found: {deploy_dir}")

    build_timestamp = find_build_timestamp(deploy_dir)

    bundles = collect_bundles(deploy_dir)
    if not bundles:
        raise SystemExit(
            f"publish: no mdmx-rauc-bundle-*.raucb under {deploy_dir}\n"
            "  Did `bitbake mdmx-rauc-bundle` run to completion?"
        )

    # Wipe and re-populate so a rebuild doesn't leave a stale bundle
    # lingering in updates/ — the client would happily install a
    # rolled-back image otherwise.
    if updates_dir.exists():
        shutil.rmtree(updates_dir)
    updates_dir.mkdir(parents=True)

    staged: list[tuple[Path, Path, str]] = []
    for bundle in bundles:
        out_bundle, out_sig = stage_bundle(bundle, updates_dir)
        staged.append((out_bundle, out_sig, sha384_of(out_bundle)))
        print(f"publish: staged {out_bundle.name} ({out_bundle.stat().st_size} bytes)")

    manifest = build_manifest(staged, build_timestamp)
    manifest_path = updates_dir / "manifest.json"
    with manifest_path.open("w") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")
    print(f"publish: wrote {manifest_path}")

    if args.trust_bundle and args.trust_bundle.exists():
        shutil.copy2(args.trust_bundle, updates_dir / "trust-bundle.pem")
        print(f"publish: staged trust-bundle.pem for operator reference")

    print(f"publish: {len(staged)} bundle(s) ready in {updates_dir}")
    print(f"publish: rsync -a {updates_dir}/ user@server:/var/www/os-updates/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
