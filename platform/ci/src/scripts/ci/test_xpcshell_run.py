#!/usr/bin/env python3
"""scripts/ci/xpcshell_run.py against the cases it exists for, with a fake binary that prints what head.js prints.

The leg (xpcshell.yml) runs our xpcshell tests on the candidate's `firefox -xpcshell`. A leg that cannot turn red is not a gate, so these cases are the red ones
first: a failing test, a test that was skipped, a process that exits non-zero with every assertion green, a log line at ERROR, a hang, a file that collects
nothing, fewer tests than the declared minimum, a support file whose bytes are not the locked ones, a lock for another tag. Then the green one, and the command
line, the environment and the profile the shell is given, which the fake binary checks as the real one would depend on them.

    python3 scripts/ci/test_xpcshell_run.py
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import xpcshell_run as x  # noqa: E402

FAKE = r'''
import json, os, re, sys, time
args = sys.argv[1:]
problems = []
def need(ok, what):
    if not ok:
        problems.append(what)
need(args[:1] == ["-xpcshell"], "first argument is -xpcshell")
need(args[1] == "-g" and os.path.isdir(args[2]), "-g <gre dir>")
need(args[3] == "-a", "-a <app dir>")
need(args[5] == "-m", "-m")
evals = {}
for i, a in enumerate(args):
    if a == "-e":
        m = re.match(r"const (\w+) = (.*);$", args[i + 1], re.S)
        if m:
            evals[m.group(1)] = json.loads(m.group(2))  # a JS string with doubled backslashes is a JSON string
need(args[-2:] == ["-e", "_execute_test(); quit(0);"], "ends with the run argument")
f = args.index("-f")
need(os.path.basename(args[f + 1]) == "head.js", "-f head.js")
for key in ("_HEAD_JS_PATH", "_MOZINFO_JS_PATH", "_PREFS_FILE", "_TESTING_MODULES_DIR", "_HEAD_FILES", "_JSDEBUGGER_PORT", "_TEST_FILE", "_TEST_NAME", "_EXPECTED"):
    need(key in evals, "const " + key)
need(os.path.isfile(args[f + 1]), "head.js exists")
prefs = evals.get("_PREFS_FILE", "")
need(os.path.isfile(prefs), "the prefs file exists")
need(os.path.isdir(evals.get("_TESTING_MODULES_DIR", "")), "the modules folder exists")
need(os.path.isfile(os.path.join(evals.get("_TESTING_MODULES_DIR", ""), "httpd.sys.mjs")), "httpd.sys.mjs is in the modules folder")
for h in evals.get("_HEAD_FILES", []):
    need(os.path.isfile(h), "head file " + h)
need(os.environ.get("MOZ_DISABLE_NONLOCAL_CONNECTIONS") == "1", "MOZ_DISABLE_NONLOCAL_CONNECTIONS=1")
need(os.path.isdir(os.environ.get("XPCSHELL_TEST_PROFILE_DIR", "")), "XPCSHELL_TEST_PROFILE_DIR")
need(bool(os.environ.get("XPCSHELL_TEST_TEMP_DIR")), "XPCSHELL_TEST_TEMP_DIR")
need(os.path.normcase(os.path.normpath(os.path.dirname(evals.get("_TEST_FILE", [""])[0]))) == os.path.normcase(os.path.normpath(os.getcwd())), "the working directory is the test's folder")
cap = os.environ.get("FAKE_CAPTURE")
if cap:
    with open(cap, "w", encoding="utf-8") as h:
        json.dump({"args": args, "evals": evals, "prefs": open(prefs, encoding="utf-8").read() if os.path.isfile(prefs) else "",
                   "env": {k: os.environ.get(k) for k in ("MOZ_DISABLE_NONLOCAL_CONNECTIONS", "MOZ_DISABLE_CONTENT_SANDBOX", "XPCSHELL_TEST_PROFILE_DIR", "EXTRA_FROM_MANIFEST")},
                   "problems": problems}, h)
if problems:
    print("FAKE BINARY: the command is not the runner's: " + "; ".join(problems))
    sys.exit(3)
name = evals["_TEST_NAME"]
clock = [1700000000000]
def out(**kw):
    clock[0] += 250
    kw.setdefault("time", clock[0])
    print(json.dumps(kw), flush=True)
def status(sub, st, msg=""):
    kw = dict(action="test_status", test=name, subtest=sub, status=st, message=msg)
    if st != "PASS":
        kw["expected"] = "PASS" if st == "FAIL" else "PASS"
    if st == "SKIP":
        kw.pop("expected")
    out(**kw)
code = 0
for line in open(evals["_TEST_FILE"][0], encoding="utf-8").read().splitlines():
    w = line.split()
    if not w:
        continue
    if w[0] in ("task", "setup"):
        out(action="log", level="INFO", message="%s | Starting %s%s" % (name, "setup " if w[0] == "setup" else "", w[1]))
        status(w[1], w[2], "[%s : 1] %s" % (w[1], w[2]))
    elif w[0] == "runtest":
        status("run_test", w[1], "[run_test : 1] an assertion")
        status("run_test", "PASS", "[run_test : 2] another")
    elif w[0] == "error":
        out(action="log", level="ERROR", message=" ".join(w[1:]))
    elif w[0] == "exit":
        code = int(w[1])
    elif w[0] == "hang":
        time.sleep(60)
sys.exit(code)
'''

PREFS_FAKE = r'''
import os, sys, time
a = sys.argv[1:]
problems = []
def need(ok, what):
    if not ok:
        problems.append(what)
need(a[:1] == ["-xpcshell"], "first argument is -xpcshell")
need(a[1:2] == ["-g"] and os.path.isdir(a[2]), "-g <gre dir>")
need(a[3:4] == ["-a"] and a[4] == os.path.join(a[2], "browser"), "-a <gre>/browser")
need(a[5:6] == ["-f"] and os.path.basename(a[6]) == "prefs_dump.js" and os.path.isfile(a[6]), "-f prefs_dump.js")
need(a[7:] == ["-e", "quit(0);"], "ends with -e quit(0);")
prof = os.environ.get("XPCSHELL_TEST_PROFILE_DIR", "")
need(os.path.isdir(prof) and os.listdir(prof) == [], "a fresh, empty profile folder")
out = os.environ.get("PREFS_DUMP_OUT", "")
need(bool(out) and os.path.isabs(out), "PREFS_DUMP_OUT, absolute")
need(os.path.samefile(os.path.dirname(out), os.getcwd()), "the working directory is the dump root")
need(os.environ.get("MOZ_DISABLE_NONLOCAL_CONNECTIONS") == "1", "MOZ_DISABLE_NONLOCAL_CONNECTIONS=1")
need(os.path.isdir(os.environ.get("XPCSHELL_TEST_TEMP_DIR", "")), "XPCSHELL_TEST_TEMP_DIR")
if problems:
    print("FAKE BINARY: the command is not the dump's: " + "; ".join(problems))
    sys.exit(3)
mode = os.environ.get("FAKE_MODE", "ok")
if mode == "exit":
    sys.exit(1)
if mode == "hang":
    time.sleep(60)
if mode == "none":
    sys.exit(0)
if mode == "jserror":
    print("JavaScript error: prefs_dump.js, line 106: SyntaxError: malformed Unicode character escape sequence")
    sys.exit(0)
with open(out, "w", encoding="utf-8", newline="\n") as h:
    h.write(open(os.environ["FAKE_PREFS"], encoding="utf-8").read())
with open(os.path.join(prof, "prefs.js"), "w") as h:  # what a real run leaves: the next dump must not see it
    h.write("stale")
print("PREFS_DUMP_OK")
'''

TOML = '''[DEFAULT]
head = "head_x.js"
firefox-appdir = "browser"
prefs = ["demo.number=3", "demo.flag=true", "demo.text=hello"]
environment = ["EXTRA_FROM_MANIFEST=yes"]

["test_declared.js"]
'''


class Tree:
    """A series, a support folder, a lock and a list, in a temporary folder, with a fake binary next to which the shell's folders would be."""

    def __init__(self, root: Path, tests: dict, minimum: int = 1, tag: str = "T1", lock_tag: str = "T1"):
        self.root = root
        self.series = root / "series"
        self.support = root / "support"
        self.out = root / "out"
        (self.series / "grp" / "fold" / "src" / "dir" / "unit").mkdir(parents=True)
        (self.series / "UPSTREAM.json").write_text(json.dumps({"mozilla_repository": "https://github.com/mozilla-firefox/firefox", "mozilla_tag": tag}), encoding="utf-8")
        for name, body in tests.items():
            (self.series / "grp" / "fold" / "src" / "dir" / "unit" / name).write_text(body, encoding="utf-8")
        files = {
            "testing/xpcshell/head.js": "// the harness\n",
            "testing/modules/Assert.sys.mjs": "// assert\n",
            "testing/modules/moz.build": "# not a module\n",
            "toolkit/modules/tests/modules/PromiseTestUtils.sys.mjs": "// a\n",
            "tools/code-coverage/PerTestCoverageUtils.sys.mjs": "// b\n",
            "netwerk/test/httpserver/httpd.sys.mjs": "// c\n",
            "testing/profiles/profiles.json": json.dumps({"xpcshell": ["base", "xpcshell"], "mochitest": ["base"]}),
            "testing/profiles/base/user.js": 'user_pref("a.server", "https://%(server)s/x");\n',
            "testing/profiles/xpcshell/user.js": 'user_pref("b.on", true);\n',
            "dir/unit/xpcshell.toml": TOML,
            "dir/unit/head_x.js": "// head\n",
        }
        for rel, text in files.items():
            target = self.support / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        locked = {rel: hashlib.sha256((self.support / rel).read_bytes()).hexdigest() for rel in files if not rel.endswith("moz.build")}
        self.lock = root / "lock.json"
        self.lock.write_text(json.dumps({"mozilla_tag": lock_tag, "files": locked}), encoding="utf-8")
        self.list = root / "list.json"
        self.list.write_text(json.dumps({"files": ["dir/unit/" + n for n in tests], "min_tests": minimum}), encoding="utf-8")
        fake = root / "bin" / "fake_firefox.py"
        fake.parent.mkdir()
        fake.write_text(FAKE, encoding="utf-8")
        self.binary = [sys.executable, str(fake)]

    def run(self, timeout: float = 20, capture: Path | None = None) -> tuple:
        """(exit code, result JSON, the output, the junit text)."""
        if capture:
            os.environ["FAKE_CAPTURE"] = str(capture)
        else:
            os.environ.pop("FAKE_CAPTURE", None)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = x.run(self.binary, self.series, self.support, self.list, self.lock, self.out, timeout)
        os.environ.pop("FAKE_CAPTURE", None)
        return code, json.loads((self.out / "xpcshell-result.json").read_text(encoding="utf-8")), buf.getvalue(), (self.out / "xpcshell-junit.xml").read_text(encoding="utf-8")


