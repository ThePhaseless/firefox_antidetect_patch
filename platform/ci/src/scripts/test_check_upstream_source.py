#!/usr/bin/env python3
"""check_upstream_source.py, driven against the files it exists to refuse.

  known-bad
    1. a file left on the previous release after the tree moved on - the drift
       a port makes by moving the base and forgetting the file;
    2. a missing value; 3. a value given twice; 4. an unknown key;
    5. a changeset that is not a 40-hex revision (a version number pasted in);
    6. a repo that is not an https URL.
  known-good
    7. the three values, with comments and blank lines, for the tree's version;
  the pinned record (the lock, scripts/ci/locks/upstream-<tag>.json)
    8. a tag with no lock, a lock of another release, a lock that pins no record: refused;
    9. --online reads only the URL the lock pins: bytes whose sha256 is not the locked one
       are refused before a value is read, and the candidates listing is never requested;
   10. the pinned record against the file: equal passes, another changeset is drift;
   11. the committed lock is the tree's.

Run it directly, like test_release_plan.py:
`python3 scripts/test_check_upstream_source.py`.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_upstream_source as c  # noqa: E402

REPO = "repo=https://hg.mozilla.org/releases/mozilla-release"
REV = "changeset=737ec77d798755890b062aab541a90d6c75afd19"
GOOD = f"# comment\n\nversion=157.0.1\n{REPO}\n{REV}\n"

REFUSED = [
    ("a file left on the previous release", f"version=156.0.1\n{REPO}\n{REV}\n", "157.0.1"),
    ("a missing changeset", f"version=157.0.1\n{REPO}\n", "157.0.1"),
    ("a value given twice", f"version=157.0.1\n{REPO}\n{REPO}\n{REV}\n", "157.0.1"),
    ("an unknown key", f"version=157.0.1\n{REPO}\n{REV}\nbranch=release\n", "157.0.1"),
    ("a changeset that is a version", f"version=157.0.1\n{REPO}\nchangeset=157.0.1\n", "157.0.1"),
    ("a repo that is not https", f"version=157.0.1\nrepo=hg.mozilla.org\n{REV}\n", "157.0.1"),
]

VALUES = {"version": "157.0.1", "repo": "https://hg.mozilla.org/releases/mozilla-release",
          "changeset": "737ec77d798755890b062aab541a90d6c75afd19"}
RECORD_URL = ("https://archive.mozilla.org/pub/firefox/candidates/157.0.1-candidates/build1/"
              "linux-x86_64/en-US/firefox-157.0.1.json")
LOCK_NAME = "upstream-FIREFOX_157_0_1_RELEASE.json"


def record_bytes(changeset=VALUES["changeset"]) -> bytes:
    return json.dumps({"moz_source_repo": VALUES["repo"], "moz_source_stamp": changeset}).encode()


def lock_for(record: bytes, **over) -> dict:
    lock = {"mozilla_tag": "FIREFOX_157_0_1_RELEASE", "version": VALUES["version"], "repo": VALUES["repo"],
            "changeset": VALUES["changeset"],
            "records": {"build_record": {"url": RECORD_URL, "sha256": hashlib.sha256(record).hexdigest()}}}
    lock.update(over)
    return lock


class Pinned:
    """Serves the URLs it is given and fails on any other (the candidates listing, say)."""

    def __init__(self, serves: dict):
        self.serves, self.requested = serves, []

    def __call__(self, url):
        self.requested.append(url)
        if url not in self.serves:
            raise AssertionError("not a pinned URL: %s" % url)
        return self.serves[url]


def refused(fn, *words) -> bool:
    try:
        fn()
    except c.SourceError as exc:
        return all(w in str(exc) for w in words)
    return False


def run_main(tmp: Path, lock, get, online=True):
    """c.main() on a tree of its own (upstream_source.txt, version_display.txt, the lock), the fetcher injected."""
    (tmp / "locks").mkdir(exist_ok=True)
    (tmp / "upstream_source.txt").write_text(
        "version=%s\nrepo=%s\nchangeset=%s\n" % (VALUES["version"], VALUES["repo"], VALUES["changeset"]), encoding="utf-8")
    (tmp / "version_display.txt").write_text(VALUES["version"] + "\n", encoding="utf-8")
    for old in (tmp / "locks").glob("*.json"):
        old.unlink()
    if lock is not None:
        (tmp / "locks" / LOCK_NAME).write_text(json.dumps(lock), encoding="utf-8")
    saved = c.SOURCE_FILE, c.VERSION_FILE, c.LOCKS, c.http_read
    c.SOURCE_FILE, c.VERSION_FILE, c.LOCKS, c.http_read = tmp / "upstream_source.txt", tmp / "version_display.txt", tmp / "locks", get
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            code = c.main(["--online"] if online else [])
    finally:
        c.SOURCE_FILE, c.VERSION_FILE, c.LOCKS, c.http_read = saved
    return code, out.getvalue()


def main() -> int:
    failures = 0
    for name, text, tree in REFUSED:
        try:
            c.check(c.parse(text), tree)
        except c.SourceError as exc:
            print(f"ok    refused: {name}: {exc}")
        else:
            print(f"FAIL  accepted: {name}")
            failures += 1
    try:
        got = c.parse(GOOD)
        c.check(got, "157.0.1")
        assert got == {"version": "157.0.1",
                       "repo": "https://hg.mozilla.org/releases/mozilla-release",
                       "changeset": "737ec77d798755890b062aab541a90d6c75afd19"}, got
        print("ok    the tree's version with comments and blank lines")
    except (c.SourceError, AssertionError) as exc:
        print(f"FAIL  refused the good file: {exc}")
        failures += 1

    extra = []

    def case(name, ok):
        extra.append((name, bool(ok)))

    good = record_bytes()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "x").mkdir()
        case("a tag with no lock: refused, the file named",
             refused(lambda: c.load_lock(VALUES, tmp / "x" / LOCK_NAME), LOCK_NAME, "missing"))
        for key, value in (("changeset", "b" * 40), ("mozilla_tag", "FIREFOX_156_0_RELEASE"), ("version", "156.0"),
                           ("repo", "https://hg.mozilla.org/releases/other")):
            f = tmp / ("bad-%s.json" % key)
            f.write_text(json.dumps(lock_for(good, **{key: value})), encoding="utf-8")
            case("a lock whose %s is not the file's" % key, refused(lambda: c.load_lock(VALUES, f), key))
        f = tmp / "norecord.json"
        lock = lock_for(good)
        lock["records"] = {}
        f.write_text(json.dumps(lock), encoding="utf-8")
        case("a lock that pins no record", refused(lambda: c.load_lock(VALUES, f), "pins no build record"))
        lock = lock_for(good)
        lock["records"]["build_record"]["sha256"] = "abc"
        f.write_text(json.dumps(lock), encoding="utf-8")
        case("a lock that pins a record by a short sha256", refused(lambda: c.load_lock(VALUES, f), "pins no build record"))

        # the pinned record
        fetcher = Pinned({RECORD_URL: good})
        rec = c.pinned_record(lock_for(good), fetcher)
        case("the pinned record: the locked URL, once, nothing else",
             fetcher.requested == [RECORD_URL] and rec["moz_source_stamp"] == VALUES["changeset"])
        fetcher = Pinned({RECORD_URL: record_bytes("b" * 40)})
        case("bytes whose sha256 is not the locked one are refused before a value is read",
             refused(lambda: c.pinned_record(lock_for(good), fetcher), "the lock pins", hashlib.sha256(good).hexdigest()))

        # --online, through main()
        fetcher = Pinned({RECORD_URL: good})
        code, printed = run_main(tmp, lock_for(good), fetcher)
        case("--online: the record the lock pins has the file's values: pass, one request, the pinned URL",
             code == 0 and "PASS" in printed and fetcher.requested == [RECORD_URL])
        fetcher = Pinned({RECORD_URL: record_bytes("b" * 40)})
        code, printed = run_main(tmp, lock_for(good), fetcher)
        case("--online: another record than the pinned one: red, no value from it is used",
             code == 1 and "DRIFT" in printed and "the lock pins" in printed)
        other = record_bytes("b" * 40)
        fetcher = Pinned({RECORD_URL: other})
        code, printed = run_main(tmp, lock_for(other), fetcher)
        case("--online: a pinned record that says another changeset than the file: drift",
             code == 1 and "DRIFT" in printed and "says" in printed)
        fetcher = Pinned({})
        code, printed = run_main(tmp, None, fetcher)
        case("--online: no lock for the tag: red, named, no request (no live fallback)",
             code == 1 and "no lock for FIREFOX_157_0_1_RELEASE" in printed and fetcher.requested == [])
        fetcher = Pinned({})
        code, printed = run_main(tmp, lock_for(good), fetcher, online=False)
        case("without --online nothing is requested, and the lock is still checked",
             code == 0 and fetcher.requested == [])

    committed = c.parse(c.SOURCE_FILE.read_text(encoding="utf-8"))
    case("the committed lock is the tree's, and pins a record",
         c.load_lock(committed)["records"]["build_record"]["url"].startswith("https://archive.mozilla.org/"))

    for name, ok in extra:
        print(("ok    " if ok else "FAIL  ") + name)
        failures += not ok
    total = len(REFUSED) + 1 + len(extra)
    print(f"{total - failures}/{total} cases as expected")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
