#!/usr/bin/env python3
"""Our xpcshell tests on the candidate's packaged binary, `firefox -xpcshell`, without Mozilla's harness and without a build.

The package has the shell (browser/app/nsBrowserApp.cpp: `-xpcshell` is handled before anything else) and not the harness: testing/xpcshell/head.js,
the modules of `resource://testing-common/` (Assert, TestUtils, StructuredLog, AppInfo, httpd, ...) and the head files of the manifests are test files
of the source tree, never shipped. This script is the part of Mozilla's runner (testing/xpcshell/runxpcshelltests.py) that the package needs:

  fetch  the unmodified Mozilla files the tests need, at the tag of the series' UPSTREAM.json, from the lock (scripts/ci/xpcshell_support.json: a path
         and a sha256 each); a file whose bytes are not the locked ones is a red, never a quiet substitute
  run    for each declared file (scripts/ci/xpcshell_tests.json): read the manifest that lists it (ours beside it in the series, else Mozilla's of the
         folder: head files, prefs, firefox-appdir, environment), build the
         command of buildXpcsCmd / buildCmdHead / buildCmdTestFile, run it with the runner's environment (no non-local connection), parse the
         structured log head.js prints, and write junit + a result JSON. Exit 1 when a test fails or is skipped, a process dies or times out, a file
         collects no test, or fewer tests were collected than the declared minimum
  check  the declared list is exactly the set of our xpcshell tests that the series holds (discover): one the list does not run is a red, so is a
         listed one that the series does not have, so a new test of ours cannot be left out of the leg unseen
  prefs  every preference the packaged engine has (default branch: name, type, value, locked; user branch of a fresh profile), written by
         scripts/ci/prefs_dump.js in `-xpcshell` mode, as a sorted JSON
  prefs-compare  two such dumps: zero differences is green, any added, missing or changed preference (name, both values, the locked flag) is red; with
         --control the two are one engine dumped twice and a difference is a broken control (exit 2), not a result
  prefs-summary  the verdicts and every difference of a prefs-out folder, as Markdown for the job's summary
  verify-asset  the published engine (`gh release download <tag>`, seal.json and the leg's archive) is the one the seal says: sha256 of the archive
  lock   (a person, on a machine that has the Mozilla tag in git) rewrite the lock: the files every test needs, and for each declared test the manifest of
         Mozilla's folder and its head files, or, when a manifest of OURS lists the test (xpcshell-stealth.toml beside it in the series), the head files that
         manifest names and that are not ours; each with its sha256, computed from the blobs of the tag

The files of OURS (the tests) come from the series checkout: `<series>/<group>/<folder>/src/<path of the test in the tree>`. Mozilla's come from the
lock. The layout the shell sees is the one of an objdir's `_tests/xpcshell/<folder>`: the test and the head files side by side, the working directory
there, so `resource://test/` and `do_get_file` mean what they mean in Mozilla's runs.

What is NOT done, on purpose: the manifest's skip-if / run-if (our list is declared per leg: a test that must not run on a system is not in it, and one
that is skipped by the shell is red), the profiler (MOZ_PROFILER_STARTUP: no test of ours reads it), the crash reporter, retries.

    python3 scripts/ci/xpcshell_run.py fetch --series engine-series --lock scripts/ci/xpcshell_support.json --into xpc-support
    python3 scripts/ci/xpcshell_run.py run --binary ff/firefox --series engine-series --support xpc-support --out xpcshell-result
    python3 scripts/ci/xpcshell_run.py lock --git C:/ff/source --series C:/ff/wt/series-69 --out scripts/ci/xpcshell_support.json
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from xml.sax.saxutils import quoteattr

HERE = Path(__file__).resolve().parent
LIST = HERE / "xpcshell_tests.json"
LOCK = HERE / "xpcshell_support.json"

# What every test needs, whatever it is (paths in Mozilla's tree). The directories are listed by the lock and take their files, not their folders.
HARNESS = "testing/xpcshell/head.js"
MODULES_DIR = "testing/modules"
# The files that the build puts in `resource://testing-common/` next to testing/modules (TESTING_JS_MODULES of other moz.build files) and that head.js
# or one of our tests imports. Add one here when a test of ours imports another, then run `lock`.
MODULES_EXTRA = (
    "toolkit/modules/tests/modules/PromiseTestUtils.sys.mjs",
    "tools/code-coverage/PerTestCoverageUtils.sys.mjs",
    "netwerk/test/httpserver/httpd.sys.mjs",
)
MODULES_SKIP = ("moz.build",)
PROFILES_DIR = "testing/profiles"
PROFILE_NAME = "xpcshell"
RAW = "https://raw.githubusercontent.com/%s/%s/%s"

TIMEOUT_S = 180
PER_FILE_ERROR_LINES = 6


# ----------------------------------------------------------------------------------------------------------------------------------------------
# the declared list and the lock
# ----------------------------------------------------------------------------------------------------------------------------------------------
def load_list(path: Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    files = data.get("files")
    if not isinstance(files, list) or not files or not all(isinstance(f, str) and f for f in files):
        raise SystemExit("%s: `files` must be a non-empty list of paths in the tree" % path)
    if len(set(files)) != len(files):
        raise SystemExit("%s: a file is declared twice" % path)
    minimum = data.get("min_tests")
    if not isinstance(minimum, int) or minimum < 1:
        raise SystemExit("%s: `min_tests` must be a positive integer" % path)
    return {"files": files, "min_tests": minimum}


def load_lock(path: Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not data.get("mozilla_tag") or not isinstance(data.get("files"), dict) or not data["files"]:
        raise SystemExit("%s: no tag or no files" % path)
    return data


def write_lf(path: Path, text: str) -> None:
    """Text with LF only, on Windows too (the lock is committed; the rest is read by people and tools that take either)."""
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def sha256_of(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def upstream(series: Path) -> dict:
    return json.loads((Path(series) / "UPSTREAM.json").read_text(encoding="utf-8"))


def check_lock_matches_upstream(lock: dict, up: dict) -> None:
    if lock["mozilla_tag"] != up.get("mozilla_tag"):
        raise SystemExit("the lock is for %s and the series says %s: run `lock` on the new tag (scripts/ci/xpcshell_run.py)"
                         % (lock["mozilla_tag"], up.get("mozilla_tag")))


def locate_test(series: Path, rel: str) -> Path:
    """The file of ours at `rel` (a path in the tree): `<series>/<group>/<folder>/src/<rel>`, exactly one."""
    found = sorted(Path(series).glob("*/*/src/" + rel))
    if len(found) != 1:
        raise FileNotFoundError("%s: %d files in the series (`*/*/src/%s`), exactly one is needed" % (rel, len(found), rel))
    return found[0]


XPCSHELL_DIRS = ("unit", "xpcshell")


def is_xpcshell_dir(parts) -> bool:
    """A folder name of Mozilla's xpcshell tests: `unit`, `xpcshell`, or `unit_<kind>` (every xpcshell folder of the tree is `tests/unit`, `test/unit`,
    `tests/xpcshell` or a `unit_*` next to them)."""
    return any(p in XPCSHELL_DIRS or p.startswith("unit_") for p in parts)


def discover(series: Path) -> list:
    """The xpcshell tests of OURS in the series, computed from the checkout: every `test_*.js` / `test_*.mjs` of `<group>/<folder>/src/` that is in an
    xpcshell folder (see is_xpcshell_dir), or whose folder holds an `xpcshell*.toml` of ours. The series' src holds only the files a feature ADDS (what
    it modifies is in hooks.patch), so each one is ours. Paths in the tree, sorted."""
    found = set()
    for src in sorted(Path(series).glob("*/*/src")):
        if not src.is_dir():
            continue
        for path in src.rglob("test_*"):
            if path.suffix not in (".js", ".mjs") or path.name.endswith(".sys.mjs") or not path.is_file():
                continue
            rel = path.relative_to(src)
            if is_xpcshell_dir(rel.parts[:-1]) or any(path.parent.glob("xpcshell*.toml")):
                found.add(rel.as_posix())
    return sorted(found)


def check_list(series: Path, files: list) -> list:
    """The reds of the list against the series, as lines: a test of ours that the list does not run, a listed file that the series does not have (or has
    twice), a listed file that is not an xpcshell test of ours by the rule of `discover` (the rule and the list must say the same)."""
    ours = set(discover(series))
    reasons = []
    for rel in sorted(ours - set(files)):
        reasons.append("%s: an xpcshell test of ours that the declared list does not run (add it to scripts/ci/xpcshell_tests.json and run `lock`)" % rel)
    for rel in files:
        try:
            locate_test(series, rel)
        except FileNotFoundError as exc:
            reasons.append("%s: declared, and the series does not have it (%s)" % (rel, exc))
            continue
        if rel not in ours:
            reasons.append("%s: declared, but it is not an xpcshell test of ours by the rule of discover (test_*.js or test_*.mjs in a unit/xpcshell folder, "
                           "or beside an xpcshell*.toml of ours)" % rel)
    return reasons


def check_cmd(series: Path, list_path: Path) -> int:
    declared = load_list(list_path)
    reasons = check_list(series, declared["files"])
    for reason in reasons:
        print("RED " + reason)
    print("check: %d declared, %d found in the series, %d problem(s)" % (len(declared["files"]), len(discover(series)), len(reasons)))
    return 1 if reasons else 0


# ----------------------------------------------------------------------------------------------------------------------------------------------
# fetch
# ----------------------------------------------------------------------------------------------------------------------------------------------
def _download(url: str, attempts: int = 4, opener=urllib.request.urlopen, sleep=time.sleep) -> bytes:
    last = None
    for i in range(attempts):
        try:
            with opener(urllib.request.Request(url, headers={"User-Agent": "ci"}), timeout=60) as response:
                return response.read()
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            last = exc
            sleep(2 * (i + 1))
    raise RuntimeError("%s: %s" % (url, last))


def fetch(series: Path, lock_path: Path, into: Path, opener=urllib.request.urlopen, sleep=time.sleep) -> int:
    lock = load_lock(lock_path)
    up = upstream(series)
    check_lock_matches_upstream(lock, up)
    owner_repo = re.sub(r"^https://github\.com/|\.git$", "", up["mozilla_repository"])
    base = RAW % (owner_repo, lock["mozilla_tag"], "")
    into = Path(into)
    bad = []

    def one(item):
        rel, want = item
        data = _download(base + rel, opener=opener, sleep=sleep)
        got = hashlib.sha256(data).hexdigest()
        if got != want:
            return "%s: sha256 %s, the lock has %s" % (rel, got, want)
        target = into / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return ""

    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for result in pool.map(lambda item: _safe(one, item), sorted(lock["files"].items())):
            if result:
                bad.append(result)
    for line in bad:
        print("FETCH FAIL " + line)
    size = sum(p.stat().st_size for p in into.rglob("*") if p.is_file()) if into.exists() else 0
    print("fetch: %d files, %d bytes, %.1f s, tag %s, %d bad" % (len(lock["files"]), size, time.monotonic() - started, lock["mozilla_tag"], len(bad)))
    return 1 if bad else 0


def _safe(function, item):
    try:
        return function(item)
    except Exception as exc:  # noqa: BLE001 - a failed fetch is a red line, not a traceback
        return "%s: %s" % (item[0], exc)


def verify_asset(directory: Path, leg: str) -> int:
    """The published engine as downloaded (`gh release download <tag> --pattern seal.json --pattern 'firefox-*-stealth-<leg>.*'`): exactly one archive of
    the leg, named in the release's seal.json, with the sha256 the seal has. Anything else is a red, never a quiet use of the archive."""
    directory = Path(directory)
    try:
        seal = json.loads((directory / "seal.json").read_text(encoding="utf-8"))
        assets = seal["assets"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("RED seal.json of the release could not be read: %s" % exc)
        return 1
    archives = sorted(p for p in directory.glob("firefox-*-stealth-%s.*" % leg) if p.is_file())
    if len(archives) != 1:
        print("RED expected one firefox-*-stealth-%s archive in %s, found %d: %s" % (leg, directory, len(archives), [p.name for p in archives]))
        return 1
    archive = archives[0]
    record = assets.get(archive.name) if isinstance(assets, dict) else None
    want = record.get("sha256") if isinstance(record, dict) else None
    if not want:
        print("RED %s is not in the assets of seal.json (tag %s)" % (archive.name, seal.get("tag")))
        return 1
    got = sha256_of(archive)
    if got != want:
        print("RED %s: sha256 %s, seal.json (tag %s) has %s" % (archive.name, got, seal.get("tag"), want))
        return 1
    print("verify-asset: %s is the %s archive of the seal, sha256 %s" % (archive.name, seal.get("tag"), got))
    return 0


# ----------------------------------------------------------------------------------------------------------------------------------------------
# every preference of the packaged engine, and the comparison of two engines
# ----------------------------------------------------------------------------------------------------------------------------------------------
PREFS_SCRIPT = HERE / "prefs_dump.js"
PREFS_TYPES = ("string", "int", "bool", "invalid", "error")
PREFS_BRANCHES = ("default", "user")
PREFS_OUTPUT_LINES = 40  # the shell's output that a red without a dump prints
EXIT_CONTROL = 2  # prefs-compare --control: the same engine dumped twice differs; the control is broken, so no result is read from the runs


def prefs_dump(binary, out: Path, root: Path | None = None, timeout: float = TIMEOUT_S, script: Path = PREFS_SCRIPT) -> int:
    """One dump: `firefox -xpcshell -g <gre> -a <gre>/browser -f prefs_dump.js -e "quit(0);"` with the leg's environment (environment()), a FRESH empty
    profile folder at a fixed place (`root`, emptied first: the same path for every dump, so that nothing that holds the path can differ between two
    runs) and PREFS_DUMP_OUT. The output is read back and written again sorted, LF only, with a `meta` that prefs-compare ignores. Red when the shell
    exits non-zero, hangs, or writes no (or no usable) dump."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    root = (Path(root) if root else Path(tempfile.gettempdir()) / "prefs-dump-root").resolve()  # absolute: the shell runs with it as its working directory
    shutil.rmtree(root, ignore_errors=True)
    exe = list(binary) if isinstance(binary, (list, tuple)) else [str(binary)]
    # absolute: the shell runs with `root` as its working directory, and a relative `ff/firefox` is looked up there (FileNotFoundError on Linux)
    exe[-1] = str(Path(exe[-1]).resolve())
    xre = Path(exe[-1]).parent
    raw = root / "dump-raw.json"
    env = environment(xre, root)  # makes root/profile, root/temp, root/temp/moz-appdata
    env["PREFS_DUMP_OUT"] = str(raw)
    command = exe + ["-xpcshell", "-g", str(xre), "-a", str(xre / "browser"), "-f", str(Path(script).resolve()), "-e", "quit(0);"]
    rc, output, seconds, timed_out = run_command(command, env, root, timeout)
    write_lf(out.with_suffix(".log"), output)
    if timed_out:
        print("RED prefs: the shell timed out after %d s (%s)" % (timeout, out.name))
        return 1
    if rc != 0:
        print("RED prefs: the shell exited with %s (%s); the shell's output (last %d lines):\n%s" % (rc, out.name, PREFS_OUTPUT_LINES, "\n".join(output.splitlines()[-PREFS_OUTPUT_LINES:])))
        return 1
    try:
        dump = json.loads(raw.read_text(encoding="utf-8"))
        problems = dump_problems(dump)
    except (OSError, ValueError) as exc:
        # a shell that exits 0 after a JavaScript error (a script that does not parse) writes nothing: its own output is the cause
        print("RED prefs: no readable dump at PREFS_DUMP_OUT (%s): %s; the shell's output (last %d lines):\n%s"
              % (out.name, exc, PREFS_OUTPUT_LINES, "\n".join(output.splitlines()[-PREFS_OUTPUT_LINES:]) or "(none)"))
        return 1
    if problems:
        print("RED prefs: the dump %s is not usable: %s" % (out.name, "; ".join(problems[:10])))
        return 1
    dump["meta"] = dict(dump.get("meta") or {}, os="windows" if os.name == "nt" else "linux", seconds=round(seconds, 3),
                        default_count=len(dump["default"]), user_count=len(dump["user"]))
    write_lf(out, json.dumps(dump, sort_keys=True, indent=1, ensure_ascii=True) + "\n")
    print("prefs: %s: %d default, %d user, %.1f s" % (out.name, len(dump["default"]), len(dump["user"]), seconds))
    return 0


def _value_ok(entry: dict) -> bool:
    kind, value = entry.get("type"), entry.get("value")
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind in ("string", "error"):
        return isinstance(value, str)
    return value is None  # invalid


def dump_problems(dump) -> list:
    """What makes a dump not a dump: not an object, no default branch or an empty one (a shell that listed nothing is not a measurement of zero
    differences), an entry without a known type or whose value does not have that type, a default entry without a boolean `locked`."""
    if not isinstance(dump, dict):
        return ["not a JSON object"]
    problems = []
    for branch in PREFS_BRANCHES:
        entries = dump.get(branch)
        if not isinstance(entries, dict):
            problems.append("no `%s` object" % branch)
            continue
        if branch == "default" and not entries:
            problems.append("the default branch is empty")
        for name, entry in sorted(entries.items()):
            if not isinstance(entry, dict) or entry.get("type") not in PREFS_TYPES or not _value_ok(entry):
                problems.append("%s pref %r is malformed: %r" % (branch, name, entry))
            elif branch == "default" and entry.get("type") not in ("invalid", "error") and not isinstance(entry.get("locked"), bool):
                problems.append("default pref %r has no boolean `locked`: %r" % (name, entry))
    return problems


def _show(entry: dict) -> str:
    text = "%s:%s" % (entry.get("type"), json.dumps(entry.get("value"), ensure_ascii=True))
    return text + (" locked=%s" % json.dumps(entry["locked"]) if "locked" in entry else "")


def prefs_diff(a: dict, b: dict) -> list:
    """Every difference between two dumps, as {branch, name, kind: changed|missing|added, a, b}: `missing` is in `a` and not in `b`, `added` the
    reverse. An entry is its type, its value (compared as JSON text, so 1 is not true and "5" is not 5) and, on the default branch, its locked flag.
    Nothing is ignored: there is no list of expected differences."""
    found = []
    for branch in PREFS_BRANCHES:
        left, right = a.get(branch, {}), b.get(branch, {})
        for name in sorted(set(left) | set(right)):
            if name not in right:
                found.append({"branch": branch, "name": name, "kind": "missing", "a": left[name], "b": None})
            elif name not in left:
                found.append({"branch": branch, "name": name, "kind": "added", "a": None, "b": right[name]})
            elif json.dumps(left[name], sort_keys=True) != json.dumps(right[name], sort_keys=True):
                found.append({"branch": branch, "name": name, "kind": "changed", "a": left[name], "b": right[name]})
    return found


def prefs_compare(path_a: Path, path_b: Path, out: Path | None = None, control: bool = False) -> int:
    """0 when the two dumps have no difference at all; 1 for any difference (every one is printed: pref name, both values) or a dump that is not
    usable; with `control` (one engine dumped twice) a difference or an unusable dump is a BROKEN CONTROL and the exit is EXIT_CONTROL."""
    red = EXIT_CONTROL if control else 1
    label = "BROKEN CONTROL (the same engine dumped twice differs: the dump is not repeatable, nothing measured with it can be read)" if control else "RED"
    dumps = []
    for path in (path_a, path_b):
        try:
            dump = json.loads(Path(path).read_text(encoding="utf-8"))
            problems = dump_problems(dump)
        except (OSError, ValueError) as exc:
            problems, dump = ["unreadable: %s" % exc], None
        if problems:
            print("%s prefs-compare: %s is not usable: %s" % (label, Path(path).name, "; ".join(problems[:10])))
            return red
        dumps.append(dump)
    diff = prefs_diff(*dumps)
    result = {"a": str(path_a), "b": str(path_b), "control": control, "verdict": "red" if diff else "green", "differences": diff,
              "count": {branch: len(dumps[0][branch]) for branch in PREFS_BRANCHES}}
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        write_lf(Path(out), json.dumps(result, sort_keys=True, indent=1, ensure_ascii=True) + "\n")
    unreadable = sorted(n for dump in dumps for branch in PREFS_BRANCHES for n, e in dump[branch].items() if e["type"] in ("invalid", "error"))
    if unreadable:
        print("prefs-compare: %d prefs the dump could not read as a string, int or bool: %s" % (len(unreadable), unreadable[:20]))
    if not diff:
        print("prefs-compare: %s and %s have no difference (%d default, %d user prefs)" % (Path(path_a).name, Path(path_b).name, len(dumps[0]["default"]), len(dumps[0]["user"])))
        return 0
    print("%s prefs-compare: %d differences between %s (a) and %s (b)" % (label, len(diff), Path(path_a).name, Path(path_b).name))
    for item in diff:
        if item["kind"] == "changed":
            print("  %s %s: a=%s b=%s" % (item["branch"], item["name"], _show(item["a"]), _show(item["b"])))
        elif item["kind"] == "missing":
            print("  %s %s: only in a: %s" % (item["branch"], item["name"], _show(item["a"])))
        else:
            print("  %s %s: only in b: %s" % (item["branch"], item["name"], _show(item["b"])))
    return red


def prefs_summary(directory: Path, title: str) -> int:
    """Markdown for the job's summary: the verdict of the control and of the comparison, and every difference (the first 200 of each)."""
    print("### %s" % title)
    for name in ("control-diff.json", "diff.json"):
        path = Path(directory) / name
        if not path.is_file():
            print("- %s: not produced" % name)
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        print("- %s: %s, %d differences (%d default prefs)" % (name, data["verdict"], len(data["differences"]), data["count"]["default"]))
        for item in data["differences"][:200]:
            print("  - `%s %s` %s: a=`%s` b=`%s`" % (item["branch"], item["name"], item["kind"], json.dumps(item["a"]), json.dumps(item["b"])))
    return 0


# ----------------------------------------------------------------------------------------------------------------------------------------------
# the manifest of a folder, and the files the command needs
# ----------------------------------------------------------------------------------------------------------------------------------------------
def manifest_entry(manifest_text: str, name: str) -> dict:
    """The keys of a test of an xpcshell.toml: [DEFAULT] and the section of the test, the section over the default. A test that has no section of its
    own (the tag's manifest does not know ours) has the defaults of its folder, as it does in the tree."""
    data = tomllib.loads(manifest_text)
    entry = dict(data.get("DEFAULT", {}))
    entry.update(data.get(name, {}))
    return entry


def our_manifest_entry(source: Path, name: str):
    """The entry of `name` in an `xpcshell*.toml` of OURS beside the test in the series (xpcshell-stealth.toml: a feature's own manifest, registered by its
    moz.build), as manifest_entry reads it; None when none of ours lists the test (then the folder's manifest is Mozilla's, from the lock)."""
    for manifest in sorted(Path(source).parent.glob("xpcshell*.toml")):
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        if name in data:
            entry = dict(data.get("DEFAULT", {}))
            entry.update(data[name])
            return entry
    return None


def head_files(entry: dict) -> list:
    value = entry.get("head", "")
    return [f for f in (value.split() if isinstance(value, str) else list(value)) if f]


def prefs_lines(entry: dict) -> list:
    """`prefs = ["a=1", "b=true", "c=text"]` of a manifest as user_pref lines (mozprefs' cast: bool, int, else a string)."""
    out = []
    for item in entry.get("prefs", []) or []:
        key, _, value = item.partition("=")
        key, value = key.strip(), value.strip()
        if value in ("true", "false"):
            literal = value
        elif re.fullmatch(r"-?\d+", value):
            literal = value
        else:
            literal = json.dumps(value.strip("'\"") if value[:1] in "'\"" and value[-1:] == value[:1] else value)
        out.append('user_pref(%s, %s);' % (json.dumps(key), literal))
    return out


def base_prefs(support: Path) -> str:
    """testing/profiles/<each profile of "xpcshell" in profiles.json>/user.js, interpolated as the runner does (`%(server)s` is `dummyserver`)."""
    profiles = json.loads((support / PROFILES_DIR / "profiles.json").read_text(encoding="utf-8"))[PROFILE_NAME]
    text = ""
    for name in profiles:
        text += (support / PROFILES_DIR / name / "user.js").read_text(encoding="utf-8").replace("%(server)s", "dummyserver") + "\n"
    return text


def build_modules_dir(support: Path, target: Path) -> Path:
    """What the build calls `_tests/modules`: testing/modules/* and the other TESTING_JS_MODULES that head.js and the tests import, in one folder."""
    target.mkdir(parents=True, exist_ok=True)
    for source in sorted((support / MODULES_DIR).iterdir()):
        if source.is_file() and source.name not in MODULES_SKIP:
            shutil.copyfile(source, target / source.name)
    for rel in MODULES_EXTRA:
        shutil.copyfile(support / rel, target / Path(rel).name)
    return target


def js_native(path) -> str:
    """A path that the shell hands to an nsIFile: native separators, backslashes doubled inside the JS string (the runner's replace)."""
    return str(path).replace("\\", "\\\\")


def js_forward(path) -> str:
    """A path that the shell hands to load(): forward slashes."""
    return str(path).replace("\\", "/")


def build_command(binary, xre: Path, app: Path, head_js: Path, mozinfo: Path, prefs: Path, modules: Path, heads: list, test_file: Path, test_name: str) -> list:
    """runxpcshelltests.py buildXpcsCmd + buildCmdHead + buildCmdTestFile + the run arguments, in the order the runner has them. `-xpcshell` is the
    package's own switch (the runner says `--xpcshell`; nsBrowserApp.cpp's IsFlag takes both)."""
    exe = list(binary) if isinstance(binary, (list, tuple)) else [str(binary)]
    return exe + [
        "-xpcshell",
        "-g", str(xre),
        "-a", str(app),
        "-m",
        "-e", 'const _HEAD_JS_PATH = "%s";' % js_forward(head_js),
        "-e", 'const _MOZINFO_JS_PATH = "%s";' % js_native(mozinfo),
        "-e", 'const _PREFS_FILE = "%s";' % js_native(prefs),
        "-e", 'const _TESTING_MODULES_DIR = "%s";' % js_native(modules),
        "-f", str(head_js),
        "-e", "const _HEAD_FILES = [%s];" % ", ".join('"%s"' % js_forward(h) for h in heads),
        "-e", "const _JSDEBUGGER_PORT = 0;",
        "-e", 'const _TEST_FILE = ["%s"];' % js_forward(test_file),
        "-e", 'const _TEST_NAME = "%s";' % test_name,
        "-e", 'const _EXPECTED = "pass";',
        "-e", "_execute_test(); quit(0);",
    ]


def environment(xre: Path, root: Path, base: dict | None = None) -> dict:
    """buildCoreEnvironment + buildEnvironment + setupTempDir + setupProfileDir of the runner: the content sandbox off (the tests bind sockets), no
    connection outside the machine, one profile and one temp folder per run, the library path of the package."""
    env = dict(os.environ if base is None else base)
    env["XPCOM_DEBUG_BREAK"] = "stack-and-abort"
    env["MOZ_CRASHREPORTER"] = "1"
    env["MOZ_CRASHREPORTER_NO_REPORT"] = "1"
    env["MOZ_DISABLE_NONLOCAL_CONNECTIONS"] = "1"
    env["MOZ_DISABLE_CONTENT_SANDBOX"] = "1"
    env["MOZ_DISABLE_SOCKET_PROCESS"] = "1"
    profile, temp = root / "profile", root / "temp"
    appdata = temp / "moz-appdata"
    for d in (profile, temp, appdata):
        d.mkdir(parents=True, exist_ok=True)
    env["XPCSHELL_TEST_PROFILE_DIR"] = str(profile)
    env["XPCSHELL_TEST_TEMP_DIR"] = str(temp)
    env["MOZ_APP_DATA"] = str(appdata / "AppData" / "Roaming")
    env["MOZ_LOCAL_APP_DATA"] = str(appdata / "Local")
    if os.name == "nt":
        env["PATH"] = env.get("PATH", "") + ";" + str(xre)
    else:
        env["LD_LIBRARY_PATH"] = str(xre) + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
    return env


def mozinfo_text() -> str:
    """The few keys of mozinfo.json that a test of ours could read (os, bits, processor, debug...); head.js loads it only when a test asks for `mozinfo`."""
    return json.dumps({"os": "win" if os.name == "nt" else "linux", "bits": 64, "processor": "x86_64", "debug": False, "appname": "firefox",
                       "xpcshell": True, "headless": False, "e10s": True, "toolkit": "windows" if os.name == "nt" else "gtk"})


# ----------------------------------------------------------------------------------------------------------------------------------------------
# the structured log of head.js
# ----------------------------------------------------------------------------------------------------------------------------------------------
STARTING = re.compile(r"\| Starting (setup )?(.*)$")


def parse_log(text: str) -> dict:
    """The tests of one file from the JSON lines head.js prints (StructuredLog.sys.mjs).

    A test is an add_task / add_test (named by its function: «<file> | Starting <name>»); the add_setup ones are not tests but a failure in them
    fails the file. A file without any (run_test()) has one test, `run_test`. A status with an `expected` field is an unexpected one (the logger
    writes it only when the status differs), a SKIP is not a pass, and a log line at ERROR or CRITICAL is a failure that belongs to the file."""
    started, orphans, errors, task_errors = [], [], [], {}
    statuses: dict = {}
    first_time = last_time = None
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or "action" not in event:
            continue
        when = event.get("time")
        if isinstance(when, (int, float)):
            first_time = when if first_time is None else first_time
            last_time = when
        action = event["action"]
        if action == "log":
            level = str(event.get("level", "")).upper()
            match = STARTING.search(str(event.get("message", "")))
            if match and level == "INFO":
                started.append({"name": match.group(2), "setup": bool(match.group(1)), "time": when})
            elif level in ("ERROR", "CRITICAL"):
                errors.append(str(event.get("message", ""))[:300])
                if started:  # an exception that escapes a task is logged at ERROR, with no failed status: it belongs to the task that was running
                    task_errors.setdefault(len(started) - 1, []).append(str(event.get("message", ""))[:300])
        elif action == "test_status":
            statuses.setdefault(event.get("subtest") or "", []).append(event)
    names = {t["name"] for t in started}
    tests, seen = [], {}
    for i, task in enumerate(started):
        nxt = started[i + 1]["time"] if i + 1 < len(started) else last_time
        seconds = round((nxt - task["time"]) / 1000.0, 3) if isinstance(nxt, (int, float)) and isinstance(task["time"], (int, float)) else None
        seen[task["name"]] = seen.get(task["name"], 0) + 1
        name = task["name"] or "<anonymous %d>" % (i + 1)
        if seen[task["name"]] > 1:
            name += "#%d" % seen[task["name"]]
        tests.append({"name": name, "key": task["name"], "setup": task["setup"], "seconds": seconds, "errors": task_errors.get(i, [])})
    orphans = [s for s in statuses if s and s not in names]
    if not any(not t["setup"] for t in tests):
        # run_test(): the statuses are named by the function the assertion is in; one test for all of them
        every = [e for events in statuses.values() for e in events]
        if every:
            seconds = round((last_time - first_time) / 1000.0, 3) if first_time is not None and last_time is not None else None
            tests = [t for t in tests if t["setup"]] + [{"name": "run_test", "key": "run_test", "setup": False, "seconds": seconds, "errors": list(errors)}]
            statuses = dict(statuses, run_test=every)
            orphans = []
    for test in tests:
        events = statuses.get(test["key"], [])
        bad = [e for e in events if "expected" in e and e.get("status") != "SKIP"]
        skipped = [e for e in events if e.get("status") == "SKIP"]
        test["asserts"] = len(events)
        if bad:
            test["status"], test["message"] = "FAIL", str(bad[0].get("message", bad[0].get("status")))[:300]
        elif skipped:
            test["status"], test["message"] = "SKIP", str(skipped[0].get("message", "skipped"))[:300]
        elif test.get("errors"):
            test["status"], test["message"] = "FAIL", test["errors"][0]
        else:
            test["status"], test["message"] = "PASS", ""
    for subtest in orphans:
        bad = [e for e in statuses[subtest] if "expected" in e]
        if bad:
            errors.append("%s: %s" % (subtest, str(bad[0].get("message", bad[0].get("status")))[:300]))
    return {"tests": tests, "errors": errors}


# ----------------------------------------------------------------------------------------------------------------------------------------------
# run
# ----------------------------------------------------------------------------------------------------------------------------------------------
def kill_tree(proc) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        else:
            import signal
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


def run_command(command: list, env: dict, cwd: Path, timeout: float):
    """(return code, output, seconds, timed out). The whole tree is killed at the timeout."""
    kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    started = time.monotonic()
    proc = subprocess.Popen(command, env=env, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs)
    timed_out = False
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        kill_tree(proc)
        out, _ = proc.communicate()
    return proc.returncode, (out or b"").decode("utf-8", errors="replace"), time.monotonic() - started, timed_out


def run_file(binary, series: Path, support: Path, work: Path, modules: Path, rel: str, timeout: float, logs: Path, base_env: dict | None = None) -> dict:
    """One declared file: stage it, run it, judge it. Never raises for a problem of the file: the problem is the file's red."""
    result = {"path": rel, "rc": None, "seconds": 0.0, "timed_out": False, "tests": [], "errors": [], "collected": 0, "passed": 0, "failed": 0, "ok": False}
    try:
        source = locate_test(series, rel)
        folder = Path(rel).parent.as_posix()
        name = Path(rel).name
        # The manifest that lists the test: one of ours beside it in the series (xpcshell-stealth.toml), else Mozilla's xpcshell.toml of the folder (the lock).
        entry = our_manifest_entry(source, name)
        if entry is None:
            manifest = support / folder / "xpcshell.toml"
            if not manifest.is_file():
                raise FileNotFoundError("%s/xpcshell.toml is not in the support folder: the lock lacks it (run `lock`)" % folder)
            entry = manifest_entry(manifest.read_text(encoding="utf-8"), name)
        run_dir = work / hashlib.sha256(rel.encode()).hexdigest()[:8]  # short: Windows paths, and Firefox makes its own folders under it
        stage = run_dir / "stage"
        stage.mkdir(parents=True, exist_ok=True)
        heads = []
        for head in head_files(entry):
            # a head file of ours is beside the test in the series; Mozilla's is in the support folder
            origin = source.parent / head
            if not origin.is_file():
                origin = support / folder / head
            if not origin.is_file():
                raise FileNotFoundError("head file %s/%s of the manifest is in neither the series nor the support folder: the lock lacks it (run `lock`)" % (folder, head))
            shutil.copyfile(origin, stage / head)
            heads.append(stage / head)
        shutil.copyfile(source, stage / name)
        prefs = run_dir / "user.js"
        write_lf(prefs, base_prefs(support) + "\n".join(prefs_lines(entry)) + "\n")
        mozinfo = run_dir / "mozinfo.json"
        write_lf(mozinfo, mozinfo_text())
        xre = Path(binary[-1] if isinstance(binary, (list, tuple)) else binary).resolve().parent
        appdir = entry.get("firefox-appdir")
        app = (xre / appdir) if appdir else xre
        command = build_command(binary, xre, app, support / HARNESS, mozinfo, prefs, modules, heads, stage / name, rel)
        env = environment(xre, run_dir, base_env)
        for item in entry.get("environment", []) or []:
            key, _, value = item.partition("=")
            env[key] = value
        rc, output, seconds, timed_out = run_command(command, env, stage, timeout)
    except Exception as exc:  # noqa: BLE001 - the file's red, with its reason
        result["errors"].append("%s: %s" % (type(exc).__name__, exc))
        return result
    logs.mkdir(parents=True, exist_ok=True)
    write_lf(logs / (re.sub(r"[^A-Za-z0-9_.-]", "_", rel) + ".log"), output)
    parsed = parse_log(output)
    tests = [t for t in parsed["tests"] if not t["setup"]]
    result.update(rc=rc, seconds=round(seconds, 3), timed_out=timed_out, tests=tests, errors=list(parsed["errors"]), collected=len(tests))
    result["passed"] = sum(t["status"] == "PASS" for t in tests)
    result["failed"] = len(tests) - result["passed"]
    for setup in (t for t in parsed["tests"] if t["setup"] and t["status"] != "PASS"):
        result["errors"].append("setup %s: %s" % (setup["name"], setup["message"] or setup["status"]))
    if timed_out:
        result["errors"].append("timed out after %d s" % timeout)
    elif rc != 0:
        result["errors"].append("exit code %s" % rc)
    declared = len(re.findall(r"^\s*add_task\(", source.read_text(encoding="utf-8", errors="replace"), re.M))
    result["declared_tasks"] = declared
    if tests and declared > len(tests) and not (len(tests) == 1 and tests[0]["name"] == "run_test"):
        # a failed assertion aborts the process (head.js _abort_failed_test): the tasks after it are never started, and counting only the started ones would hide them
        result["errors"].append("%d of the %d add_task of the file were never started (the run stopped at a failure)" % (declared - len(tests), declared))
    if not tests:
        result["errors"].append("no test collected (nothing was started or asserted)")
    result["ok"] = rc == 0 and not timed_out and not result["errors"] and result["failed"] == 0 and result["collected"] > 0
    if not result["ok"] and output:
        result["tail"] = output.splitlines()[-PER_FILE_ERROR_LINES:]
    return result


def verdict(files: list, minimum: int) -> dict:
    collected = sum(f["collected"] for f in files)
    reasons = []
    for f in files:
        if not f["ok"]:
            why = "; ".join(f["errors"][:3]) or ", ".join("%s %s" % (t["name"], t["status"]) for t in f["tests"] if t["status"] != "PASS")
            reasons.append("%s: %s" % (f["path"], why or "not ok"))
    if collected < minimum:
        reasons.append("collected %d tests, the declared minimum is %d" % (collected, minimum))
    return {"collected": collected, "passed": sum(f["passed"] for f in files), "failed": sum(f["failed"] for f in files),
            "min_tests": minimum, "files": files, "reasons": reasons, "verdict": "red" if reasons else "green"}


def junit_suite(f: dict, system: str) -> list:
    """The lines of the <testsuite> of one test file: a testcase per test (classname = the path of the file in the tree, name = the test's, the
    function of the add_task), and a testcase `(file)` when the file as a whole failed (an error, a timeout, a process that died)."""
    lines = []
    bad = sum(t["status"] == "FAIL" for t in f["tests"]) + (1 if f["errors"] else 0)
    skipped = sum(t["status"] == "SKIP" for t in f["tests"])
    lines.append("  <testsuite name=%s tests=\"%d\" failures=\"%d\" skipped=\"%d\" time=\"%s\">"
                 % (quoteattr("xpcshell.%s:%s" % (system, f["path"])), len(f["tests"]) + (1 if f["errors"] else 0), bad, skipped, f["seconds"]))
    for t in f["tests"]:
        lines.append("    <testcase classname=%s name=%s time=\"%s\">" % (quoteattr(f["path"]), quoteattr(t["name"]), t.get("seconds") or 0))
        if t["status"] == "FAIL":
            lines.append("      <failure message=%s/>" % quoteattr(t["message"]))
        elif t["status"] == "SKIP":
            lines.append("      <skipped message=%s/>" % quoteattr(t["message"]))
        lines.append("    </testcase>")
    if f["errors"]:
        lines.append("    <testcase classname=%s name=\"(file)\" time=\"0\">" % quoteattr(f["path"]))
        lines.append("      <failure message=%s/>" % quoteattr("; ".join(f["errors"])[:1000]))
        lines.append("    </testcase>")
    lines.append("  </testsuite>")
    return lines


def junit(result: dict, system: str) -> str:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<testsuites>"]
    for f in result["files"]:
        lines += junit_suite(f, system)
    lines.append("</testsuites>")
    return "\n".join(lines) + "\n"


def write_junit_files(result: dict, system: str, directory: Path) -> list:
    """One junit per xpcshell test file, at `<directory>/<path of the file in the tree>.xml`: the package of the named hook tests judge
    (`junit-xpcshell`, scripts/ci/hook_tests_judge.py) reads which file a test is in from the classname, and one file per test file keeps a file that
    reported nothing from hiding behind the others. Returns the paths written."""
    written = []
    for f in result["files"]:
        target = Path(directory) / (f["path"] + ".xml")
        target.parent.mkdir(parents=True, exist_ok=True)
        write_lf(target, junit({"files": [f]}, system))
        written.append(target)
    return written


def summary_table(result: dict) -> str:
    rows = ["| file | tests | passed | seconds | result |", "|---|---|---|---|---|"]
    for f in result["files"]:
        rows.append("| %s | %d | %d | %s | %s |" % (f["path"], f["collected"], f["passed"], f["seconds"], "ok" if f["ok"] else "RED"))
        for t in f["tests"]:
            rows.append("| &nbsp;&nbsp;%s | | | %s | %s |" % (t["name"], t.get("seconds"), t["status"]))
    return "\n".join(rows) + "\n"


def run(binary, series: Path, support: Path, list_path: Path, lock_path: Path, out: Path, timeout: float = TIMEOUT_S, only: str = "") -> int:
    declared = load_list(list_path)
    lock = load_lock(lock_path)
    check_lock_matches_upstream(lock, upstream(series))
    if not isinstance(binary, (list, tuple)):
        binary = str(Path(binary).resolve())  # the working directory of every run is its own folder: the binary is named once, absolutely
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    system = "windows" if os.name == "nt" else "linux"
    missing = [rel for rel, want in lock["files"].items() if not (support / rel).is_file() or sha256_of(support / rel) != want]
    if missing:
        result = {"verdict": "red", "files": [], "collected": 0, "passed": 0, "failed": 0, "min_tests": declared["min_tests"],
                  "reasons": ["the support folder differs from the lock (missing or other bytes): %s" % ", ".join(sorted(missing)[:8])]}
    else:
        work = Path(tempfile.mkdtemp(prefix="xpc-"))
        try:
            modules = build_modules_dir(support, work / "modules")
            files = [run_file(binary, series, support, work, modules, rel, timeout, out / "logs") for rel in declared["files"] if not only or only in rel]
            result = verdict(files, declared["min_tests"])
        finally:
            shutil.rmtree(work, ignore_errors=True)
    # the list against the series: a test of ours the list does not run, or a listed file the series does not have, is red whatever else ran
    problems = check_list(series, declared["files"])
    if problems:
        result["reasons"] = list(result["reasons"]) + problems
        result["verdict"] = "red"
    result.update(system=system, mozilla_tag=lock["mozilla_tag"], seconds=round(sum(f["seconds"] for f in result["files"]), 3))
    write_lf(out / "xpcshell-result.json", json.dumps(result, indent=1) + "\n")
    write_lf(out / "xpcshell-junit.xml", junit(result, system))
    write_junit_files(result, system, out / "junit-xpcshell")
    table = summary_table(result)
    write_lf(out / "xpcshell-summary.md", table)
    print(table)
    print("xpcshell %s: %d collected, %d passed, %d failed, minimum %d, %.1f s: %s"
          % (system, result["collected"], result["passed"], result["failed"], result["min_tests"], result["seconds"], result["verdict"].upper()))
    for reason in result["reasons"]:
        print("RED " + reason)
    return 0 if result["verdict"] == "green" else 1


# ----------------------------------------------------------------------------------------------------------------------------------------------
# lock
# ----------------------------------------------------------------------------------------------------------------------------------------------
def _git(repo: str, *args: str) -> bytes:
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True).stdout


