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
import time
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

# 60s for the small text manifest. Per-operation socket timeout for
# bundle transfers is deliberately shorter than the historical 30 min:
# with Range-based resume a stall is cheap to recover from, so detect
# stalls quickly (5 min of no data on the wire) and let the retry loop
# pick up where we left off.
MANIFEST_TIMEOUT = 60
BUNDLE_TIMEOUT = 300
DOWNLOAD_CHUNK = 1024 * 1024

# Bounded retry for the bundle fetch. Transient DNS/TLS/TCP blips on a
# flaky link should not require the whole 6h timer cycle to recover;
# four attempts with exponential backoff (2,4,8,16s, capped) covers the
# "ISP hiccupped" case without hammering a broken server.
MAX_DOWNLOAD_ATTEMPTS = 4


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


def http_download(url: str, dest: Path, timeout: int,
                  expected_size: Optional[int] = None,
                  attempts: int = MAX_DOWNLOAD_ATTEMPTS) -> None:
    """Fetch url to dest with resume + bounded retry.

    Writes to a ``.part`` sidecar; promotes to ``dest`` on success. On
    transient failure the ``.part`` is left behind so the next call (or
    the next scheduled run) can pick up with a ``Range: bytes=N-``
    request instead of restarting from zero.
    """
    for attempt in range(1, attempts + 1):
        try:
            _http_fetch_resumable(url, dest, timeout, expected_size)
            return
        except (urllib.error.URLError, OSError) as exc:
            if attempt == attempts:
                raise
            backoff = min(60, 2 ** attempt)
            logger.warning(
                "download attempt %d/%d failed (%s); retrying in %ds",
                attempt, attempts, exc, backoff,
            )
            time.sleep(backoff)


def _http_fetch_resumable(url: str, dest: Path, timeout: int,
                          expected_size: Optional[int]) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    existing = tmp.stat().st_size if tmp.exists() else 0

    # An oversized partial can never promote cleanly — the server's
    # manifest size is the authority, so wipe the sidecar and restart.
    if expected_size is not None and existing > expected_size:
        logger.warning("partial %s is larger than expected; discarding", tmp.name)
        tmp.unlink()
        existing = 0

    # Short-circuit: if the sidecar already matches the expected total,
    # there's nothing to fetch — just promote it. Covers the case where
    # a previous run completed the transfer but crashed between the
    # final chunk write and the rename.
    if expected_size is not None and existing == expected_size:
        tmp.replace(dest)
        return

    headers = {"User-Agent": "mdmx-updater/1"}
    if existing > 0:
        headers["Range"] = f"bytes={existing}-"

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        # 206 Partial Content => server honored Range (append to .part).
        # 200 OK with existing > 0 => server ignored Range; truncate and
        # restart from byte 0 rather than silently concatenating two
        # copies of the prefix.
        status = r.getcode()
        append = (existing > 0 and status == 206)
        if existing > 0 and not append:
            logger.info("server returned %d (no Range); restarting %s",
                        status, tmp.name)
        elif append:
            logger.info("resuming %s from byte %d", tmp.name, existing)
        with tmp.open("ab" if append else "wb") as fh:
            while True:
                chunk = r.read(DOWNLOAD_CHUNK)
                if not chunk:
                    break
                fh.write(chunk)

    got = tmp.stat().st_size
    if expected_size is not None and got != expected_size:
        # Keep .part so the next retry resumes from where we actually
        # are, not from zero. The exception propagates to the retry
        # loop above, which decides whether to try again.
        raise OSError(
            f"size mismatch for {tmp.name}: expected {expected_size}, got {got}"
        )
    tmp.replace(dest)


def _prune_stale_bundle_files(candidate_file: str, candidate_sig: str) -> None:
    """Drop anything in BUNDLE_DIR that isn't part of the current candidate.

    We keep the candidate's bundle, sig, and their ``.part`` sidecars
    so a resumable download in flight survives across invocations. A
    stale partial from a now-superseded candidate is useless and would
    waste disk space; wipe it.
    """
    if not BUNDLE_DIR.exists():
        return
    keep = {
        candidate_file, candidate_file + ".part",
        candidate_sig,  candidate_sig  + ".part",
    }
    for entry in BUNDLE_DIR.iterdir():
        if entry.name in keep:
            continue
        try:
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink()
        except OSError:
            pass


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

    # Keep any in-progress .part for the current candidate so a flaky
    # multi-GB download can finish across runs; drop anything else. We
    # only ever offer one pending update at a time (the newest).
    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
    _prune_stale_bundle_files(candidate["file"], candidate["sig"])

    bundle_path = BUNDLE_DIR / candidate["file"]
    sig_path    = BUNDLE_DIR / candidate["sig"]

    raw_size = candidate.get("size")
    expected_size: Optional[int] = None
    if isinstance(raw_size, int):
        expected_size = raw_size
    elif isinstance(raw_size, str) and raw_size.isdigit():
        expected_size = int(raw_size)

    logger.info(
        "downloading %s (%s bytes)",
        candidate["file"], expected_size if expected_size is not None else "?",
    )
    try:
        http_download(base_url + candidate["file"], bundle_path,
                      BUNDLE_TIMEOUT, expected_size=expected_size)
        http_download(base_url + candidate["sig"],  sig_path,    MANIFEST_TIMEOUT)
    except (urllib.error.URLError, OSError) as exc:
        # Deliberately leave the .part sidecar behind — the next run
        # resumes from it. Only hash/signature failures below (which
        # imply bad bytes, not a transport blip) drop downloaded data.
        logger.error("download failed: %s", exc)
        return 1

    expected_sha = candidate.get("sha384")
    if expected_sha:
        actual = sha384_of(bundle_path)
        if actual.lower() != expected_sha.lower():
            logger.error(
                "sha384 mismatch: expected %s, got %s", expected_sha, actual
            )
            # Bytes on disk are known-bad; a Range resume would just
            # replay the same wrong prefix. Drop the bundle (and its
            # .part, in case the rename above raced) so the next run
            # fetches from byte 0. The tiny .sig is harmless to keep.
            bundle_path.unlink(missing_ok=True)
            bundle_path.with_suffix(bundle_path.suffix + ".part").unlink(missing_ok=True)
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
