#!/usr/bin/env python3
"""Check for OS updates, download and verify them, mark as pending.

Runs unattended on a systemd timer as the ``user`` account. Reads the
update server URL from ``~/.config/console-settings.ini`` under
``[update] url = ...`` (same INI file console-lock uses for the PIN,
disjoint section so we can't clobber the lock config). Falls back to
``https://mission-dmx.org/downloads/os-updates/`` when the file or
section is missing.

Never installs on its own. Installation is the console menu's job, gated
on a user tap through pkexec (see 50-mdmx-updater.rules).

Manifest schema served at ``<url>/manifest.json``::

    {
      "generated": "2026-09-08T12:34:56Z",
      "bundles": [
        {
          "file":            "mdmx-rauc-bundle-qemux86-64-20260907202423.raucb",
          "sig":             "mdmx-rauc-bundle-qemux86-64-20260907202423.raucb.sig",
          "build_timestamp": "20260907202423",
          "sha384":          "…",
          "size":            123456789
        },
        …
      ]
    }

Freshness test: an entry is a candidate iff its ``build_timestamp``
sorts strictly greater than the local ``/etc/mdmx-build-timestamp``.
Both use the ``YYYYMMDDhhmmss`` layout from bitbake's DATETIME, which
already sorts identically to chronological order — no date parsing.
"""

from __future__ import annotations

import configparser
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

DEFAULT_URL = "https://mission-dmx.org/downloads/os-updates/"
CONFIG_PATH = Path.home() / ".config" / "console-settings.ini"
BUILD_TIMESTAMP_PATH = Path("/etc/mdmx-build-timestamp")
KEYRING_PATH = Path("/etc/rauc/mdmx-keyring.pem")
CACHE_DIR = Path.home() / ".cache" / "mdmx-updater"
BUNDLE_DIR = CACHE_DIR / "pending"
PENDING_MARKER = CACHE_DIR / "pending.json"
MANIFEST_NAME = "manifest.json"

# 60s for the small text manifest; 30 min ceiling on bundle transfers so
# a stuck TCP stream can't wedge the timer indefinitely on slow links.
MANIFEST_TIMEOUT = 60
BUNDLE_TIMEOUT = 1800
DOWNLOAD_CHUNK = 1024 * 1024


# systemd captures stdout/stderr into the journal with per-line prefixes
# already (unit name, PID, priority), so keep the format minimal — just
# the level and the message. logging.basicConfig() in main() attaches a
# StreamHandler to the root logger with this format; the module-level
# getLogger() call below returns the singleton "mdmx-updater" child.
logger = logging.getLogger("mdmx-updater")


def load_server_url() -> str:
    cfg = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        try:
            cfg.read(CONFIG_PATH)
        except configparser.Error as exc:
            logger.warning("config parse failed (%s); using default URL", exc)
            return DEFAULT_URL
    url = cfg.get("update", "url", fallback=DEFAULT_URL).strip()
    # Trailing slash normalisation — the code below joins with "/" and
    # a doubled separator would produce a 404 on strict servers.
    return url.rstrip("/") + "/"


def load_local_timestamp() -> str:
    try:
        return BUILD_TIMESTAMP_PATH.read_text().strip()
    except OSError:
        return ""