def lock_files(repo: str, tag: str, items: list) -> dict:
    """{path: sha256} of the blobs of `tag` that the declared tests need. `items` is [(folder, name, our_entry, our_dir)] per declared test: with an entry of
    ours (a manifest of ours lists it) the heads come from that entry, and a head that sits in our_dir (the series) is ours and is not locked; without one the
    folder's xpcshell.toml of the tag is read and locked, with the heads of the test's entry."""
    def blob(path: str) -> bytes:
        return _git(repo, "cat-file", "blob", "%s:%s" % (tag, path))

    wanted = [HARNESS, *MODULES_EXTRA, PROFILES_DIR + "/profiles.json"]
    listing = _git(repo, "ls-tree", "--name-only", "%s:%s" % (tag, MODULES_DIR)).decode().split()
    wanted += [MODULES_DIR + "/" + n for n in listing if n not in MODULES_SKIP and _git(repo, "cat-file", "-t", "%s:%s/%s" % (tag, MODULES_DIR, n)).strip() == b"blob"]
    for name in json.loads(blob(PROFILES_DIR + "/profiles.json"))[PROFILE_NAME]:
        wanted.append("%s/%s/user.js" % (PROFILES_DIR, name))
    for folder, name, ours, our_dir in items:
        if ours is None:
            manifest = folder + "/xpcshell.toml"
            wanted.append(manifest)
            entry = manifest_entry(blob(manifest).decode("utf-8"), name)
            wanted += ["%s/%s" % (folder, h) for h in head_files(entry)]
        else:
            wanted += ["%s/%s" % (folder, h) for h in head_files(ours) if not (our_dir and (Path(our_dir) / h).is_file())]
    return {path: hashlib.sha256(blob(path)).hexdigest() for path in sorted(set(wanted))}


