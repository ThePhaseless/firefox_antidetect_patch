#!/usr/bin/env python3
"""upstream_toolchain.py against a lock, and a fetcher that serves only what the lock pins.

What a build runs (`rust-version`, `pgo`) reads scripts/ci/locks/upstream-<tag>.json and
verifies every downloaded byte against it. Mozilla's index and chain of trust are read only
by `lock`, which a person runs once per port.

  known-bad
    1. a profile whose bytes do not match the locked sha256; 2. the locked sha256 with
       another size; 3. a leg that is not in the lock; 4. a tag with no lock file; 5. a lock
       of another changeset, tag, version or repository; 6. a lock entry that names an index
       route instead of a task's artifact, a bad sha256, a bad Rust release; 7. a profile
       without merged.profdata;
  known-good, and the network
    8. the Rust release and the profile of the lock; the only URL ever requested is the
       locked one (a fetcher that fails on any other, the index and the chain of trust
       included), and `rust-version` asks for nothing at all, through main() as the
       workflows run it; 9. the committed lock describes this tree and has both legs;
  the generator (`lock`), against a fake Taskcluster
    10. a profile that does not match its chain of trust, a chain of trust without a
        sha256, a changeset with no retail build, a build that fetched no profile, a
        toolchain with no X.Y.Z release, a tag that is not the tree's: refused; the lock it
        writes is accepted by the readers; 11. Taskcluster busy is asked again, a 404 is not.

Run it directly: `python3 scripts/test_upstream_toolchain.py`.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tarfile
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_upstream_source as c  # noqa: E402
import upstream_toolchain as u  # noqa: E402

SOURCE = {"version": "159.0", "repo": "https://hg.mozilla.org/releases/mozilla-release", "changeset": "a" * 40}
TAG = "FIREFOX_159_0_RELEASE"
RECORD_URL = "https://archive.mozilla.org/pub/firefox/candidates/159.0-candidates/build2/linux-x86_64/en-US/firefox-159.0.json"
RECORD = json.dumps({"moz_source_repo": SOURCE["repo"], "moz_source_stamp": SOURCE["changeset"]}).encode()
TASKS = {"win-x86_64": "W" * 22, "linux-x86_64": "L" * 22}


def profile_tar(members=(("merged.profdata", b"PROF"), ("en-US.log", b"LOG"))) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as tar:
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def profile_url(task: str) -> str:
    return "%s/queue/v1/task/%s/artifacts/public/build/profdata.tar.xz" % (u.TC, task)


def lock_of(profile: bytes, source: dict = SOURCE, tasks: dict = TASKS, **over) -> dict:
    legs = {leg: {"build_task": "B" * 22, "rust_version": "1.95.0", "rust_task": "R" * 22,
                  "pgo": {"task": task, "url": profile_url(task), "sha256": hashlib.sha256(profile).hexdigest(),
                          "size": len(profile)}}
            for leg, task in tasks.items()}
    lock = {"mozilla_tag": c.tag_of(source["version"]), "version": source["version"], "repo": source["repo"],
            "changeset": source["changeset"],
            "records": {"build_record": {"url": RECORD_URL, "sha256": hashlib.sha256(RECORD).hexdigest()}},
            "legs": legs}
    lock.update(over)
    return lock


class Pinned:
    """A fetcher that serves the locked URLs and fails on anything else: the index, a
    chain of trust, another task."""

    def __init__(self, serves: dict):
        self.serves = serves
        self.requested = []

    def __call__(self, url):
        self.requested.append(url)
        if url not in self.serves:
            raise AssertionError("not a pinned URL: %s" % url)
        return self.serves[url]


def refuses(fn, *words) -> bool:
    try:
        fn()
    except u.UpstreamError as exc:
        return all(w in str(exc) for w in words)
    return False


def write_lock(directory: Path, lock: dict, name: str = "upstream-%s.json" % TAG) -> Path:
    path = directory / name
    path.write_text(json.dumps(lock), encoding="utf-8")
    return path


def run_main(argv, get):
    """u.main(argv) with stdout and stderr captured and the retrying fetcher replaced."""
    out, err = io.StringIO(), io.StringIO()
    saved = u.http_get
    u.http_get = get
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = u.main(argv)
    finally:
        u.http_get = saved
    return code, out.getvalue(), err.getvalue()


# ---- the generator's Taskcluster -------------------------------------------------------

def fake_tc(profile=None, cot_sha="right", indexed=True, fetches=("rustc", "profdata"), channel="1.95.0"):
    profile = profile if profile is not None else profile_tar()
    sha = hashlib.sha256(profile).hexdigest() if cot_sha == "right" else cot_sha
    fetch = []
    if "rustc" in fetches:
        fetch.append({"task": "R" * 22, "artifact": "public/build/rustc.tar.zst"})
    if "profdata" in fetches:
        fetch.append({"task": "P" * 22, "artifact": "public/build/profdata.tar.xz"})
    build = {"metadata": {"name": "build"}, "payload": {"env": {"MOZ_FETCHES": json.dumps(fetch)}}}
    rust = {"metadata": {"name": "toolchain-rust"}, "payload": {"command": ["repack", "--channel", channel]}}
    cot = {"artifacts": {"public/build/profdata.tar.xz": {"sha256": sha}} if sha else {}}
    listing = b'<a href="build1/">build1/</a><a href="build2/">build2/</a>'

    def get(url):
        if "/index/v1/task/" in url:
            if not indexed:
                raise OSError("404")
            return json.dumps({"taskId": "B" * 22}).encode()
        table = {"/queue/v1/task/%s" % ("B" * 22): build, "/queue/v1/task/%s" % ("R" * 22): rust,
                 "/queue/v1/task/%s/artifacts/public/chain-of-trust.json" % ("P" * 22): cot}
        for suffix, obj in table.items():
            if url.endswith(suffix):
                return json.dumps(obj).encode()
        if url == profile_url("P" * 22):
            return profile
        if url == c.CANDIDATES.format(v="159.0"):
            return listing
        if url == RECORD_URL:
            return RECORD
        raise AssertionError("unexpected url %s" % url)
    return get


def busy_then(code: int, times: int):
    """http_get against a server that fails `times` times with `code`, then answers."""
    import urllib.error
    calls, waits = [], []

    def open_url(url, timeout):
        calls.append(url)
        if len(calls) <= times:
            raise urllib.error.HTTPError(url, code, "busy", {}, None)
        return io.BytesIO(b"OK")
    return u.http_get("https://tc/x", open_url, waits.append), waits


def refuses_http(fn) -> bool:
    import urllib.error
    try:
        fn()
    except urllib.error.HTTPError:
        return True
    return False


def main() -> int:
    prof = profile_tar()
    cases = []

    def case(name, ok):
        cases.append((name, bool(ok)))

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        out = tmp / "pgo"
        lock = lock_of(prof)
        win, lin = TASKS["win-x86_64"], TASKS["linux-x86_64"]
        serves = {profile_url(t): prof for t in TASKS.values()}

        # known-bad: the bytes
        other = profile_tar((("merged.profdata", b"OTHER"), ("en-US.log", b"LOG")))
        case("a profile whose sha256 is not the locked one: refused, both sha256s named",
             refuses(lambda: u.pgo("win-x86_64", out, Pinned({profile_url(win): other}), SOURCE, lock),
                     "the lock pins", lock["legs"]["win-x86_64"]["pgo"]["sha256"], hashlib.sha256(other).hexdigest()))
        case("a refused profile is not unpacked", not (out / "merged.profdata").exists())
        wrong_size = lock_of(prof)
        wrong_size["legs"]["win-x86_64"]["pgo"]["size"] += 1
        case("the locked sha256 with another size",
             refuses(lambda: u.pgo("win-x86_64", out, Pinned(serves), SOURCE, wrong_size), "bytes"))
        thin = profile_tar((("en-US.log", b"x"),))
        case("a locked profile that has no merged.profdata",
             refuses(lambda: u.pgo("win-x86_64", out, Pinned({profile_url(win): thin}), SOURCE, lock_of(thin)), "merged.profdata"))

        # known-bad: the lock
        missing_leg = lock_of(prof)
        del missing_leg["legs"]["linux-x86_64"]
        fetcher = Pinned(serves)
        case("a leg that is not in the lock (pgo): refused, named, nothing requested",
             refuses(lambda: u.pgo("linux-x86_64", out, fetcher, SOURCE, missing_leg), "linux-x86_64", TAG)
             and not fetcher.requested)
        case("a leg that is not in the lock (rust-version)",
             refuses(lambda: u.rust_version("linux-x86_64", SOURCE, missing_leg), "linux-x86_64"))
        case("a tag with no lock file: refused, the file named",
             refuses(lambda: u.load_lock(SOURCE, tmp / ("upstream-%s.json" % TAG)), "upstream-%s.json" % TAG, "missing"))
        for key, value in (("changeset", "b" * 40), ("mozilla_tag", "FIREFOX_158_0_RELEASE"), ("version", "158.0"),
                           ("repo", "https://hg.mozilla.org/releases/other")):
            path = write_lock(tmp, lock_of(prof, **{key: value}), "bad-%s.json" % key)
            case("a lock whose %s is not the tree's" % key, refuses(lambda: u.load_lock(SOURCE, path), key))
        no_record = lock_of(prof)
        del no_record["records"]
        case("a lock that pins no build record",
             refuses(lambda: u.load_lock(SOURCE, write_lock(tmp, no_record, "norec.json")), "build record"))
        index = lock_of(prof)
        index["legs"]["win-x86_64"]["pgo"]["url"] = "%s/index/v1/task/gecko.v2.x.shippable.revision.%s.firefox.win64-opt" % (u.TC, "a" * 40)
        fetcher = Pinned({})
        case("a lock entry that names an index route, not a task's artifact: refused before any request",
             refuses(lambda: u.pgo("win-x86_64", out, fetcher, SOURCE, index), "not the artifact") and not fetcher.requested)
        bad_sha = lock_of(prof)
        bad_sha["legs"]["win-x86_64"]["pgo"]["sha256"] = "XYZ"
        case("a lock entry without a 64-hex sha256",
             refuses(lambda: u.pgo("win-x86_64", out, Pinned(serves), SOURCE, bad_sha), "sha256"))
        bad_rust = lock_of(prof)
        bad_rust["legs"]["win-x86_64"]["rust_version"] = "nightly"
        case("a lock entry with no X.Y.Z Rust release", refuses(lambda: u.rust_version("win-x86_64", SOURCE, bad_rust), "Rust"))

        # known-good, and only the locked URL is requested
        fetcher = Pinned(serves)
        lines = u.pgo("win-x86_64", out, fetcher, SOURCE, lock)
        linux = u.pgo("linux-x86_64", out, Pinned(serves), SOURCE, lock)
        case("the profile unpacked, with the retail's LTO mode",
             (out / "merged.profdata").read_bytes() == b"PROF" and (out / "en-US.log").read_bytes() == b"LOG"
             and lines[-1] == "ac_add_options --enable-lto=full,cross" and linux[-1] == "ac_add_options --enable-lto=full,cross")
        case("pgo requests the locked URL, once, and nothing else (no index, no chain of trust)",
             fetcher.requested == [profile_url(win)])
        case("the Rust release of the lock", u.rust_version("win-x86_64", SOURCE, lock) == "1.95.0")

        # main(), as the workflows run it (no --lock: the committed one; with --lock: this tree's description)
        tree = u.upstream_source()
        tree_lock = lock_of(prof, source=tree)
        tree_path = write_lock(tmp, tree_lock, "tree.json")
        guard = Pinned({})
        code, printed, err = run_main(["--lock", str(tree_path), "--leg", "win-x86_64", "rust-version"], guard)
        case("main rust-version prints the locked release and asks for nothing",
             code == 0 and printed.strip() == "1.95.0" and guard.requested == [])
        guard = Pinned(serves)
        code, printed, err = run_main(["--lock", str(tree_path), "--leg", "linux-x86_64", "pgo", "--out", str(tmp / "m")], guard)
        case("main pgo requests only the locked URL", code == 0 and guard.requested == [profile_url(lin)])
        guard = Pinned({profile_url(lin): other})
        code, printed, err = run_main(["--lock", str(tree_path), "--leg", "linux-x86_64", "pgo", "--out", str(tmp / "m2")], guard)
        case("main pgo on bytes that are not the locked ones: exit 1, the sha256s in the message, nothing unpacked",
             code == 1 and "the lock pins" in err and not (tmp / "m2" / "merged.profdata").exists())
        guard = Pinned({})
        code, printed, err = run_main(["--lock", str(tmp / "nope.json"), "--leg", "win-x86_64", "rust-version"], guard)
        case("main with a lock that is not there: exit 1, named, no live fallback",
             code == 1 and "nope.json" in err and guard.requested == [])
        case("main with the committed lock of this tree, as the workflows call it (no --lock): no request, the release",
             run_main(["--leg", "win-x86_64", "rust-version"], Pinned({}))[0] == 0)

        # the committed lock
        committed = u.load_lock()
        case("the committed lock describes this tree and has both legs, each with a Rust release and a pinned profile",
             sorted(committed["legs"]) == sorted(u.PLATFORMS) and all(u.leg_entry(committed, leg) for leg in u.PLATFORMS)
             and committed["mozilla_tag"] == c.tag_of(tree["version"]))

        # the generator
        generated = u.make_lock(TAG, fake_tc(), SOURCE)
        expected = lock_of(prof, tasks={leg: "P" * 22 for leg in TASKS})
        case("lock: what it writes is what the readers accept, with the exact URLs and sha256s",
             generated == expected and all(u.leg_entry(generated, leg) for leg in u.PLATFORMS))
        case("lock: a profile that does not match its chain of trust",
             refuses(lambda: u.make_lock(TAG, fake_tc(cot_sha="0" * 64), SOURCE), "chain of trust"))
        case("lock: a chain of trust with no sha256 for the profile",
             refuses(lambda: u.make_lock(TAG, fake_tc(cot_sha=""), SOURCE), "no sha256"))
        case("lock: a changeset with no retail build",
             refuses(lambda: u.make_lock(TAG, fake_tc(indexed=False), SOURCE), "no retail build"))
        case("lock: a retail build that fetched no profile",
             refuses(lambda: u.make_lock(TAG, fake_tc(fetches=("rustc",)), SOURCE), "fetched 0"))
        case("lock: a Rust toolchain with no X.Y.Z release",
             refuses(lambda: u.make_lock(TAG, fake_tc(channel="nightly"), SOURCE), "X.Y.Z"))
        case("lock: a tag that is not the tree's", refuses(lambda: u.make_lock("FIREFOX_160_0_RELEASE", fake_tc(), SOURCE), TAG))

        case("Taskcluster busy (503) twice, then the answer: asked again", busy_then(503, 2) == (b"OK", [15, 60]))
        case("Taskcluster busy on every attempt: the error after the last wait", refuses_http(lambda: busy_then(503, 99)))
        case("a 404 is an answer: not asked again", refuses_http(lambda: busy_then(404, 1)))
        case("no linux-arm64 leg from firefox-56 on: nothing to ask the retail for",
             sorted(u.PLATFORMS) == ["linux-x86_64", "win-x86_64"] and sorted(u.LTO) == sorted(u.PLATFORMS))
    failures = 0
    for name, ok in cases:
        print(("ok    " if ok else "FAIL  ") + name)
        failures += not ok
    print("%d/%d cases as expected" % (len(cases) - failures, len(cases)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