def http_get(url: str, timeout: int) -> bytes:
    req = urllib.request.Request(
        url, headers={"User-Agent": "mdmx-updater/1"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def http_download(url: str, dest: Path, timeout: int) -> None:
    req = urllib.request.Request(
        url, headers={"User-Agent": "mdmx-updater/1"}
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req, timeout=timeout) as r, tmp.open("wb") as fh:
        while True:
            chunk = r.read(DOWNLOAD_CHUNK)
            if not chunk:
                break
            fh.write(chunk)
    tmp.replace(dest)


def sha384_of(path: Path) -> str:
    h = hashlib.sha384()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(DOWNLOAD_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_hybrid(bundle: Path, sig: Path) -> bool:
    """Detached CMS verify using the on-device RAUC keyring.

    The keyring bundles both the RSA and the ML-DSA certificates that
    ``sign-images.sh`` produced, so ``openssl cms -verify`` here checks
    both SignerInfos before returning success — same posture as
    sign-images.sh --verify on the build host.
    """
    result = subprocess.run(
        [
            "openssl", "cms", "-verify", "-binary", "-inform", "DER",
            "-in", str(sig), "-content", str(bundle),
            "-CAfile", str(KEYRING_PATH), "-partial_chain",
            "-purpose", "any", "-out", os.devnull,
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        logger.error("CMS verify failed: %s", result.stderr.strip())
        return False
    return True


def pick_candidate(manifest: dict, local_ts: str) -> Optional[dict]:
    """Newest bundle with a build_timestamp strictly greater than local."""
    bundles = manifest.get("bundles") or []
    fresh = [
        b for b in bundles
        if isinstance(b, dict)
        and str(b.get("build_timestamp", "")) > local_ts
        and b.get("file") and b.get("sig")
    ]
    if not fresh:
        return None
    return max(fresh, key=lambda b: str(b["build_timestamp"]))


def already_pending(candidate: dict) -> bool:
    if not PENDING_MARKER.exists():
        return False
    try:
        current = json.loads(PENDING_MARKER.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return (
        current.get("build_timestamp") == candidate.get("build_timestamp")
        and current.get("sha384") == candidate.get("sha384")
        and Path(current.get("bundle_path", "")).exists()
    )


def clear_pending() -> None:
    if PENDING_MARKER.exists():
        try:
            PENDING_MARKER.unlink()
        except OSError:
            pass
    if BUNDLE_DIR.exists():
        shutil.rmtree(BUNDLE_DIR, ignore_errors=True)


def write_pending(candidate: dict, bundle_path: Path, sig_path: Path) -> None:
    payload = {
        "build_timestamp": candidate["build_timestamp"],
        "sha384":          candidate.get("sha384"),
        "size":            candidate.get("size"),
        "bundle_path":     str(bundle_path),
        "sig_path":        str(sig_path),
        "source_file":     candidate["file"],
    }
    tmp = PENDING_MARKER.with_suffix(".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    with tmp.open("w") as fh:
        json.dump(payload, fh, indent=2)
    tmp.replace(PENDING_MARKER)


def main() -> int:
    # Format is deliberately simple — systemd's journal already tags
    # each line with the unit, PID, and priority derived from the level.
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    base_url = load_server_url()
    local_ts = load_local_timestamp()
    if not local_ts:
        # Missing timestamp means every remote entry would look "newer"
        # by string comparison — refuse rather than mis-trigger.
        logger.error("no /etc/mdmx-build-timestamp on this system — skipping")
        return 1

    logger.info("checking %s (local build %s)", base_url, local_ts)
    try:
        raw = http_get(base_url + MANIFEST_NAME, MANIFEST_TIMEOUT)
        manifest = json.loads(raw)
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        logger.error("manifest fetch failed: %s", exc)
        return 1

    candidate = pick_candidate(manifest, local_ts)
    if candidate is None:
        logger.info("up to date")
        clear_pending()
        return 0

    if already_pending(candidate):
        logger.info(
            "already downloaded pending update %s", candidate["build_timestamp"]
        )
        return 0

    # Wipe stale pendings before staging a new one — we only ever offer
    # one pending update at a time (the newest).
    if BUNDLE_DIR.exists():
        shutil.rmtree(BUNDLE_DIR, ignore_errors=True)
    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)

    bundle_path = BUNDLE_DIR / candidate["file"]
    sig_path    = BUNDLE_DIR / candidate["sig"]

    logger.info(
        "downloading %s (%s bytes)",
        candidate["file"], candidate.get("size", "?"),
    )
    try:
        http_download(base_url + candidate["file"], bundle_path, BUNDLE_TIMEOUT)
        http_download(base_url + candidate["sig"],  sig_path,    MANIFEST_TIMEOUT)
    except (urllib.error.URLError, OSError) as exc:
        logger.error("download failed: %s", exc)
        shutil.rmtree(BUNDLE_DIR, ignore_errors=True)
        return 1

    expected_sha = candidate.get("sha384")
    if expected_sha:
        actual = sha384_of(bundle_path)
        if actual.lower() != expected_sha.lower():
            logger.error(
                "sha384 mismatch: expected %s, got %s", expected_sha, actual
            )
            shutil.rmtree(BUNDLE_DIR, ignore_errors=True)
            return 1

    if not verify_hybrid(bundle_path, sig_path):
        logger.error("hybrid signature verification failed — discarding download")
        shutil.rmtree(BUNDLE_DIR, ignore_errors=True)
        return 1

    write_pending(candidate, bundle_path, sig_path)
    logger.info("pending update ready: %s", candidate["build_timestamp"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
