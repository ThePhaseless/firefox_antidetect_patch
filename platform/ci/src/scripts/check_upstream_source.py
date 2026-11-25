#!/usr/bin/env python3
"""Fail when browser/config/upstream_source.txt is not the source of the version
this tree builds.

Why this exists
---------------
The .mozconfig builds as MOZILLA_OFFICIAL, and an official build states its
source repository and changeset (source-repo.h, application.ini SourceRepository
and SourceStamp). Built from a git checkout of this fork, the build cannot name
them, so upstream_source.txt states the retail's values and the .mozconfig
exports them as MOZ_SOURCE_REPO / MOZ_SOURCE_CHANGESET.

Until 157 nothing noticed when they were missing: packager.mk extracted the URL
with awk, which printed nothing, and every binary up to firefox-53 shipped
without SourceRepository and SourceStamp while the retail has both. From 157
make_sourcestamp_file.py refuses the empty header and `mach package` fails.
The values are per release, so a port that moves the base without updating the
file would state the previous release's changeset: that is what this refuses.

Nothing here is read live and trusted on sight. Mozilla's record of the release
is pinned by content in scripts/ci/locks/upstream-<mozilla_tag>.json (its exact
URL and the sha256 of its bytes, written once per port by a person with
`python scripts/upstream_toolchain.py lock`); --online downloads that URL and
refuses bytes whose sha256 is not the locked one, before it reads a value.

Usage:
  python scripts/check_upstream_source.py            # the version matches the tree, the lock matches the file
  python scripts/check_upstream_source.py --online   # and the pinned record, checked by its sha256, has the file's values
Exit 0 = aligned, 1 = drift, a malformed file, a missing lock or bytes that are not the locked ones.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_FILE = ROOT / "browser" / "config" / "upstream_source.txt"
VERSION_FILE = ROOT / "browser" / "config" / "version_display.txt"
LOCKS = ROOT / "scripts" / "ci" / "locks"
KEYS = ("version", "repo", "changeset")
CANDIDATES = "https://archive.mozilla.org/pub/firefox/candidates/{v}-candidates/"
RECORD = CANDIDATES + "{build}/linux-x86_64/en-US/firefox-{v}.json"


class SourceError(ValueError):
    pass


def parse(text: str) -> dict[str, str]:
    """The three values of upstream_source.txt, or SourceError."""
    values: dict[str, str] = {}
    for n, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or key not in KEYS or key in values or not value:
            raise SourceError(f"line {n}: expected one of {KEYS} as key=value, once: {line!r}")
        values[key] = value
    missing = [k for k in KEYS if k not in values]
    if missing:
        raise SourceError(f"missing {', '.join(missing)}")
    if not re.fullmatch(r"[0-9a-f]{40}", values["changeset"]):
        raise SourceError(f"changeset is not a 40-hex revision: {values['changeset']!r}")
    if not values["repo"].startswith("https://"):
        raise SourceError(f"repo is not an https URL: {values['repo']!r}")
    return values


def check(values: dict[str, str], tree_version: str) -> None:
    """SourceError unless the file describes the version the tree builds."""
    if values["version"] != tree_version:
        raise SourceError(
            f"upstream_source.txt describes {values['version']} but the tree builds "
            f"{tree_version}: take repo and changeset from Mozilla's record of "
            f"{tree_version} (see the file's header) and update all three lines")


def tag_of(version: str) -> str:
    """Mozilla's release tag of a version: 159.0 -> FIREFOX_159_0_RELEASE."""
    if not re.fullmatch(r"\d+(\.\d+)+", version):
        raise SourceError(f"not a release version: {version!r}")
    return "FIREFOX_%s_RELEASE" % version.replace(".", "_")


def lock_path(version: str, locks: Path | None = None) -> Path:
    return Path(locks or LOCKS) / ("upstream-%s.json" % tag_of(version))


