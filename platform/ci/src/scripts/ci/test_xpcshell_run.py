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
    add("the declared list has our three xpcshell tests of the line and the minimum is their eight tasks",
        len(declared["files"]) == 3 and declared["min_tests"] == 8 and all(Path(f).name.startswith("test_stealth_") for f in declared["files"]))
    add("the lock has the harness, the modules, the profiles, and the manifest of every folder of a declared test",
        x.HARNESS in lock["files"] and all(r in lock["files"] for r in x.MODULES_EXTRA) and "testing/modules/StructuredLog.sys.mjs" in lock["files"]
        and "testing/profiles/xpcshell/user.js" in lock["files"] and all(f + "/xpcshell.toml" in lock["files"] for f in folders)
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

    # the workflow
    wf = ROOT / ".github" / "workflows" / "xpcshell.yml"
    text = wf.read_text(encoding="utf-8") if wf.is_file() else ""
    try:
        import yaml
        doc = yaml.safe_load(text)
        on = doc.get(True, doc.get("on", {}))
        legs = doc["jobs"]["xpcshell"]["strategy"]["matrix"]["include"]
        steps = doc["jobs"]["xpcshell"]["steps"]
        add("xpcshell.yml: a workflow_call with build_run_id and wrapper_ref, a push on latitude/*-oracles with the measurement's candidate as default, no schedule",
            set(on["workflow_call"]["inputs"]) == {"build_run_id", "wrapper_ref"} and on["push"]["branches"] == ["latitude/*-oracles"] and "schedule" not in on
            and "'44921963200'" in text and on["workflow_dispatch"]["inputs"]["build_run_id"]["default"] == "44921963200")
        add("xpcshell.yml: a Linux leg and a Windows leg, each on its native runner", {(l["runner"], l["kind"]) for l in legs} == {("ubuntu-24.04", "linux"), ("windows-latest", "win")})
        runs = [s for s in steps if "xpcshell_run.py run" in s.get("run", "")]
        add("xpcshell.yml: one step runs the tests, it binds (no continue-on-error, no `|| true`), and the result is uploaded even when it is red",
            len(runs) == 1 and "continue-on-error" not in runs[0] and "|| true" not in runs[0]["run"]
            and any(s.get("uses", "").startswith("actions/upload-artifact") and "always()" in s.get("if", "") for s in steps))
        add("xpcshell.yml: the files of ours come from the series at the commit under test, Mozilla's from the lock (fetch before run)",
            any("engine-series" in str((s.get("with") or {}).get("path", "")) for s in steps)
            and [i for i, s in enumerate(steps) if "xpcshell_run.py fetch" in s.get("run", "")][0] < [i for i, s in enumerate(steps) if "xpcshell_run.py run" in s.get("run", "")][0])
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
