"""The toolchain inputs of the retail build of this tree, from a lock in this repository.

    python3 scripts/upstream_toolchain.py --leg win-x86_64 rust-version
    python3 scripts/upstream_toolchain.py --leg win-x86_64 pgo --out DIR
    python3 scripts/upstream_toolchain.py lock --tag FIREFOX_159_0_RELEASE --out scripts/ci/locks/upstream-FIREFOX_159_0_RELEASE.json

`rust-version` and `pgo` (what a build runs) read only scripts/ci/locks/upstream-<mozilla_tag>.json,
the lock of the tag browser/config/upstream_source.txt describes, and verify every byte they
download against it: per leg the Rust release, and the PGO profile as its exact Taskcluster URL
(a task id, never an index route), its size and its sha256. A lock that is missing, of another
release or without the leg is an error that names it, and so is a download whose sha256 is not
the locked one; nothing falls back to Mozilla's index or to a chain of trust read at run time.
The profile is unpacked only after its sha256 matched.

`lock` is for a person, once per port (and when the retail changes): it is the only mode that
reads Mozilla's records live, and it writes what the others then verify. It starts from
upstream_source.txt (the retail's repository and changeset, check_upstream_source.py) and
follows Mozilla's own records:

  Taskcluster index  gecko.v2.<project>.shippable.revision.<changeset>.firefox.<platform>-opt
    -> the retail build task of this changeset and platform
    -> its MOZ_FETCHES: the rustc toolchain task and the PGO profile task it used
    -> rustc: the toolchain task's repack command (--channel X.Y.Z), the
       official Rust release Mozilla repackages. rustup installs that release.
    -> PGO: public/build/profdata.tar.xz of the profile task (merged.profdata
       and en-US.log), whose sha256 must be the one the same task lists in its
       public/chain-of-trust.json (the signature is not verified) before it is locked.
    -> the build record that check_upstream_source.py compares (its URL and sha256)

So a new Firefox needs a new upstream_source.txt and a new lock, and
toolchain_parity.py compares the result with the retail's about:buildconfig
after the build.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UPSTREAM_SOURCE = ROOT / "browser" / "config" / "upstream_source.txt"
LOCKS = ROOT / "scripts" / "ci" / "locks"
TC = "https://firefox-ci-tc.services.mozilla.com/api"
PROFILE = "public/build/profdata.tar.xz"

#: release.yml's legs -> Mozilla's build platform names.
PLATFORMS = {"win-x86_64": "win64", "linux-x86_64": "linux64"}

#: What Mozilla's own CI builds with LTO: lto-pgo.configure turns MOZ_LTO=cross
#: into FULL LTO when PGO and MOZ_AUTOMATION are on and the target is x86_64
#: Windows or Linux, and into thin LTO otherwise. We do not set MOZ_AUTOMATION
#: (it changes far more than LTO), so the mode the retail got is asked for.
LTO = {"win-x86_64": "full,cross", "linux-x86_64": "full,cross"}


class UpstreamError(Exception):
    pass


#: Seconds before each new attempt. Taskcluster answers 5xx and 429 when it is busy
#: (run 41269143133: "HTTP Error 503: Service Unavailable" on the chain of trust,
#: and the leg died 8 minutes in); a 4xx is an answer and is not asked again.
RETRY_WAITS = (15, 60, 180, 300)


def http_get(url: str, open_url=urllib.request.urlopen, wait=time.sleep) -> bytes:
    for pause in RETRY_WAITS + (None,):
        try:
            with open_url(url, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if pause is None or not (e.code >= 500 or e.code == 429):
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if pause is None:
                raise
        print("upstream_toolchain: %s failed, again in %ds" % (url, pause), file=sys.stderr)
        wait(pause)


def upstream_source(path: Path = UPSTREAM_SOURCE) -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import check_upstream_source
    return check_upstream_source.parse(path.read_text("utf-8"))


def check_source():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import check_upstream_source
    return check_upstream_source


# ---- what a build runs: the lock, and the bytes checked against it ----------------------

def is_sha256(value) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def load_lock(source: dict | None = None, path: Path | None = None) -> dict:
    """The lock of the tag upstream_source.txt describes, or UpstreamError naming what is wrong."""
    cus = check_source()
    source = source or upstream_source()
    try:
        return cus.load_lock(source, path)
    except cus.SourceError as exc:
        raise UpstreamError(str(exc)) from None


def leg_entry(lock: dict, leg: str) -> dict:
    """The locked Rust release and PGO profile of `leg`, validated; UpstreamError when the leg is not in the lock."""
    entries = lock.get("legs")
    where = lock.get("mozilla_tag", "the lock")
    if not isinstance(entries, dict) or not isinstance(entries.get(leg), dict):
        raise UpstreamError("the lock of %s has no entry for the leg %s: write it again (`upstream_toolchain.py lock`)"
                            % (where, leg))
    entry = entries[leg]
    rust = entry.get("rust_version")
    if not isinstance(rust, str) or not re.fullmatch(r"\d+\.\d+\.\d+", rust):
        raise UpstreamError("the lock of %s has no X.Y.Z Rust release for %s: %r" % (where, leg, rust))
    pin = entry.get("pgo")
    task = pin.get("task") if isinstance(pin, dict) else None
    if not isinstance(task, str) or not re.fullmatch(r"[A-Za-z0-9_-]{22}", task):
        raise UpstreamError("the lock of %s has no profile task id for %s" % (where, leg))
    if pin.get("url") != "%s/queue/v1/task/%s/artifacts/%s" % (TC, task, PROFILE):
        raise UpstreamError("the lock of %s pins a profile URL for %s that is not the artifact of its task: %r"
                            % (where, leg, pin.get("url")))
    if not is_sha256(pin.get("sha256")) or not isinstance(pin.get("size"), int) or pin["size"] <= 0:
        raise UpstreamError("the lock of %s has no sha256 and size for the profile of %s" % (where, leg))
    return entry


def rust_version(leg: str, source: dict | None = None, lock: dict | None = None) -> str:
    """The Rust release the retail build of this tree used, as the lock says. No network."""
    return leg_entry(lock or load_lock(source), leg)["rust_version"]


def pinned_download(url: str, sha256: str, size: int | None, get) -> bytes:
    """The bytes of `url`, only if they are the locked ones."""
    data = get(url)
    got = hashlib.sha256(data).hexdigest()
    if got != sha256:
        raise UpstreamError("%s is %s, the lock pins %s" % (url, got, sha256))
    if size is not None and len(data) != size:
        raise UpstreamError("%s is %d bytes, the lock pins %d" % (url, len(data), size))
    return data


def unpack_profile(data: bytes, out: Path, task: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:xz") as tar:
        members = {m.name: m for m in tar.getmembers()}
        for wanted in ("merged.profdata", "en-US.log"):
            if wanted not in members or not members[wanted].isfile():
                raise UpstreamError("%s of %s has no %s" % (PROFILE, task, wanted))
            (out / wanted).write_bytes(tar.extractfile(members[wanted]).read())


def mozconfig_lines(leg: str, out: Path) -> list:
    return ["ac_add_options --enable-profile-use=cross",
            "ac_add_options --with-pgo-profile-path=%s" % (out / "merged.profdata"),
            "ac_add_options --with-pgo-jarlog=%s" % (out / "en-US.log"),
            "ac_add_options --enable-lto=%s" % LTO[leg]]


def pgo(leg: str, out: Path, get=None, source: dict | None = None, lock: dict | None = None) -> list:
    """Download the PGO profile the lock pins into `out`, refusing bytes that are not the
    locked ones, and return the mozconfig lines that use it, as the retail build does.
    The only URL requested is the locked one."""
    get = get or http_get
    pin = leg_entry(lock or load_lock(source), leg)["pgo"]
    data = pinned_download(pin["url"], pin["sha256"], pin["size"], get)
    unpack_profile(data, out, pin["task"])
    return mozconfig_lines(leg, out)


# ---- what a person runs once per port: Mozilla's records, read live, written as the lock ----

def retail_build(leg: str, get=http_get, source: dict | None = None) -> tuple:
    """The id and the task definition of the retail build of this tree for `leg`."""
    source = source or upstream_source()
    project = source["repo"].rstrip("/").rsplit("/", 1)[-1]
    platform = PLATFORMS[leg]
    route = "gecko.v2.%s.shippable.revision.%s.firefox.%s-opt" % (project, source["changeset"], platform)
    try:
        task_id = json.loads(get("%s/index/v1/task/%s" % (TC, route)))["taskId"]
    except Exception as exc:
        raise UpstreamError("no retail build indexed at %s: %s" % (route, exc)) from None
    return task_id, json.loads(get("%s/queue/v1/task/%s" % (TC, task_id)))


def fetched_task(build: dict, artifact_suffix: str) -> str:
    """The task id the build fetched `*artifact_suffix` from."""
    fetches = json.loads(build["payload"].get("env", {}).get("MOZ_FETCHES", "[]"))
    found = [f["task"] for f in fetches if f["artifact"].endswith(artifact_suffix)]
    if len(found) != 1:
        raise UpstreamError("the retail build %s fetched %d artifacts ending %s"
                            % (build["metadata"]["name"], len(found), artifact_suffix))
    return found[0]


def locked_leg(leg: str, get=http_get, source: dict | None = None) -> dict:
    """Mozilla's retail build of `leg`, as the lock's entry: the Rust release and the
    profile (task, exact URL, size, sha256), the profile checked against the chain of trust."""
    build_id, build = retail_build(leg, get, source)
    rust_task = fetched_task(build, "/rustc.tar.zst")
    toolchain = json.loads(get("%s/queue/v1/task/%s" % (TC, rust_task)))
    m = re.search(r"--channel\W+(\d+\.\d+\.\d+)\b", json.dumps(toolchain["payload"].get("command", "")))
    if not m:
        raise UpstreamError("the retail's Rust toolchain task %s names no X.Y.Z release"
                            % toolchain["metadata"]["name"])
    task = fetched_task(build, "/profdata.tar.xz")
    cot = json.loads(get("%s/queue/v1/task/%s/artifacts/public/chain-of-trust.json" % (TC, task)))
    want = cot.get("artifacts", {}).get(PROFILE, {}).get("sha256")
    if not want:
        raise UpstreamError("the chain of trust of %s lists no sha256 for %s" % (task, PROFILE))
    url = "%s/queue/v1/task/%s/artifacts/%s" % (TC, task, PROFILE)
    data = get(url)
    got = hashlib.sha256(data).hexdigest()
    if got != want:
        raise UpstreamError("%s of %s is %s, its chain of trust says %s" % (PROFILE, task, got, want))
    return {"build_task": build_id, "rust_version": m.group(1), "rust_task": rust_task,
            "pgo": {"task": task, "url": url, "sha256": got, "size": len(data)}}


def make_lock(tag: str, get=http_get, source: dict | None = None) -> dict:
    cus = check_source()
    source = source or upstream_source()
    if tag != cus.tag_of(source["version"]):
        raise UpstreamError("upstream_source.txt describes %s (tag %s), not %s"
                            % (source["version"], cus.tag_of(source["version"]), tag))
    try:
        record = cus.pin_record(source["version"], get)
    except cus.SourceError as exc:
        raise UpstreamError(str(exc)) from None
    return {"mozilla_tag": tag, "version": source["version"], "repo": source["repo"],
            "changeset": source["changeset"], "records": {"build_record": record},
            "legs": {leg: locked_leg(leg, get, source) for leg in sorted(PLATFORMS)}}


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--leg", choices=sorted(PLATFORMS))
    ap.add_argument("--lock", type=Path, help="the lock to read (default: the one of the tag upstream_source.txt describes)")
    sub = ap.add_subparsers(dest="what", required=True)
    sub.add_parser("rust-version")
    p = sub.add_parser("pgo")
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("lock")
    p.add_argument("--tag", required=True)
    p.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    try:
        if a.what == "lock":
            text = json.dumps(make_lock(a.tag), indent=1, sort_keys=True) + "\n"
            a.out.parent.mkdir(parents=True, exist_ok=True)
            with open(a.out, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
            print("wrote %s" % a.out)
            return 0
        if not a.leg:
            ap.error("--leg is required for %s" % a.what)
        lock = load_lock(path=a.lock)
        if a.what == "rust-version":
            print(rust_version(a.leg, lock=lock))
        else:
            print("\n".join(pgo(a.leg, a.out, lock=lock)))
    except UpstreamError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