def lock_cmd(repo: str, series: Path, list_path: Path, out: Path) -> int:
    declared = load_list(list_path)
    tag = upstream(series)["mozilla_tag"]
    items = []
    for rel in declared["files"]:
        source = locate_test(series, rel)
        items.append((Path(rel).parent.as_posix(), Path(rel).name, our_manifest_entry(source, Path(rel).name), source.parent))
    files = lock_files(repo, tag, items)
    write_lf(Path(out), json.dumps({"mozilla_tag": tag, "files": files}, indent=1) + "\n")
    print("lock: %d files at %s -> %s" % (len(files), tag, out))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--series", required=True, type=Path)
    f.add_argument("--lock", type=Path, default=LOCK)
    f.add_argument("--into", required=True, type=Path)
    r = sub.add_parser("run")
    r.add_argument("--binary", required=True)
    r.add_argument("--series", required=True, type=Path)
    r.add_argument("--support", required=True, type=Path)
    r.add_argument("--list", type=Path, default=LIST)
    r.add_argument("--lock", type=Path, default=LOCK)
    r.add_argument("--out", required=True, type=Path)
    r.add_argument("--timeout", type=float, default=TIMEOUT_S)
    r.add_argument("--only", default="", help="run only the declared files whose path contains this text (a measurement aid; the verdict then lacks the others)")
    c = sub.add_parser("check")
    c.add_argument("--series", required=True, type=Path)
    c.add_argument("--list", type=Path, default=LIST)
    v = sub.add_parser("verify-asset")
    v.add_argument("--dir", required=True, type=Path)
    v.add_argument("--leg", required=True)
    pd = sub.add_parser("prefs")
    pd.add_argument("--binary", required=True)
    pd.add_argument("--out", required=True, type=Path)
    pd.add_argument("--root", type=Path, default=None, help="the folder of the fresh profile (emptied first); the same for every dump that is compared")
    pd.add_argument("--timeout", type=float, default=TIMEOUT_S)
    pc = sub.add_parser("prefs-compare")
    pc.add_argument("a", type=Path)
    pc.add_argument("b", type=Path)
    pc.add_argument("--out", type=Path, default=None)
    pc.add_argument("--control", action="store_true", help="a and b are one engine dumped twice: a difference is a broken control (exit 2)")
    ps = sub.add_parser("prefs-summary")
    ps.add_argument("dir", type=Path)
    ps.add_argument("--title", default="prefs")
    k = sub.add_parser("lock")
    k.add_argument("--git", required=True, help="a git repository that has the Mozilla tag of the series' UPSTREAM.json")
    k.add_argument("--series", required=True, type=Path)
    k.add_argument("--list", type=Path, default=LIST)
    k.add_argument("--out", type=Path, default=LOCK)
    args = parser.parse_args(argv)
    if args.cmd == "fetch":
        return fetch(args.series, args.lock, args.into)
    if args.cmd == "check":
        return check_cmd(args.series, args.list)
    if args.cmd == "verify-asset":
        return verify_asset(args.dir, args.leg)
    if args.cmd == "prefs":
        return prefs_dump(args.binary, args.out, args.root, args.timeout)
    if args.cmd == "prefs-compare":
        return prefs_compare(args.a, args.b, args.out, args.control)
    if args.cmd == "prefs-summary":
        return prefs_summary(args.dir, args.title)
    if args.cmd == "lock":
        return lock_cmd(args.git, args.series, args.list, args.out)
    return run(args.binary, args.series, args.support.resolve(), args.list, args.lock, args.out, args.timeout, args.only)


if __name__ == "__main__":
    sys.exit(main())
