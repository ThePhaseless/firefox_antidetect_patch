#!/usr/bin/env python3
r"""The junit of the cargo job: `cargo test`'s text output (libtest's, stable on every toolchain) turned into one junit file per test binary.

The named hook tests judge (scripts/ci/hook_tests_judge.py) reads `junit-cargo/**/*.xml` of a run: a hook that names `cargo:<crate>::<test path>` is
judged on the testcase whose name is the test path exactly as `cargo test` prints it (`test <path> ... ok`) and whose classname holds the crate. The log
the job already keeps (`cargo test ... | tee cargo-test.log`) has all of it: a `Running unittests src/lib.rs (target/debug/deps/<crate>-<hash>)` line opens
each test binary, a `test <path> ... ok|FAILED|ignored` line is each test, a `---- <path> stdout ----` block is why one failed. No nightly flag
(`-Z unstable-options --format json`), no download: this reads text.

    python3 scripts/ci/cargo_junit.py cargo-test.log --out junit-cargo [--packages webrender,wr_glyph_rasterizer]

One file per test binary, `<out>/<binary>.xml` (`<binary>-doc.xml` for the doc-tests of a crate). The classname of its testcases is the crate: the package
named by --packages whose name, with `-` read as `_`, is the binary's name (so a hook may say `wgpu-core` for the binary `wgpu_core`), else the binary's
name. A test that did not print `ok` is a failure (`FAILED`, or anything libtest adds), `ignored` is skipped, `bench` is skipped. Exit 0 when a file
was written, 1 when the log has no test binary (a cargo that did not get as far as running one writes nothing for the judge to find: that is the judge's
red), 2 for a log that cannot be read.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from xml.sax.saxutils import quoteattr

#: `     Running unittests src/lib.rs (target/debug/deps/webrender-0123456789abcdef)`, `Running tests/x.rs (target\debug\deps\x-0123.exe)`, and
#: `   Doc-tests webrender` (cargo 1.8x prints `Doc-tests <crate>`; older ones the same).
RUNNING = re.compile(r"^\s*Running (?:unittests )?(?P<what>.+?) \((?P<exe>[^()]+)\)\s*$")
DOCTESTS = re.compile(r"^\s*Doc-tests (?P<name>\S+)\s*$")
TEST = re.compile(r"^test (?P<path>.+?) \.\.\. (?P<how>ok|FAILED|ignored|bench:.*|\S+)(?:, .*)?\s*$")
FAILURE_HEAD = re.compile(r"^---- (?P<path>.+?) (?:stdout|stderr) ----\s*$")
HASH = re.compile(r"-[0-9a-f]{8,}$")
MESSAGE_LINES = 12


def binary_name(exe: str) -> str:
    """`target/debug/deps/wr_glyph_rasterizer-0123456789abcdef.exe` -> `wr_glyph_rasterizer` (either slash, with or without .exe and the hash)."""
    leaf = re.split(r"[\\/]", exe.strip())[-1]
    if leaf.lower().endswith(".exe"):
        leaf = leaf[:-4]
    return HASH.sub("", leaf)


def parse(log: str) -> list:
    """-> [{"binary", "doc", "tests": [{"path", "how", "message"}]}] in the order of the log, one entry per test binary. Lines before the first
    binary are not tests; a test line outside any binary opens an anonymous one named `cargo`."""
    binaries, current, failing = [], None, None
    for raw in log.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        run = RUNNING.match(raw)
        doc = DOCTESTS.match(raw)
        if run or doc:
            name = binary_name(run.group("exe")) if run else doc.group("name")
            current = {"binary": name, "doc": bool(doc), "tests": []}
            binaries.append(current)
            failing = None
            continue
        test = TEST.match(raw)
        if test:
            if current is None:
                current = {"binary": "cargo", "doc": False, "tests": []}
                binaries.append(current)
            current["tests"].append({"path": test.group("path"), "how": test.group("how"), "message": ""})
            failing = None
            continue
        head = FAILURE_HEAD.match(raw)
        if head:
            failing = [head.group("path"), []]
            if current is not None:
                for t in current["tests"]:
                    if t["path"] == head.group("path"):
                        failing[1] = t.setdefault("lines", [])
            continue
        if failing is not None:
            if raw.startswith("failures:") or raw.startswith("test result:"):
                failing = None
            elif len(failing[1]) < MESSAGE_LINES:
                failing[1].append(raw)
    for b in binaries:
        for t in b["tests"]:
            t["message"] = "\n".join(l for l in t.pop("lines", []) if l.strip()).strip()
    return binaries


def package_of(binary: str, packages: list) -> str:
    """The package whose name is the binary's (`-` and `_` alike), else the binary's own name."""
    for package in packages:
        if package.replace("-", "_") == binary.replace("-", "_"):
            return package
    return binary


def junit(binary: dict, packages: list) -> str:
    crate = package_of(binary["binary"], packages)
    tests = binary["tests"]
    failed = [t for t in tests if t["how"] not in ("ok", "ignored") and not t["how"].startswith("bench")]
    skipped = [t for t in tests if t["how"] == "ignored" or t["how"].startswith("bench")]
    suite = crate + (" (doc-tests)" if binary["doc"] else "")
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<testsuites>",
             "  <testsuite name=%s tests=\"%d\" failures=\"%d\" skipped=\"%d\">" % (quoteattr(suite), len(tests), len(failed), len(skipped))]
    for t in tests:
        lines.append("    <testcase classname=%s name=%s>" % (quoteattr(crate), quoteattr(t["path"])))
        if t in failed:
            lines.append("      <failure message=%s>%s</failure>" % (quoteattr("test %s: %s" % (t["path"], t["how"])), _text(t["message"])))
        elif t in skipped:
            lines.append("      <skipped message=%s/>" % quoteattr(t["how"]))
        lines.append("    </testcase>")
    lines += ["  </testsuite>", "</testsuites>"]
    return "\n".join(lines) + "\n"


def _text(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def write(log: str, out: Path, packages: list) -> list:
    """Write one junit per test binary of `log` into `out`; return the paths. Two binaries of one name (a lib and a bin target) get a number."""
    out = Path(out)
    written, seen = [], {}
    for binary in parse(log):
        stem = binary["binary"] + ("-doc" if binary["doc"] else "")
        seen[stem] = seen.get(stem, 0) + 1
        name = stem if seen[stem] == 1 else "%s-%d" % (stem, seen[stem])
        out.mkdir(parents=True, exist_ok=True)
        target = out / (name + ".xml")
        with open(target, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(junit(binary, packages))
        written.append(target)
    return written


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("log", type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--packages", default="", help="comma-separated package names given to `cargo test -p`, to name the crate of a binary")
    args = ap.parse_args(argv)
    try:
        log = args.log.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print("cargo_junit: %s cannot be read: %s" % (args.log, exc), file=sys.stderr)
        return 2
    written = write(log, args.out, [p for p in args.packages.split(",") if p])
    for path in written:
        print("cargo_junit: wrote %s" % path)
    if not written:
        print("cargo_junit: no test binary in %s: nothing written" % args.log, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