def tree(tests, **kw):
    tmp = tempfile.TemporaryDirectory()
    return tmp, Tree(Path(tmp.name), tests, **kw)


DEMO = False
PASSING = "task test_one PASS\ntask test_two PASS\n"


def cases() -> list:
    out = []

    def add(name, ok):
        out.append(("xpcshell: " + name, bool(ok)))

    # --- the green one
    tmp, t = tree({"test_declared.js": PASSING}, minimum=2)
    with tmp:
        code, result, text, junit = t.run()
        add("all tests pass and the minimum is met: green, exit 0, two tests named by their function, junit has two testcases",
            code == 0 and result["verdict"] == "green" and result["collected"] == 2 and result["passed"] == 2
            and [x_["name"] for x_ in result["files"][0]["tests"]] == ["test_one", "test_two"] and len(ET.fromstring(junit).findall(".//testcase")) == 2)
        add("the result says the seconds of each test and of the file", all(isinstance(x_["seconds"], float) for x_ in result["files"][0]["tests"]) and result["files"][0]["seconds"] > 0)

    # --- the red ones
    tmp, t = tree({"test_declared.js": "task test_one PASS\ntask test_two FAIL\n"}, minimum=2)
    with tmp:
        code, result, text, junit = t.run()
        failed = ET.fromstring(junit).findall(".//failure")
        add("a failing test: exit 1, red, the failing test is named, the other still counts as passed, junit has a failure",
            code == 1 and result["verdict"] == "red" and result["files"][0]["tests"][1]["status"] == "FAIL" and result["passed"] == 1 and len(failed) == 1
            and "test_declared.js" in text and "RED" in text)
        if DEMO:
            print("---- the red case, as the leg prints it ----")
            print(text.strip())
            print("---- exit code %d ----" % code)

    tmp, t = tree({"test_declared.js": PASSING}, minimum=3)
    with tmp:
        code, result, text, _ = t.run()
        add("every test passes but fewer were collected than the declared minimum: red, and it says the numbers",
            code == 1 and result["verdict"] == "red" and "collected 2 tests, the declared minimum is 3" in " ".join(result["reasons"]))

    tmp, t = tree({"test_declared.js": "task test_one PASS\ntask test_two SKIP\n"}, minimum=1)
    with tmp:
        code, result, _, _ = t.run()
        add("a skipped test is not a pass: red", code == 1 and result["files"][0]["tests"][1]["status"] == "SKIP")

    tmp, t = tree({"test_declared.js": PASSING + "exit 5\n"}, minimum=1)
    with tmp:
        code, result, _, _ = t.run()
        add("a process that exits non-zero with every assertion green is red (a crash after the last test)", code == 1 and result["files"][0]["rc"] == 5 and result["failed"] == 0)

    tmp, t = tree({"test_declared.js": PASSING + "error an exception that nobody caught\n"}, minimum=1)
    with tmp:
        code, result, _, junit = t.run()
        add("a log line at ERROR is a failure of the file even when every test is green", code == 1 and "an exception that nobody caught" in " ".join(result["files"][0]["errors"]) and "(file)" in junit)

    tmp, t = tree({"test_declared.js": "setup add_setup_thing FAIL\ntask test_one PASS\n"}, minimum=1)
    with tmp:
        code, result, _, _ = t.run()
        add("a failing setup fails the file and is not counted as a test", code == 1 and result["collected"] == 1 and any("setup add_setup_thing" in e for e in result["files"][0]["errors"]))

    tmp, t = tree({"test_declared.js": "task test_one PASS\nhang\n"}, minimum=1)
    with tmp:
        code, result, _, _ = t.run(timeout=2)
        add("a test that hangs is killed at the timeout and is red", code == 1 and result["files"][0]["timed_out"] and any("timed out" in e for e in result["files"][0]["errors"]))

    tmp, t = tree({"test_declared.js": "# nothing runs\n"}, minimum=1)
    with tmp:
        code, result, _, _ = t.run()
        add("a file that collects no test is red, whatever the minimum", code == 1 and result["collected"] == 0 and any("no test collected" in e for e in result["files"][0]["errors"]))

    tmp, t = tree({"test_declared.js": PASSING}, minimum=2)
    with tmp:
        t.list.write_text(json.dumps({"files": ["dir/unit/test_declared.js", "dir/unit/test_missing.js"], "min_tests": 2}), encoding="utf-8")
        code, result, _, _ = t.run()
        add("a declared file that is not in the series is red and says so", code == 1 and any("test_missing.js" in r and "exactly one" in r for r in result["reasons"]))

    tmp, t = tree({"test_declared.js": PASSING}, minimum=2)
    with tmp:
        (t.support / "dir/unit/head_x.js").write_text("// another head\n", encoding="utf-8")
        code, result, _, _ = t.run()
        add("a support file whose bytes are not the locked ones is red before anything runs", code == 1 and not result["files"] and "head_x.js" in " ".join(result["reasons"]))

    tmp, t = tree({"test_declared.js": PASSING}, minimum=2, tag="T2", lock_tag="T1")
    with tmp:
        try:
            t.run()
            ok = False
        except SystemExit as exc:
            ok = "for T1" in str(exc) and "T2" in str(exc)
        add("a lock for another Mozilla tag than the series' is red (a port must run `lock`)", ok)

    tmp, t = tree({"test_declared.js": "task test_one PASS\ntask test_two PASS\nerror Unexpected exception TypeError: NetworkError\n"}, minimum=1)
    with tmp:
        code, result, _, junit = t.run()
        add("an exception that escapes the last task is logged at ERROR with no failed status: that task is FAIL, not 'passed' (run 44944973609: 5/5 passed and red)",
            code == 1 and result["passed"] == 1 and result["failed"] == 1 and result["files"][0]["tests"][1]["status"] == "FAIL"
            and "NetworkError" in result["files"][0]["tests"][1]["message"] and "NetworkError" in junit)

    tmp, t = tree({"test_declared.js": "task test_one FAIL\nadd_task(async function test_one() {\nadd_task(async function test_two() {\n"}, minimum=1)
    with tmp:
        code, result, _, _ = t.run()
        add("a failure that stops the run leaves tasks never started: the file says how many of its add_task were not started (collected 1 of 2 was red without saying why)",
            code == 1 and any("1 of the 2 add_task" in e for e in result["files"][0]["errors"]) and result["files"][0]["declared_tasks"] == 2)

    tmp, t = tree({"test_declared.js": PASSING + "add_task(async function test_one() {\nadd_task(async function test_two() {\n"}, minimum=2)
    with tmp:
        code, result, _, _ = t.run()
        add("a file whose every add_task started has no such error", code == 0 and result["files"][0]["errors"] == [])

    # --- the command, the environment and the profile
    tmp, t = tree({"test_declared.js": PASSING}, minimum=2)
    with tmp:
        cap = Path(tmp.name) / "capture.json"
        code, result, text, _ = t.run(capture=cap)
        seen = json.loads(cap.read_text(encoding="utf-8"))
        a = seen["args"]
        add("the command is the runner's: -xpcshell first, -g and -a, -m, the eight constants, -f head.js, the run argument last (the fake binary exits 3 otherwise)",
            code == 0 and seen["problems"] == [] and a[0] == "-xpcshell" and a[-1] == "_execute_test(); quit(0);")
        add("firefox-appdir of the manifest becomes -a <gre>/browser", a[a.index("-a") + 1].replace("\\", "/").endswith("/bin/browser"))
        add("the head files of the manifest are passed in _HEAD_FILES and staged next to the test", len(seen["evals"]["_HEAD_FILES"]) == 1 and seen["evals"]["_HEAD_FILES"][0].endswith("/head_x.js"))
        add("_TEST_NAME is the path of the test in the tree, as the ids of the runs of the harness", seen["evals"]["_TEST_NAME"] == "dir/unit/test_declared.js")
        add("the environment has no non-local connection, no content sandbox, and a profile folder",
            seen["env"]["MOZ_DISABLE_NONLOCAL_CONNECTIONS"] == "1" and seen["env"]["MOZ_DISABLE_CONTENT_SANDBOX"] == "1" and bool(seen["env"]["XPCSHELL_TEST_PROFILE_DIR"]))
        add("the environment of the manifest is set", seen["env"]["EXTRA_FROM_MANIFEST"] == "yes")
        prefs = seen["prefs"]
        add("the profile has the base prefs interpolated (`%(server)s` is dummyserver), the xpcshell ones and the manifest's, typed",
            'user_pref("a.server", "https://dummyserver/x");' in prefs and 'user_pref("b.on", true);' in prefs and 'user_pref("demo.number", 3);' in prefs
            and 'user_pref("demo.flag", true);' in prefs and 'user_pref("demo.text", "hello");' in prefs and "mochitest" not in prefs)

    # --- the parts
    log = "\n".join(json.dumps(e) for e in [
        {"action": "log", "level": "INFO", "message": "f | Starting setup add_setup", "time": 1000},
        {"action": "test_status", "subtest": "add_setup", "status": "PASS"},
        {"action": "log", "level": "INFO", "message": "f | Starting test_a", "time": 2000},
        {"action": "test_status", "subtest": "test_a", "status": "PASS"},
        {"action": "log", "level": "INFO", "message": "f | Starting test_b", "time": 4000},
        {"action": "test_status", "subtest": "test_b", "status": "FAIL", "expected": "PASS", "message": "boom"},
        {"action": "log", "level": "INFO", "message": "not json lines are ignored", "time": 5000},
    ]) + "\nplain text from the shell\n{broken json\n"
    p = x.parse_log(log)
    add("parse_log: tasks are the tests, setups are marked, an `expected` field is a failure, times give the seconds of each task",
        [(t_["name"], t_["setup"], t_["status"]) for t_ in p["tests"]] == [("add_setup", True, "PASS"), ("test_a", False, "PASS"), ("test_b", False, "FAIL")]
        and p["tests"][1]["seconds"] == 2.0 and p["tests"][2]["message"] == "boom")
    p = x.parse_log(json.dumps({"action": "test_status", "subtest": "run_test", "status": "PASS"}) + "\n" + json.dumps({"action": "test_status", "subtest": "run_test", "status": "PASS"}))
    add("parse_log: a file with run_test() and no task has one test, run_test", [t_["name"] for t_ in p["tests"]] == ["run_test"] and p["tests"][0]["asserts"] == 2)
    p = x.parse_log(json.dumps({"action": "test_status", "subtest": "run_test", "status": "FAIL", "expected": "PASS", "message": "no"}))
    add("parse_log: a failing assertion of a run_test() file fails its one test", p["tests"][0]["status"] == "FAIL")
    add("parse_log: an empty output has no test", x.parse_log("")["tests"] == [])

    # the manifest
    entry = x.manifest_entry(TOML, "test_declared.js")
    other = x.manifest_entry(TOML, "test_not_in_the_manifest.js")
    add("the manifest: a test without a section of its own (the tag's manifest does not know ours) has the defaults of its folder", other == entry and x.head_files(entry) == ["head_x.js"])
    section = x.manifest_entry('[DEFAULT]\nhead = "h.js"\n\n["t.js"]\nhead = "a.js b.js"\nprefs = ["p=1"]\n', "t.js")
    add("the manifest: the section of the test is over the default, `head` may list several files", x.head_files(section) == ["a.js", "b.js"] and x.prefs_lines(section) == ['user_pref("p", 1);'])

    # the declared list and the lock of the repository
    declared = x.load_list(x.LIST)
    lock = x.load_lock(x.LOCK)
    folders = {Path(f).parent.as_posix() for f in declared["files"]}
    add("the declared list has our three xpcshell tests of the line and the minimum is their seven tasks (the launch counter's hook test is a node test now)",
        len(declared["files"]) == 3 and declared["min_tests"] == 7 and all(Path(f).name.startswith("test_stealth_") for f in declared["files"]))
    add("the lock has the harness, the modules and the profiles (the manifests of the folders are held by the lock cases of the two layouts below)",
        x.HARNESS in lock["files"] and all(r in lock["files"] for r in x.MODULES_EXTRA) and "testing/modules/StructuredLog.sys.mjs" in lock["files"]
        and "testing/profiles/xpcshell/user.js" in lock["files"]
        and all(len(h) == 64 and set(h) <= set("0123456789abcdef") for h in lock["files"].values()))
    add("the lock holds blobs of one tag only, no moz.build and no folder", not any(p_.endswith("moz.build") or p_.endswith("/tests") for p_ in lock["files"]))
    raw = x.LOCK.read_bytes() + x.LIST.read_bytes() + (HERE / "xpcshell_run.py").read_bytes()
    add("LF only in the script, the list and the lock", b"\r" not in raw)

    # fetch
    tmp, t = tree({"test_declared.js": PASSING}, minimum=2)
    with tmp:
        asked = []

        class Reply(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def serve(request, timeout=None):
            asked.append(request.full_url)
            rel = request.full_url.split("/T1/", 1)[1]
            return Reply((t.support / rel).read_bytes())

        into = Path(tmp.name) / "fetched"
        with contextlib.redirect_stdout(io.StringIO()):
            code = x.fetch(t.series, t.lock, into, opener=serve, sleep=lambda s: None)
        same = all((into / r).read_bytes() == (t.support / r).read_bytes() for r in json.loads(t.lock.read_text(encoding="utf-8"))["files"])
        add("fetch: every locked file is read from raw.githubusercontent.com at the tag, written, and the exit is 0",
            code == 0 and same and all(u.startswith("https://raw.githubusercontent.com/mozilla-firefox/firefox/T1/") for u in asked) and len(asked) == len(json.loads(t.lock.read_text(encoding="utf-8"))["files"]))

        def tampered(request, timeout=None):
            return Reply(b"not the locked bytes")

        into2 = Path(tmp.name) / "fetched2"
        with contextlib.redirect_stdout(io.StringIO()) as bad_out:
            code = x.fetch(t.series, t.lock, into2, opener=tampered, sleep=lambda s: None)
        add("fetch: bytes that are not the locked ones are refused, not written, and the exit is 1", code == 1 and not list(into2.rglob("*.js")) and "sha256" in bad_out.getvalue())

        def down(request, timeout=None):
            raise OSError("no route")

        with contextlib.redirect_stdout(io.StringIO()):
            code = x.fetch(t.series, t.lock, Path(tmp.name) / "fetched3", opener=down, sleep=lambda s: None)
        add("fetch: a file that cannot be read after the retries is red, not a traceback", code == 1)

    # --- the list is the set: our xpcshell tests that the series holds against the declared list
    def series_with(paths):
        tmp_ = tempfile.TemporaryDirectory()
        base = Path(tmp_.name)
        for rel in paths:
            f = base / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("// x\n", encoding="utf-8")
        return tmp_, base

    def checked(series, list_path):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = x.check_cmd(series, list_path)
        return code, buf.getvalue()

    S = "grp/fold/src/"
    tmp, base = series_with([
        S + "a/tests/unit/test_stealth_one.js", S + "b/test/unit/test_stealth_two.mjs", S + "c/tests/xpcshell/test_three.js", S + "d/unit_ipc/test_four.js",
        S + "e/tests/test_with_a_toml.js", S + "e/tests/xpcshell-stealth.toml",
        # not ours or not xpcshell: a head file, a python test, a module, a node test, a mochitest, a test outside any xpcshell folder, files outside src
        S + "a/tests/unit/head_x.js", S + "a/tests/unit/test_stealth_py.py", S + "a/tests/unit/test_stealth_mod.sys.mjs", S + "juggler/tests/x.test.mjs",
        S + "f/tests/browser/browser_test_x.js", S + "g/tests/mochitest/test_not_xpcshell.js", "grp/fold/FEATURE.md", "grp/fold/hooks.patch",
        "other/test_unit_root.js", "grp/fold/notsrc/unit/test_outside_src.js"])
    with tmp:
        add("discover: test_*.js/.mjs in a unit, xpcshell or unit_* folder of a feature's src, or beside an xpcshell*.toml of ours, and nothing else",
            x.discover(base) == ["a/tests/unit/test_stealth_one.js", "b/test/unit/test_stealth_two.mjs", "c/tests/xpcshell/test_three.js", "d/unit_ipc/test_four.js",
                                 "e/tests/test_with_a_toml.js"])
    tmp, base = series_with([])
    with tmp:
        add("discover: a series with no feature has none", x.discover(base) == [])

    tmp, t = tree({"test_declared.js": PASSING}, minimum=2)
    with tmp:
        code, result, _, _ = t.run()
        add("a list that is the set, and tests that pass: no reason from the check, green", code == 0 and result["reasons"] == [] and checked(t.series, t.list)[0] == 0)

    tmp, t = tree({"test_declared.js": PASSING}, minimum=2)
    with tmp:
        (t.series / "grp" / "fold" / "src" / "dir" / "unit" / "test_new_of_ours.js").write_text("// a new xpcshell test of ours\n", encoding="utf-8")
        code, result, text, _ = t.run()
        add("a test of ours in the series that the list does not run is RED, said by name, even when every listed test passes",
            code == 1 and result["verdict"] == "red" and result["passed"] == 2 and result["failed"] == 0
            and any("dir/unit/test_new_of_ours.js" in r and "declared list does not run" in r for r in result["reasons"]) and "RED dir/unit/test_new_of_ours.js" in text)
        code, said = checked(t.series, t.list)
        add("check: the same test of ours that the list does not run is exit 1, by name", code == 1 and "test_new_of_ours.js" in said and "1 problem" in said)
        t.list.write_text(json.dumps({"files": ["dir/unit/test_declared.js", "dir/unit/test_new_of_ours.js"], "min_tests": 2}), encoding="utf-8")
        code, said = checked(t.series, t.list)
        add("check: the list that has every test of ours is exit 0", code == 0 and "0 problem" in said)

    tmp, t = tree({"test_declared.js": PASSING}, minimum=2)
    with tmp:
        t.list.write_text(json.dumps({"files": ["dir/unit/test_declared.js", "dir/unit/test_gone.js"], "min_tests": 2}), encoding="utf-8")
        code, result, _, _ = t.run()
        add("a listed file that the series does not have is RED in the verdict, with the reason of the check and the one of the run",
            code == 1 and any("test_gone.js" in r and "series does not have it" in r for r in result["reasons"]) and any("test_gone.js" in r and "exactly one" in r for r in result["reasons"]))
        code, said = checked(t.series, t.list)
        add("check: a listed file that is not in the series is exit 1, by name", code == 1 and "test_gone.js" in said)

    tmp, t = tree({"test_declared.js": PASSING}, minimum=2)
    with tmp:
        odd = t.series / "grp" / "fold" / "src" / "dir" / "mochitest"
        odd.mkdir(parents=True)
        (odd / "test_listed_but_not_xpcshell.js").write_text("// not in an xpcshell folder\n", encoding="utf-8")
        reasons = x.check_list(t.series, ["dir/unit/test_declared.js", "dir/mochitest/test_listed_but_not_xpcshell.js"])
        add("a listed file that exists but is not an xpcshell test of ours by the rule is RED (the rule and the list say the same)",
            len(reasons) == 1 and "not an xpcshell test of ours" in reasons[0])

    tmp, t = tree({"test_declared.js": PASSING}, minimum=2)
    with tmp:
        other = t.series / "grp2" / "fold2" / "src" / "dir" / "unit"
        other.mkdir(parents=True)
        (other / "test_declared.js").write_text("// the same path in another feature\n", encoding="utf-8")
        reasons = x.check_list(t.series, ["dir/unit/test_declared.js"])
        add("the same path in two features of the series is RED (exactly one file)", any("test_declared.js" in r and "series does not have it" in r for r in reasons))

    # --- the published engine: seal.json and the archive of the leg
    def published(archive_bytes=b"engine", seal_sha=None, name="firefox-159.0-stealth-linux-x86_64.tar.gz", extra=()):
        tmp_ = tempfile.TemporaryDirectory()
        d = Path(tmp_.name)
        (d / name).write_bytes(archive_bytes)
        sha = seal_sha if seal_sha is not None else hashlib.sha256(archive_bytes).hexdigest()
        (d / "seal.json").write_text(json.dumps({"tag": "firefox-68", "assets": {name: {"sha256": sha}}}), encoding="utf-8")
        for other_name in extra:
            (d / other_name).write_bytes(b"x")
        return tmp_, d

    def verify(d, leg="linux-x86_64"):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = x.verify_asset(d, leg)
        return code, buf.getvalue()

    tmp, d = published()
    with tmp:
        code, said = verify(d)
        add("verify-asset: the leg's archive with the sha256 of the seal is green", code == 0 and "firefox-68" in said)
    tmp, d = published(seal_sha="0" * 64)
    with tmp:
        code, said = verify(d)
        add("verify-asset: an archive whose sha256 is not the seal's is RED, with both hashes",
            code == 1 and "RED" in said and "0" * 64 in said and hashlib.sha256(b"engine").hexdigest() in said)
    tmp, d = published()
    with tmp:
        (d / "seal.json").write_text(json.dumps({"tag": "firefox-68", "assets": {"firefox-159.0-stealth-win-x86_64.zip": {"sha256": "ab"}}}), encoding="utf-8")
        code, said = verify(d)
        add("verify-asset: an archive that the seal does not name is RED", code == 1 and "not in the assets" in said)
    tmp, d = published()
    with tmp:
        code, said = verify(d, leg="win-x86_64")
        add("verify-asset: a leg with no archive is RED", code == 1 and "found 0" in said)
    tmp, d = published(extra=("firefox-160.0-stealth-linux-x86_64.tar.gz",))
    with tmp:
        code, said = verify(d)
        add("verify-asset: two archives of the leg are RED (one is the engine, which one is not guessed)", code == 1 and "found 2" in said)
    tmp, d = published()
    with tmp:
        (d / "seal.json").unlink()
        code, said = verify(d)
        add("verify-asset: no seal.json is RED", code == 1 and "seal.json" in said)
    tmp, d = published()
    with tmp:
        (d / "seal.json").write_text("{not json", encoding="utf-8")
        add("verify-asset: a seal.json that is not JSON is RED, not a traceback", verify(d)[0] == 1)

    # --- the two layouts of a manifest: Mozilla's xpcshell.toml of the folder (support) and a manifest of OURS beside the test (xpcshell-stealth.toml in the series)
    OURS_TOML = '[DEFAULT]\nhead = "head_ours.js head_x.js"\nprefs = ["ours.number=7"]\nenvironment = ["EXTRA_FROM_MANIFEST=ours"]\n\n["test_declared.js"]\n'
    tmp, t = tree({"test_declared.js": PASSING}, minimum=2)
    with tmp:
        cap = Path(tmp.name) / "capture-mozilla.json"
        code, result, _, _ = t.run(capture=cap)
        seen = json.loads(cap.read_text(encoding="utf-8"))
        add("layout Mozilla: the test is listed by the folder's xpcshell.toml of the tag; its head file comes from the support folder, its prefs and environment from that manifest",
            code == 0 and [Path(h).name for h in seen["evals"]["_HEAD_FILES"]] == ["head_x.js"] and 'user_pref("demo.number", 3);' in seen["prefs"]
            and seen["env"]["EXTRA_FROM_MANIFEST"] == "yes" and x.our_manifest_entry(t.series / "grp/fold/src/dir/unit/test_declared.js", "test_declared.js") is None)

    tmp, t = tree({"test_declared.js": PASSING}, minimum=2)
    with tmp:
        unit = t.series / "grp" / "fold" / "src" / "dir" / "unit"
        (unit / "xpcshell-stealth.toml").write_text(OURS_TOML, encoding="utf-8")
        (unit / "head_ours.js").write_text("// a head file of ours, beside the test in the series\n", encoding="utf-8")
        cap = Path(tmp.name) / "capture-ours.json"
        code, result, _, _ = t.run(capture=cap)
        seen = json.loads(cap.read_text(encoding="utf-8"))
        stage = Path(seen["evals"]["_TEST_FILE"][0]).parent
        add("layout ours: the test is listed by xpcshell-stealth.toml beside it; the manifest read is ours (its prefs and environment, not Mozilla's section)",
            code == 0 and result["verdict"] == "green" and 'user_pref("ours.number", 7);' in seen["prefs"] and 'user_pref("demo.number", 3);' not in seen["prefs"]
            and seen["env"]["EXTRA_FROM_MANIFEST"] == "ours")
        add("layout ours: a head file named by it comes from the series when it is ours (head_ours.js) and from the support folder when it is Mozilla's (head_x.js), both staged beside the test",
            [Path(h).name for h in seen["evals"]["_HEAD_FILES"]] == ["head_ours.js", "head_x.js"] and seen["problems"] == [])
        add("layout ours: discovery finds the test (it is in a unit folder and beside a manifest of ours), and the list that has it is the set",
            x.discover(t.series) == ["dir/unit/test_declared.js"] and x.check_list(t.series, ["dir/unit/test_declared.js"]) == []
            and x.our_manifest_entry(unit / "test_declared.js", "test_declared.js")["prefs"] == ["ours.number=7"])

    # a test in a folder that is not named unit/xpcshell is found by the manifest of ours beside it, in both layouts it must be in the list
    tmp, base = series_with([S + "w/tests/test_odd_name.js", S + "w/tests/xpcshell-stealth.toml", S + "x/tests/test_odd_name2.js"])
    with tmp:
        add("layout ours: a test beside xpcshell-stealth.toml in a folder with any name is ours; the same file with no manifest of ours and no unit/xpcshell folder is not",
            x.discover(base) == ["w/tests/test_odd_name.js"])

    tmp, t = tree({"test_declared.js": PASSING}, minimum=2)
    with tmp:
        unit = t.series / "grp" / "fold" / "src" / "dir" / "unit"
        (unit / "xpcshell-stealth.toml").write_text(OURS_TOML.replace("head_ours.js head_x.js", "head_missing.js"), encoding="utf-8")
        code, result, _, _ = t.run()
        add("layout ours: a head file that is neither beside the test nor in the support folder is the file's red, said by name",
            code == 1 and any("head_missing.js" in e for e in result["files"][0]["errors"]))

    # the lock, from a real git repository with a tag, for both layouts
    def git_repo(files):
        tmp_ = tempfile.TemporaryDirectory()
        repo = Path(tmp_.name)
        for rel, text in files.items():
            f = repo / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text, encoding="utf-8")
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "tag"], ["tag", "T1"]):
            subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env)
        return tmp_, str(repo)

    base_files = {
        "testing/xpcshell/head.js": "// h\n", "testing/modules/Assert.sys.mjs": "// a\n", "toolkit/modules/tests/modules/PromiseTestUtils.sys.mjs": "// b\n",
        "tools/code-coverage/PerTestCoverageUtils.sys.mjs": "// c\n", "netwerk/test/httpserver/httpd.sys.mjs": "// d\n",
        "testing/profiles/profiles.json": json.dumps({"xpcshell": ["base"]}), "testing/profiles/base/user.js": "// u\n",
        "dir/unit/xpcshell.toml": '[DEFAULT]\nhead = "head_x.js"\n\n["test_declared.js"]\n', "dir/unit/head_x.js": "// x\n", "dir/unit/head_ours.js": "// not ours in the tag\n",
        "dir/unit/head_unlisted.js": "// y\n"}
    tmp_g, repo = git_repo(base_files)
    with tmp_g:
        moz = x.lock_files(repo, "T1", [("dir/unit", "test_declared.js", None, None)])
        add("lock, layout Mozilla: the folder's xpcshell.toml of the tag and the head files of the test's entry are locked",
            "dir/unit/xpcshell.toml" in moz and "dir/unit/head_x.js" in moz and "dir/unit/head_unlisted.js" not in moz and x.HARNESS in moz)
        with tempfile.TemporaryDirectory() as ours_dir:
            (Path(ours_dir) / "head_ours.js").write_text("// ours\n", encoding="utf-8")
            entry = {"head": "head_ours.js head_x.js"}
            mine = x.lock_files(repo, "T1", [("dir/unit", "test_declared.js", entry, ours_dir)])
            add("lock, layout ours: the head file of Mozilla's that the manifest of ours names is locked, the head file of ours (beside the test in the series) is not, and the folder's xpcshell.toml is not needed",
                "dir/unit/head_x.js" in mine and "dir/unit/head_ours.js" not in mine and "dir/unit/xpcshell.toml" not in mine and x.HARNESS in mine)

    # --- prefs: every preference of the engine, two engines compared with zero differences allowed
    def dump(default=None, user=None, meta=None):
        base = {"app.a": {"type": "bool", "value": True, "locked": False}, "app.b": {"type": "int", "value": 5, "locked": False},
                "app.c": {"type": "string", "value": "x", "locked": False}, "app.d": {"type": "string", "value": "café", "locked": True}}
        return {"schema": 1, "default": base if default is None else default, "user": {} if user is None else user, "meta": meta or {}}

    def changed(**edits):
        d = dump()
        for name, entry in edits.items():
            n = name.replace("_", ".")
            if entry is None:
                d["default"].pop(n, None)
            else:
                d["default"][n] = entry
        return d

    def compare(a, b, control=False):
        """(exit code, output, the diff JSON) of prefs-compare on two dumps written to a temporary folder."""
        with tempfile.TemporaryDirectory() as tmpd:
            pa, pb, po = Path(tmpd) / "a.json", Path(tmpd) / "b.json", Path(tmpd) / "diff.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = x.prefs_compare(pa, pb, po, control)
            return code, buf.getvalue(), json.loads(po.read_text(encoding="utf-8")) if po.is_file() else None

    code, text, diff = compare(dump(), dump(meta={"seconds": 9, "os": "linux"}))
    add("prefs-compare: two dumps with the same prefs (only `meta` differs) are green, exit 0, no difference listed",
        code == 0 and diff["verdict"] == "green" and diff["differences"] == [] and "no difference" in text)

    code, text, diff = compare(dump(), changed(app_b={"type": "int", "value": 6, "locked": False}))
    add("prefs-compare: one value changed is red, exit 1, and the line has the pref name and both values",
        code == 1 and diff["verdict"] == "red" and len(diff["differences"]) == 1 and "app.b: a=int:5 locked=false b=int:6 locked=false" in text)
    if DEMO:
        print("---- the red case: a pref of the candidate has another value, another pref is gone, a third is new ----")
        d_demo = changed(app_b={"type": "int", "value": 6, "locked": False}, app_a=None, app_e={"type": "string", "value": "new", "locked": False})
        c_demo, t_demo, _ = compare(dump(), d_demo)
        print(t_demo.strip())
        print("---- exit code %d ----" % c_demo)
        print("---- the broken control: the same engine dumped twice ----")
        c_demo, t_demo, _ = compare(dump(), changed(app_c={"type": "string", "value": "y", "locked": False}), control=True)
        print(t_demo.strip())
        print("---- exit code %d ----" % c_demo)

    code, text, diff = compare(dump(), changed(app_a=None))
    add("prefs-compare: a pref the candidate lacks is red and is named (kind missing)",
        code == 1 and [(i["name"], i["kind"]) for i in diff["differences"]] == [("app.a", "missing")] and "app.a: only in a: bool:true" in text)
    code, text, diff = compare(dump(), changed(app_e={"type": "bool", "value": False, "locked": False}))
    add("prefs-compare: a pref the candidate adds is red and is named (kind added)",
        code == 1 and [(i["name"], i["kind"]) for i in diff["differences"]] == [("app.e", "added")] and "app.e: only in b: bool:false" in text)
    code, text, _ = compare(dump(), changed(app_b={"type": "string", "value": "5", "locked": False}))
    add("prefs-compare: the same text in another type (int 5 against string \"5\") is red, both are shown with their type",
        code == 1 and "a=int:5 locked=false b=string:\"5\" locked=false" in text)
    code, text, _ = compare(dump(), changed(app_a={"type": "int", "value": 1, "locked": False}))
    add("prefs-compare: bool true against int 1 is red (a value is compared with its type, never by Python equality)", code == 1 and "a=bool:true" in text and "b=int:1" in text)
    code, text, _ = compare(dump(), changed(app_d={"type": "string", "value": "café", "locked": False}))
    add("prefs-compare: only the locked flag differs: red, and both flags are shown", code == 1 and "app.d" in text and "locked=true" in text and "locked=false" in text)
    code, text, _ = compare(dump(), dump(user={"app.u": {"type": "bool", "value": True}}))
    add("prefs-compare: a difference on the user branch of the fresh profile is red, with the branch named", code == 1 and "user app.u: only in b: bool:true" in text)
    code, text, _ = compare(dump(user={"app.u": {"type": "int", "value": 1}}), dump(user={"app.u": {"type": "int", "value": 2}}))
    add("prefs-compare: a user value that changed is red", code == 1 and "user app.u: a=int:1 b=int:2" in text)
    code, text, _ = compare(dump(), changed(app_a={"type": "float", "value": 1.5, "locked": False}))
    add("prefs-compare: an entry of a type that is not string, int or bool is not a dump: red", code == 1 and "malformed" in text)
    code, text, _ = compare(dump(), changed(app_a={"type": "int", "value": True, "locked": False}))
    add("prefs-compare: an int whose value is a boolean is malformed: red", code == 1 and "malformed" in text)
    code, text, _ = compare(dump(), changed(app_a={"type": "bool", "value": True}))
    add("prefs-compare: a default entry without the locked flag is not a dump: red", code == 1 and "locked" in text)
    code, text, _ = compare(dump(), dump(default={}))
    add("prefs-compare: a dump with an empty default branch is red (a shell that listed nothing is not zero differences)", code == 1 and "empty" in text)
    code, text, _ = compare(dump(), changed(app_x={"type": "error", "value": "NS_ERROR_UNEXPECTED"}))
    add("prefs-compare: a pref the dump could not read is a difference when only one engine has it, and is listed as unreadable",
        code == 1 and "app.x" in text and "could not read" in text)

    code, text, diff = compare(dump(), dump(), control=True)
    add("control (A/A): the same engine twice with no difference is green, exit 0", code == 0 and diff["control"] is True and diff["verdict"] == "green")
    code, text, diff = compare(dump(), changed(app_c={"type": "string", "value": "y", "locked": False}), control=True)
    add("control (A/A): the same engine twice that differs is BROKEN CONTROL, exit 2, and every difference is still printed",
        code == x.EXIT_CONTROL == 2 and "BROKEN CONTROL" in text and "app.c: a=string:\"x\" locked=false b=string:\"y\" locked=false" in text and diff["verdict"] == "red")
    code, text, _ = compare(dump(), dump(default={}), control=True)
    add("control (A/A): an unusable dump in the control is a broken control too, exit 2", code == 2 and "BROKEN CONTROL" in text)

    # the dump command, with a fake shell that checks what the real one would depend on
    with tempfile.TemporaryDirectory() as tmpd:
        tmp = Path(tmpd)
        (tmp / "bin").mkdir()
        fake = tmp / "bin" / "fake_firefox.py"
        fake.write_text(PREFS_FAKE, encoding="utf-8")
        binary = [sys.executable, str(fake)]
        wanted = tmp / "wanted.json"
        wanted.write_text(json.dumps(dump(user={"app.u": {"type": "bool", "value": True}})), encoding="utf-8")
        os.environ["FAKE_PREFS"] = str(wanted)

        def run_dump(mode="ok", name="d.json", root=None, timeout=20):
            os.environ["FAKE_MODE"] = mode
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = x.prefs_dump(binary, tmp / name, root or tmp / "profile-root", timeout)
            return code, buf.getvalue()

        code, text = run_dump()
        written = json.loads((tmp / "d.json").read_text(encoding="utf-8")) if (tmp / "d.json").is_file() else {}
        raw = (tmp / "d.json").read_bytes() if (tmp / "d.json").is_file() else b""
        add("prefs: the shell gets -xpcshell -g <gre> -a <gre>/browser -f prefs_dump.js -e quit(0);, a fresh empty profile, PREFS_DUMP_OUT, the leg's environment: green, "
            "the dump is written sorted with LF only and the counts in meta (a fake shell that checks them)",
            code == 0 and written.get("default", {}).get("app.d") == {"type": "string", "value": "café", "locked": True} and written["user"] == {"app.u": {"type": "bool", "value": True}}
            and written["meta"]["default_count"] == 4 and written["meta"]["user_count"] == 1 and b"\r" not in raw and b"\\u00e9" in raw
            and list(written["default"]) == sorted(written["default"]))
        code, text = run_dump(name="d2.json")
        add("prefs: a second dump finds the profile folder empty again (the folder of the first run, with its prefs.js, is removed first): green",
            code == 0 and (tmp / "d2.json").is_file())
        with contextlib.redirect_stdout(io.StringIO()):
            code = x.prefs_compare(tmp / "d.json", tmp / "d2.json", None, True)
        add("prefs: two dumps of the same fake engine through the real commands: control green", code == 0)
        code, text = run_dump("exit", "e.json")
        add("prefs: the shell exits non-zero: red, exit 1, no dump", code == 1 and "RED" in text and not (tmp / "e.json").is_file())
        code, text = run_dump("none", "n.json")
        add("prefs: the shell exits 0 and writes no dump: red", code == 1 and "no readable dump" in text and not (tmp / "n.json").is_file())
        code, text = run_dump("jserror", "j.json")
        add("prefs: the shell exits 0 after a JavaScript error and writes no dump: red, and the shell's own output (the error line) is printed",
            code == 1 and "no readable dump" in text and "SyntaxError: malformed Unicode character escape sequence" in text)
        code, text = run_dump("exit", "e2.json")
        add("prefs: a shell that exits non-zero has its output printed too", code == 1 and "the shell's output" in text)
        # a relative path to the binary (the workflow's `ff/firefox`) with the dump root as the shell's working directory
        here = os.getcwd()
        try:
            os.chdir(tmp)
            os.environ["FAKE_MODE"] = "ok"
            with contextlib.redirect_stdout(io.StringIO()):
                code = x.prefs_dump([sys.executable, os.path.join("bin", "fake_firefox.py")], Path("rel.json"), Path("rel-root"), 20)
        finally:
            os.chdir(here)
        add("prefs: a binary and a root given as RELATIVE paths (as the workflow does: ff/firefox, prefs-profile) work: the binary is made absolute before the shell's folder is its working directory",
            code == 0 and (tmp / "rel.json").is_file())
        code, text = run_dump("hang", "h.json", timeout=1.5)
        add("prefs: the shell hangs: red at the timeout", code == 1 and "timed out" in text)
        wanted.write_text(json.dumps(dump(default={})), encoding="utf-8")
        code, text = run_dump(name="z.json")
        add("prefs: a dump with an empty default branch is red and is not written", code == 1 and "not usable" in text and not (tmp / "z.json").is_file())
        os.environ.pop("FAKE_PREFS", None)
        os.environ.pop("FAKE_MODE", None)

    # the dump script, read as text: the enumeration and the getters that the Python side expects
    js_path = HERE / "prefs_dump.js"
    js = js_path.read_text(encoding="utf-8") if js_path.is_file() else ""
    add("prefs_dump.js: enumerates the default branch (getDefaultBranch, getChildList), types each name, reads the typed getter, the locked flag and the user branch, "
        "announces the profile as head.js does, writes to PREFS_DUMP_OUT",
        all(t in js for t in ('getDefaultBranch("")', "getChildList(", "getPrefType(", "getStringPref(", "getIntPref(", "getBoolPref(", "prefIsLocked(", "prefHasUserValue(",
                              '"profile-do-change"', "PREFS_DUMP_OUT", "XPCSHELL_TEST_PROFILE_DIR")) and b"\r" not in js_path.read_bytes())
    add("prefs_dump.js: the non-ASCII escape is written with TWO backslashes in the JS source (a single one makes the file not parse: 'malformed Unicode character escape sequence')",
        'c => "' + chr(92) * 2 + 'u" +' in js and 'c => "' + chr(92) + 'u" +' not in js.replace('c => "' + chr(92) * 2 + 'u" +', ""))
    add("prefs_dump.js: never a getter of the host (no os, no env other than the two paths, no Date)", "Date" not in js and js.count("env.get(") == 2)

    # the workflow
    wf = ROOT / ".github" / "workflows" / "xpcshell.yml"
    text = wf.read_text(encoding="utf-8") if wf.is_file() else ""
    try:
        import yaml
        doc = yaml.safe_load(text)
        on = doc.get(True, doc.get("on", {}))
        legs = doc["jobs"]["xpcshell"]["strategy"]["matrix"]["include"]
        steps = doc["jobs"]["xpcshell"]["steps"]
        add("xpcshell.yml: a workflow_call with build_run_id, wrapper_ref and published_tag, a push on latitude/*-oracles, no schedule, the dispatch's candidate as default",
            set(on["workflow_call"]["inputs"]) == {"build_run_id", "wrapper_ref", "published_tag"} and on["push"]["branches"] == ["latitude/*-oracles"] and "schedule" not in on
            and "'44921963200'" in text and on["workflow_dispatch"]["inputs"]["build_run_id"]["default"] == "44921963200")
        env = doc["jobs"]["xpcshell"]["env"]
        run_dl = [st for st in steps if st.get("name", "").startswith("Download asset (the run's)")]
        pub_dl = [st for st in steps if st.get("name", "").startswith("Download asset (the published")]
        add("xpcshell.yml: the legs have 15 minutes", doc["jobs"]["xpcshell"]["timeout-minutes"] == 15)
        add("xpcshell.yml: the published engine is firefox-68 on this workflow's own push (no build_run_id) and never because the caller's event is a push",
            "inputs.build_run_id == ''" in env["PUBLISHED_TAG"] and "github.event_name == 'push'" in env["PUBLISHED_TAG"] and "'firefox-68'" in env["PUBLISHED_TAG"]
            and env["PUBLISHED_TAG"].index("inputs.build_run_id == ''") < env["PUBLISHED_TAG"].index("github.event_name") and "inputs.published_tag" in env["PUBLISHED_TAG"])
        add("xpcshell.yml: the run's artifacts are downloaded only with no published tag, the release's archives only with one",
            len(run_dl) == 1 and run_dl[0]["if"] == "env.PUBLISHED_TAG == ''" and "run-id" in run_dl[0]["with"]
            and len(pub_dl) == 1 and pub_dl[0]["if"] == "env.PUBLISHED_TAG != ''")
        add("xpcshell.yml: the published download is `gh release download` of the seal and the leg's archive, then verify-asset (the sha256 of the seal) before anything is extracted",
            len(pub_dl) == 1 and "gh release download" in pub_dl[0]["run"] and "--pattern seal.json" in pub_dl[0]["run"] and "xpcshell_run.py verify-asset" in pub_dl[0]["run"]
            and [i for i, st in enumerate(steps) if st is pub_dl[0]][0] < [i for i, st in enumerate(steps) if st.get("name", "").startswith("Extract")][0])
        chk = [i for i, st in enumerate(steps) if "xpcshell_run.py check" in st.get("run", "")]
        add("xpcshell.yml: the list-against-the-series check runs before any download, and it binds",
            len(chk) == 1 and chk[0] < [i for i, st in enumerate(steps) if st is run_dl[0]][0] and "continue-on-error" not in steps[chk[0]] and "|| true" not in steps[chk[0]]["run"])
        add("xpcshell.yml: the series checkout reaches the test folders named `test` too, not only `tests`", "/*/*/src/**/test/" in text and "/*/*/src/**/tests/" in text)
        add("xpcshell.yml: a Linux leg and a Windows leg, each on its native runner", {(l["runner"], l["kind"]) for l in legs} == {("ubuntu-24.04", "linux"), ("windows-latest", "win")})
        runs = [s for s in steps if "xpcshell_run.py run" in s.get("run", "")]
        ldd = [s for s in steps if "ldd" in s.get("run", "")]
        add("xpcshell.yml: ldd sees the package's folder (LD_LIBRARY_PATH) and only a library that is not in the package counts as missing",
            len(ldd) == 1 and 'LD_LIBRARY_PATH="$PWD/ff"' in ldd[0]["run"] and '[ -e "ff/$lib" ]' in ldd[0]["run"])
        add("xpcshell.yml: one step runs the tests, it binds (no continue-on-error, no `|| true`), and the result is uploaded even when it is red",
            len(runs) == 1 and "continue-on-error" not in runs[0] and "|| true" not in runs[0]["run"]
            and any(s.get("uses", "").startswith("actions/upload-artifact") and "always()" in s.get("if", "") for s in steps))
        add("xpcshell.yml: the files of ours come from the series at the commit under test, Mozilla's from the lock (fetch before run)",
            any("engine-series" in str((s.get("with") or {}).get("path", "")) for s in steps)
            and [i for i, s in enumerate(steps) if "xpcshell_run.py fetch" in s.get("run", "")][0] < [i for i, s in enumerate(steps) if "xpcshell_run.py run" in s.get("run", "")][0])
        # --- the prefs job
        pj = doc["jobs"]["prefs"]
        ps = pj["steps"]
        runs_text = [st.get("run", "") for st in ps]
        idx = lambda needle: [i for i, t in enumerate(runs_text) if needle in t]  # noqa: E731
        control_i = [i for i in idx("--control")]
        cand_i = [i for i in idx("--out prefs-out/candidate.json")]
        cmp_i = [i for i in idx("prefs-compare prefs-out/published-1.json prefs-out/candidate.json")]
        pre = [st for st in ps if "download-artifact" in st.get("uses", "")]
        add("xpcshell.yml prefs: a Linux leg and a Windows leg on their native runners, 15 minutes, the baseline is firefox-68",
            {(l["runner"], l["kind"]) for l in pj["strategy"]["matrix"]["include"]} == {("ubuntu-24.04", "linux"), ("windows-latest", "win")}
            and pj["timeout-minutes"] == 15 and pj["env"]["PREFS_BASE_TAG"] == "firefox-68")
        add("xpcshell.yml prefs: the published engine is the release's archive checked against its seal (verify-asset), the candidate is the run's asset, "
            "a push to latitude/*-oracles uses the dispatch's candidate",
            len(idx("gh release download")) == 1 and len(idx("verify-asset")) == 1 and len(pre) == 1 and "44921963200" in pre[0]["with"]["run-id"] and "build_run_id" in pre[0]["with"]["run-id"]
            and "asset-${{ matrix.leg }}" == pre[0]["with"]["name"])
        add("xpcshell.yml prefs: the A/A (published dumped twice, compared with --control) comes before the candidate is extracted or dumped",
            len(control_i) == 1 and len(cand_i) == 1 and control_i[0] < cand_i[0] < cmp_i[0]
            and runs_text[control_i[0]].count("prefs --binary") == 2 and "art-pub" in runs_text[control_i[0]] and "art-cand" not in runs_text[control_i[0]]
            and "art-cand" in runs_text[cand_i[0]])
        add("xpcshell.yml prefs: both engines are extracted to `ff` and every dump uses the same profile folder (so no value that holds a path can differ)",
            sum(t.count("--root prefs-profile") for t in runs_text) == 3 and sum(t.count("-C ff") for t in runs_text) == 2
            and all("rm -rf ff" in runs_text[i] for i in (control_i[0], cand_i[0])))
        add("xpcshell.yml prefs: the control and the comparison bind (no continue-on-error, no `|| true`), the diff is written, the dumps and the diff are uploaded even when red",
            all("continue-on-error" not in ps[i] and not any("|| true" in ln for ln in ps[i]["run"].splitlines() if "xpcshell_run.py" in ln or "$PREFS_PY" in ln)
                for i in (control_i[0], cand_i[0], cmp_i[0]))
            and "--out prefs-out/diff.json" in runs_text[cmp_i[0]] and "--out prefs-out/control-diff.json" in runs_text[control_i[0]]
            and any(st.get("uses", "").startswith("actions/upload-artifact") and "always()" in st.get("if", "") and st["with"]["path"] == "prefs-out" for st in ps))
        add("xpcshell.yml prefs: the checkout reaches the dump script", any("/platform/ci/src/scripts/ci/prefs_dump.js" in str((st.get("with") or {}).get("sparse-checkout", "")) for st in ps))
        add("xpcshell.yml prefs: the existing xpcshell job is still the one the cases above read (two jobs, the prefs job does not replace it)", set(doc["jobs"]) == {"xpcshell", "prefs"})
    except Exception as exc:  # noqa: BLE001
        add("xpcshell.yml reads as the cases above expect: %s" % exc, False)
    return out


if __name__ == "__main__":
    DEMO = True
    results = cases()
    for label, ok in results:
        print(("ok    " if ok else "FAIL  ") + label)
    print("%d/%d cases as expected" % (sum(ok for _, ok in results), len(results)))
    sys.exit(0 if all(ok for _, ok in results) else 1)