def is_sha256(value) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def load_lock(values: dict[str, str], path: Path | None = None) -> dict:
    """The lock of the tree's upstream tag, which must describe the same release as
    upstream_source.txt: SourceError when it is missing, unreadable or of another one.
    The pinned record, if any, is checked for shape here; its bytes in pinned_record."""
    path = Path(path) if path else lock_path(values["version"])
    try:
        lock = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SourceError(
            f"no lock for {tag_of(values['version'])}: {path.name} is missing from scripts/ci/locks; "
            "a person writes it once per port with `python scripts/upstream_toolchain.py lock "
            f"--tag {tag_of(values['version'])} --out scripts/ci/locks/{path.name}`") from None
    except (OSError, ValueError) as exc:
        raise SourceError(f"{path.name} is not readable JSON: {exc}") from None
    if not isinstance(lock, dict):
        raise SourceError(f"{path.name} is not a JSON object")
    for key, want in (("mozilla_tag", tag_of(values["version"])), ("version", values["version"]),
                      ("repo", values["repo"]), ("changeset", values["changeset"])):
        if lock.get(key) != want:
            raise SourceError(f"{path.name} says {key}={lock.get(key)!r} and the tree is {want!r}: "
                              "write the lock again for this release (`upstream_toolchain.py lock`)")
    record = (lock.get("records") or {}).get("build_record")
    if not isinstance(record, dict) or not str(record.get("url", "")).startswith("https://")             or not is_sha256(record.get("sha256")):
        raise SourceError(f"{path.name} pins no build record (records.build_record needs an https url and a sha256)")
    return lock


def http_read(url: str) -> bytes:
    return urllib.request.urlopen(url, timeout=30).read()


def pinned_record(lock: dict, get=http_read) -> dict:
    """Mozilla's build record of the release: the pinned URL, and nothing else, whose
    bytes must be the locked sha256 before anything is read from them."""
    pin = lock["records"]["build_record"]
    data = get(pin["url"])
    got = hashlib.sha256(data).hexdigest()
    if got != pin["sha256"]:
        raise SourceError(f"{pin['url']} is {got}, the lock pins {pin['sha256']}")
    return json.loads(data)


def pin_record(version: str, get=http_read) -> dict:
    """What the lock pins, read live: Mozilla's build record of the release (its last
    candidate build) as its exact URL and the sha256 of its bytes. For the person who
    writes the lock (upstream_toolchain.py lock); no check or build calls it."""
    listing = get(CANDIDATES.format(v=version)).decode()
    builds = sorted(set(re.findall(r"build(\d+)/", listing)), key=int)
    if not builds:
        raise SourceError(f"no candidate builds listed for {version}")
    url = RECORD.format(v=version, build="build" + builds[-1])
    data = get(url)
    return {"url": url, "sha256": hashlib.sha256(data).hexdigest()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--online", action="store_true",
                    help="also compare repo and changeset with Mozilla's record, "
                         "downloaded from the URL the lock pins and checked by its sha256")
    a = ap.parse_args(argv)
    try:
        values = parse(SOURCE_FILE.read_text(encoding="utf-8"))
        check(values, VERSION_FILE.read_text(encoding="utf-8").strip())
        lock = load_lock(values)
        if a.online:
            rec = pinned_record(lock, http_read)
            got = (rec.get("moz_source_repo"), rec.get("moz_source_stamp"))
            if got != (values["repo"], values["changeset"]):
                raise SourceError(f"Mozilla's record of {values['version']} says {got}, "
                                  f"the file says {(values['repo'], values['changeset'])}")
    except (SourceError, OSError) as exc:
        print(f"UPSTREAM SOURCE DRIFT: {exc}")
        return 1
    print(f"UPSTREAM SOURCE PASS - {values['version']} from {values['repo']} "
          f"at {values['changeset']}" + (" (matches Mozilla's record, pinned by sha256)" if a.online else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
