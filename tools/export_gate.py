"""The tests that have to be green before the series is exported, run on what the export is about to write.

Run 43156862361 (the third candidate of the UDP line) died one minute after it started: the Juggler's node tests, which the build job
runs before it compiles, found six reds that nobody had run, because the local tree they were tried on is a sparse one and four of
them read files it does not have. A red that can be found here costs a node of Latitude there. So `engine.py export` runs the same
tests the build job runs and refuses to write anything into the checkout if one is red. Two kinds of test, each on what it tests:

  1. The tests of the SOURCE head, on the WHOLE tree of the head, before anything is written:
       * the Juggler's node tests (juggler/tests/*.test.mjs), with Node;
       * the python tests of ours in the engine tree that are plain scripts (modules/libpref/test/test_stealth_*.py).
     The tree is a git worktree of the source repository, at the path in ENGINE_NODE_GATE_TREE (no default: unset, the export
     refuses), moved to the head by a checkout (the first time it is made it writes the whole tree, a quarter of an hour; after that
     only what differs). Node is the one in ENGINE_NODE, else the one on the PATH; with none the export refuses (a gate that cannot
     run is not a pass).
  2. The tests of the SERIES, on the series the export writes, never on the old one. A commit of tools that changes what the export
     writes has tests that are red until that export has written (they read the folders, SERIES, HOOKS.json, the workflow copies),
     so a gate that ran them on the checkout before the write refused the very export that turns them green. The order is:
       a. a scratch copy of the checkout (scratch_series): `git worktree add --detach --no-checkout` of the checkout's repository at
          HEAD, which gives it its own index and the refs (origin/main), then every file of the checkout copied into it byte for
          byte, uncommitted edits included, so the scratch tree is what the checkout is now, not what HEAD was;
       b. the export writes the series into the scratch tree (the callable `write` that engine.py gives: the same `export`, with the
          paths of engine.py moved to the scratch root);
       c. in the scratch tree: `tools/engine.py check` (as the command line does) and
          `python -m pytest -q -n auto tools/tests` (pytest-xdist). The tests find their root from their own file, so they read
          the scratch tree, never the checkout;
       d. only if all are green the checkout takes the result (replace_series): every file the export wrote or changed is copied,
          every file it removed is deleted, and a folder left empty goes; the set is found by comparing the scratch tree before and
          after the write, not from a list of names, so nothing the export writes can be left stale. A re-export that changes
          nothing touches nothing.
     A red leaves the checkout as it was, byte for byte, and the scratch tree is removed; the stop names which test or check is red.
     What only a step after the export can close does not make the gate red, and only what THIS export made (News, tolerated): an empty
     `anchor`, `notes` or `hookable` of an inventory record the export derived (its (file, folder) is not in the checkout's
     tools/inventory.json), and a missing churn row (C18) of a hunk the export moved or created (its churn key is in the scratch
     hooks.patch files and not in the checkout's; tools/churn.py writes the rows and needs the release tags). Each is printed as
     `TODO after export: <file>: <what>. Fix: <command or hand step>`; an empty field of any other record, a missing row of a hunk the
     export did not touch, and every other failure of check stay red. check itself is not changed: on the pull request it refuses both.
     The one test of tools/tests that says the churn rule again over the whole series (RESTATES_CHURN) is red for the same hunks, so it is let
     through, as a TODO line, exactly when check's own churn failure was and nothing else is red.
There is no switch to skip the gate.
"""
from __future__ import annotations

import glob
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from failure import Failure, fail  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
# The decision that owns the gate: the export is the one writer, and it writes nothing while a test is red (series-01).
RULE = "series-01-export-is-the-only-writer"


def _with_next(failure, next_step: str) -> str:
    """repo-05: a stop ends with `next: <the exact command to run>`."""
    return "%s\nnext: %s" % (failure, next_step)


def gate_tree() -> Path:
    value = os.environ.get("ENGINE_NODE_GATE_TREE")
    if not value:
        raise SystemExit(str(fail(
            "environment variable ENGINE_NODE_GATE_TREE", "export refused: the whole tree for the node tests is not named",
            "set ENGINE_NODE_GATE_TREE to the path of a worktree of the source repository (it is made there the first time)", RULE)))
    return Path(value)


def node_binary() -> str:
    for candidate in (os.environ.get("ENGINE_NODE"), shutil.which("node")):
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise SystemExit(str(fail(
        "node on this machine", "export refused: there is no Node (ENGINE_NODE, or node on the PATH), so the Juggler's node tests "
        "cannot run, and the build job would be the first to run them",
        "install Node, or set ENGINE_NODE to its path", RULE)))


def git(*args: str, cwd: Path | None = None) -> str:
    done = subprocess.run(["git", "-c", "core.longpaths=true", *args], cwd=cwd, capture_output=True, text=True)
    if done.returncode:
        raise SystemExit(str(fail(
            "git %s" % " ".join(args), "export refused: git failed: %s" % done.stderr.strip(),
            "run `git %s` by hand (in %s) to see git's message, then by case: `not a git repository` means --source (or FIREFOX_SOURCE) is not the Firefox "
            "repository: pass the folder that holds its .git; `unknown revision` or `bad object` means the commit or branch to export is missing: run "
            "`git -C <source> fetch`, or pass --head with a branch it has; a path error naming the gate tree means ENGINE_NODE_GATE_TREE points at a "
            "folder that does not exist: set it to an existing tree or unset it" % (" ".join(args), cwd or "the current folder"), RULE)))
    return done.stdout.strip()


def prepare_tree(source: Path, head: str, tree: Path | None = None) -> Path:
    """The whole tree of `head`, in a worktree of the source repository."""
    tree = tree or gate_tree()
    sha = git("-C", str(source), "rev-parse", head)
    if not (tree / ".git").exists():
        print("export gate: making the whole tree of the node tests in %s (the first time takes a quarter of an hour)" % tree)
        git("-C", str(source), "worktree", "add", "--detach", str(tree), sha)
    elif git("-C", str(tree), "rev-parse", "HEAD") != sha:
        git("-C", str(tree), "checkout", "--detach", "--force", sha)
    if git("-C", str(tree), "rev-parse", "HEAD") != sha:
        raise SystemExit(str(fail(
            str(tree), "export refused: it is not at %s" % sha,
            "remove the worktree (git -C <source> worktree remove --force %s) and run the export again" % tree, RULE)))
    if not (tree / "juggler" / "tests").is_dir() or not (tree / "netwerk" / "base").is_dir():
        raise SystemExit(str(fail(
            str(tree), "export refused: it is not a whole tree (no juggler/tests or netwerk/base)",
            "remove it (git -C <source> worktree remove --force %s) and run the export again: it is made whole the first time" % tree, RULE)))
    return tree


def _failures(output: str) -> list:
    return [line.split(" - ", 1)[-1].strip() for line in output.splitlines() if line.startswith("not ok ")]


def run_node_tests(tree: Path, node: str) -> list:
    files = sorted(glob.glob(str(tree / "juggler" / "tests" / "*.test.mjs")))
    if not files:
        return [fail("%s/juggler/tests" % tree, "there is no *.test.mjs file",
                         "restore the tests in the source branch: the export runs the Juggler's node tests and a gate with none is not a pass", RULE)]
    done = subprocess.run([node, "--test", "--test-reporter=tap", *files], cwd=tree, capture_output=True, text=True, encoding="utf-8", errors="replace")
    summary = [line for line in done.stdout.splitlines() if line.startswith(("# tests", "# pass", "# fail"))]
    print("export gate: node tests: " + ", ".join(s[2:] for s in summary))
    if done.returncode:
        return [fail("juggler/tests (node --test)", "a node test is red: %s" % reason, "fix the test or the code in the source branch, then run the export again", RULE)
                for reason in (_failures(done.stdout) or ["node exited %d: %s" % (done.returncode, done.stderr.strip())])]
    return []


def run_tree_python_tests(tree: Path) -> list:
    problems = []
    for script in sorted(glob.glob(str(tree / "modules" / "libpref" / "test" / "test_stealth_*.py"))):
        done = subprocess.run([sys.executable, script], cwd=tree, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if done.returncode:
            problems.append(fail("modules/libpref/test/%s" % Path(script).name, "a python test of the tree is red: %s" % (done.stdout + done.stderr).strip(),
                                     "fix the test or the code in the source branch, then run the export again", RULE))
    print("export gate: %d python tests of the tree" % len(glob.glob(str(tree / "modules" / "libpref" / "test" / "test_stealth_*.py"))))
    return problems


def scratch_series(root: Path = ROOT) -> Path:
    """A scratch copy of the checkout at `root`: the tree to write the series into and to test before the checkout is touched.

    A git worktree of the checkout's repository (detached at HEAD, nothing checked out) gives the copy its own index and the refs of
    the repository, origin/main among them, which `check` and the tests read; the files are then copied from the checkout itself,
    so uncommitted edits (a tools change under test, a FEATURE.md) are in it and the copy is what the export would have found in
    the checkout. A copy and not a hard link: the export rewrites files in place. Returns the tree; its parent is the scratch
    directory (remove_scratch takes both away)."""
    base = Path(tempfile.mkdtemp(prefix="series-gate-"))
    tree = base / "s"
    try:
        git("-C", str(root), "worktree", "add", "--detach", "--no-checkout", str(tree), "HEAD")
        shutil.copytree(root, tree, dirs_exist_ok=True, ignore=lambda directory, names: [
            n for n in names if n == "__pycache__" or (n == ".git" and Path(directory) == root)])
    except BaseException:
        remove_scratch(tree, root)
        raise
    return tree


def remove_scratch(tree: Path, root: Path = ROOT) -> None:
    """Takes the scratch tree and its registration in the repository away."""
    subprocess.run(["git", "-c", "core.longpaths=true", "-C", str(root), "worktree", "remove", "--force", str(tree)], capture_output=True)
    shutil.rmtree(tree.parent, ignore_errors=True)
    subprocess.run(["git", "-C", str(root), "worktree", "prune"], capture_output=True)


def _walk(root: Path) -> dict:
    """Every file under `root` (not .git, not __pycache__): relative posix path -> (size, mtime_ns)."""
    found = {}
    for directory, names, files in os.walk(root):
        names[:] = [n for n in names if n not in ("__pycache__", ".git")]
        for name in files:
            path = Path(directory, name)
            stat = path.stat()
            found[path.relative_to(root).as_posix()] = (stat.st_size, stat.st_mtime_ns)
    return found


def _same_bytes(a: Path, b: Path) -> bool:
    return a.is_file() and b.is_file() and a.stat().st_size == b.stat().st_size and a.read_bytes() == b.read_bytes()


def series_delta(tree: Path, root: Path, before: dict) -> tuple:
    """(written, removed): what the export did to `tree`, against `before` (a _walk of it taken before the write). A file is written
    when it is new or its size or modification time moved, and its bytes then differ from the checkout's (a rewrite with the same
    bytes is not a change); removed when it was there before and is not now. Found by comparing, not from a list of names, so
    nothing the export writes can be left out."""
    after = _walk(tree)
    written = sorted(p for p, stat in after.items() if before.get(p) != stat and not _same_bytes(tree / p, root / p))
    removed = sorted(set(before) - set(after))
    return written, removed


def replace_series(tree: Path, root: Path, written: list, removed: list) -> None:
    """The checkout takes the series from the scratch tree: the written files copied, the removed ones deleted, a folder that is left
    with nothing (a __pycache__ apart) taken away."""
    for rel in removed:
        (root / rel).unlink(missing_ok=True)
        parent = (root / rel).parent
        while parent != root and parent.is_dir() and all(n.name == "__pycache__" for n in parent.iterdir()):
            shutil.rmtree(parent)
            parent = parent.parent
    for rel in written:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(tree / rel, target)


def _run(command: list, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")


FAILURE_LINE = re.compile(r"^FAIL ")
# A failure prints as `FAIL <where>: <what>. Fix: <fix>. Rule: docs/decisions/<rule>.md`, and a `where` may hold ": " (a hook is found by its
# C++ context: `class NrSocket : public NrSocketBase {`). So the two failures the gate reads are cut where their `what` begins, and any
# other line at its first ": "; a split that does not rebuild the line is refused (parse_failure).
FAIL_LINES = tuple(re.compile(r"^FAIL " + head + r"\. Fix: (?P<fix>.+)\. Rule: docs/decisions/(?P<rule>.+)\.md$") for head in (
    r"(?P<where>.+?): (?P<what>C18: the hook .+)",
    r"(?P<where>tools/inventory\.json, the record of .+?): (?P<what>its `.+)",
    r"(?P<where>.+?): (?P<what>.+)"))
INVENTORY_WHERE = re.compile(r"^tools/inventory\.json, the record of (?P<file>.+) in (?P<folder>.+)$")
EMPTY_HAND_FIELD = re.compile(r"^its `(?:anchor|notes|hookable)` is ")
HOOK_WHERE = re.compile(r"^(?P<folder>.+)/hooks\.patch, (?P<file>[^,]+)(?:, .*)?$")
NO_CHURN_ROW = re.compile(r"^C18: the hook `.*`(?:, hunk (?P<hunk>\d+),)? has no churn row in tools/churn\.json$")
CHURN_FIX = "python tools/churn.py --source <repo with the tags> --write, then commit tools/churn.json"


def parse_failure(line: str):
    """The Failure that `check` printed as `line` (it runs in a subprocess, so only the text comes back), or None when the line is not
    the rendering of one: a line that does not rebuild into itself is not trusted."""
    for pattern in FAIL_LINES:
        found = pattern.match(line)
        if not found:
            continue
        try:
            rebuilt = Failure(found["where"], found["what"], found["fix"], found["rule"])      # the rule is read from the line: Failure, not fail()
        except ValueError:
            continue
        if str(rebuilt) == line:
            return rebuilt
    return None


class News:
    """What this export itself made new in the series, against the checkout it will replace: the only things the gate lets `check` miss.
      derived: (file, folder) of the inventory records the export derived (absent from the checkout's tools/inventory.json);
      moved:   (folder, file, hunk) of the hunks whose churn key is in the scratch hooks.patch files and not in the checkout's;
      files:   (folder, file) with a hunk in the scratch hooks.patch files and none in the checkout's (a whole file moved to a folder)."""

    def __init__(self, derived: set, moved: set, files: set):
        self.derived, self.moved, self.files = derived, moved, files

    @classmethod
    def of(cls, root: Path, tree: Path) -> "News":
        before, after = _churn_hunks(root), _churn_hunks(tree)
        keys_before = set(before.values())
        return cls(_inventory_keys(tree) - _inventory_keys(root),
                   {hunk for hunk, key in after.items() if key not in keys_before},
                   {(folder, path) for folder, path, _ in after} - {(folder, path) for folder, path, _ in before})


def _inventory_keys(root: Path) -> set:
    """(file, folder) of every record of tools/inventory.json under `root` (folder: the one of the record's feature, None if it has none)."""
    import layout
    try:
        records = json.loads((Path(root) / "tools" / "inventory.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    keys = set()
    for record in records:
        try:
            folder = layout.feature_folder(record["feature"])
        except KeyError:
            folder = None
        keys.add((record["file"], folder))
    return keys


def _churn_hunks(root: Path) -> dict:
    """(folder, file, hunk number) -> churn key, of the hooks.patch files of the series under `root` (tools/churn.py reads them)."""
    import churn
    try:
        return churn.hunk_keys(root)
    except (OSError, ValueError, KeyError):
        return {}


def tolerated(failure, news: News):
    """The `TODO after export` line for a failure of `check` that only a step after the export can close, or None when the gate keeps it
    red. Two classes, and only for what this export made:
      1. an empty hand field (`anchor`, `notes`, `hookable`) of an inventory record the export derived (`news.derived`): a human writes
         it;
      2. a hook with no churn row (C18) in a hunk the export moved or created (`news.moved`, or `news.files` for a whole file):
         tools/churn.py writes the rows and needs the release tags, which the export does not have.
    Anything else, among it an empty field of another record and a missing churn row of a hunk the export did not touch, is red."""
    record = INVENTORY_WHERE.match(failure.where)
    if record and EMPTY_HAND_FIELD.match(failure.what):
        if (record["file"], record["folder"]) in news.derived:
            return "TODO after export: %s: the record in %s: %s. Fix: %s" % (record["file"], record["folder"], failure.what, failure.fix)
        return None
    hook, row = HOOK_WHERE.match(failure.where), NO_CHURN_ROW.match(failure.what)
    if hook and row:
        mine = ((hook["folder"], hook["file"], int(row["hunk"])) in news.moved if row["hunk"]
                else (hook["folder"], hook["file"]) in news.files)
        if mine:
            return "TODO after export: %s: %s. Fix: %s" % (hook["file"], failure.what, CHURN_FIX)
    return None


def run_series_check(tree: Path, news: News | None = None) -> tuple:
    """engine.py check of the scratch tree, as the command line runs it: (problems, todo). Every `FAIL` line is a failure; with `news`,
    the ones `tolerated` names are TODO lines (printed by the gate), the rest are problems. A red exit with no failure line to show for
    it is a problem. check itself is the one the pull request runs: it refuses every one of these."""
    done = _run([sys.executable, "tools/engine.py", "check"], tree)
    lines = done.stdout.strip().splitlines()
    print("export gate: engine.py check: " + (lines or ["no output"])[0])
    if not done.returncode:
        return [], []
    problems, todo = [], []
    for line in lines:
        if not FAILURE_LINE.match(line):
            continue
        failure = parse_failure(line)
        text = tolerated(failure, news) if failure is not None and news is not None else None
        if text:
            todo.append(text)
        else:
            problems.append(failure if failure is not None else fail(
                "engine.py check", "it printed a line that is not the rendering of a failure of the series: %s" % line,
                "run python tools/engine.py check on the series and fix what it says, then run the export again", RULE))
    if done.stderr.strip() or (not problems and not todo):
        problems.append(fail("engine.py check", "the check of the series written is red and does not end in failure lines: %s" % (done.stdout + done.stderr).strip()[-1500:],
                             "run python tools/engine.py check on the series, fix what is red, then run the export again", RULE))
    return problems, todo


# A test of tools/tests that says again, over the whole series, what a tolerated failure of check says about its hooks: it is red for the same
# rows, so it is let through exactly when check's own failure is (a named test that is renamed or gone is a test of its own: see the tests).
RESTATES_CHURN = {"tools/tests/test_quiet_anchors.py::test_every_hook_of_the_series_has_its_churn":
                  ("it is red for the same hunks as check's C18 (no churn row)", CHURN_FIX)}
FAILED_TEST = re.compile(r"^FAILED (\S+)", re.MULTILINE)
SUMMARY_FAILED = re.compile(r"\b(\d+) (failed|error)")


def run_series_tests(tree: Path, tolerate: dict | None = None, todo: list | None = None) -> list:
    """The series' own tests, `python -m pytest -q -n auto tools/tests`, in the scratch tree: their root is the scratch tree.
    `tolerate` {test id: (why, fix)}: when the tests that are red are all in it (and nothing else is red, no error), they are TODO lines in `todo`
    and not problems."""
    if importlib.util.find_spec("xdist") is None:
        raise SystemExit(_with_next(fail(
            "python module xdist", "export refused: pytest-xdist is not installed, so tools/tests cannot run in parallel here",
            "install it with `python -m pip install pytest-xdist`", RULE), "run the export again"))
    done = _run([sys.executable, "-m", "pytest", "-q", "-n", "auto", "-p", "no:cacheprovider", "tools/tests"], tree)
    print("export gate: tools/tests: " + (done.stdout.strip().splitlines() or ["no output"])[-1])
    if not done.returncode:
        return []
    red = FAILED_TEST.findall(done.stdout)
    counted = {kind: int(n) for n, kind in SUMMARY_FAILED.findall((done.stdout.strip().splitlines() or [""])[-1])}
    if tolerate and red and set(red) <= set(tolerate) and counted == {"failed": len(red)} and not done.stderr.strip():
        for test in sorted(set(red)):
            if todo is not None:
                todo.append("TODO after export: %s: %s. Fix: %s" % (test, tolerate[test][0], tolerate[test][1]))
        return []
    return [fail("tools/tests", "a test of the series is red: %s" % (done.stdout + done.stderr).strip()[-1500:],
                 "run `python -m pytest -q tools/tests`, fix what is red, then run the export again", RULE)]


# The CI scripts' own tests (platform/ci/src/scripts, run by the job `tree` of checks.yml on the materialized tree) that hold what the export writes into
# platform/ci and into .github/workflows: the jobs of checks.yml and release.yml by name, and what a pull request starts. PR 79 added a job to checks.yml and
# only the tree job, an hour after the push, said that the two lists naming the jobs did not. Run on the scratch tree, when the export touched a CI file;
# the whole of scripts/ci/test_ci.py needs Linux (symlinks, sched_setaffinity, bash), these modules run anywhere and take under a second.
CI_SCRIPT_MODULES = ("test_release_checks", "test_release_builder")
CI_PATHS = ("platform/ci/", ".github/")
CI_RUNNER = (
    "import sys\n"
    "sys.path[:0] = ['scripts/ci', 'scripts']\n"
    "bad = 0\n"
    "for name in sys.argv[1:]:\n"
    "    cases = __import__(name).cases()\n"
    "    for case, ok in cases:\n"
    "        if not ok:\n"
    "            bad += 1\n"
    "            print('RED ' + name + ': ' + case)\n"
    "    print('%s: %d cases' % (name, len(cases)))\n"
    "sys.exit(1 if bad else 0)\n")


def run_ci_script_tests(tree: Path, written: list, removed: list) -> list:
    """The cases of CI_SCRIPT_MODULES on the scratch tree: a tree as the job `tree` makes it (scripts/ and .github/ of platform/ci/src at its root, the
    series in .series), built in a scratch directory. Not run when the export touched no file of platform/ci or .github, or the tree has no platform/ci/src."""
    touched = [p for p in list(written) + list(removed) if p.startswith(CI_PATHS)]
    src = tree / "platform" / "ci" / "src"
    if not touched or not (src / "scripts").is_dir():
        print("export gate: CI scripts' tests: no file of platform/ci or .github written, not run")
        return []
    home = Path(tempfile.mkdtemp(prefix="ci-scripts-"))
    started = time.time()
    try:
        for part in ("scripts", ".github"):
            if (src / part).is_dir():
                shutil.copytree(src / part, home / part, ignore=shutil.ignore_patterns("__pycache__"))
        series = home / ".series"
        for part in (".github", "tools"):
            if (tree / part).is_dir():
                shutil.copytree(tree / part, series / part, ignore=shutil.ignore_patterns("__pycache__", "tests"))
        for part in ("UPSTREAM.json", "SERIES"):
            if (tree / part).is_file():
                series.mkdir(exist_ok=True)
                shutil.copyfile(tree / part, series / part)
        done = _run([sys.executable, "-c", CI_RUNNER, *CI_SCRIPT_MODULES], home)
    finally:
        shutil.rmtree(home, ignore_errors=True)
    print("export gate: CI scripts' tests (%s): %s in %.1f s" % (", ".join(CI_SCRIPT_MODULES), (done.stdout.strip().splitlines() or ["no output"])[-1], time.time() - started))
    if done.returncode:
        found = [line[len("RED "):] for line in done.stdout.splitlines() if line.startswith("RED ")]
        return [fail("scripts/ci (the CI scripts' tests, %d file(s) of platform/ci or .github written)" % len(touched),
                     "a case is red: %s" % (case if found else (done.stdout + done.stderr).strip()[-800:]),
                     "fix the case or the file it holds (a job added to checks.yml is named in test_release_checks.py and test_release_builder.py), "
                     "in the source, then run the export again", RULE) for case in (found or [""])]
    return []


def run_engine_tree_tests(source: Path, head: str) -> list:
    """The tests of the source head on its whole tree (node tests, the engine's python tests): they test the head, not the series."""
    gate_tree()          # refuses, naming the variable, before anything else is looked at
    node = node_binary()
    tree = prepare_tree(source, head)
    return run_node_tests(tree, node) + run_tree_python_tests(tree)


def gate(source: Path, head: str, write: Callable[[Path], None], root: Path = ROOT) -> list:
    """The whole export: the engine tree's tests, then `write(scratch)` writes the series into a scratch copy of the checkout, the
    copy is checked and tested, and only if all is green does the checkout take what was written. Exits (SystemExit) on a red, with
    the checkout untouched, and ends with `next:` (repo-05).

    Green is green except for what only a step after the export can close, and only what this export made (News): an empty hand field
    of a record it derived, a missing churn row of a hunk it moved or created. Each is printed as `TODO after export: <file>: <what>.
    Fix: <command or hand step>` and returned (the list of lines); `check`, which the pull request runs, still refuses them."""
    again = "python tools/engine.py export --source %s --head %s" % ("<source>", head)
    try:
        problems = run_engine_tree_tests(source, head)
    except SystemExit as stopped:        # the tree or Node is missing: the stop of gate_tree()/node_binary(), then the way on (repo-05)
        raise SystemExit(_with_next(stopped.code, again)) from None
    if problems:
        raise SystemExit(_with_next(fail(
            "the source tree of %s" % head[:12], "export refused: red before the build job would have found it:\n  " + "\n  ".join(str(p) for p in problems),
            "fix the test in the source and commit it (the head is then another)", RULE), again))
    tree = scratch_series(root)
    try:
        before = _walk(tree)
        write(tree)
        written, removed = series_delta(tree, root, before)
        # the scratch tree has its own index: the tests that read `git ls-files` see the files the export wrote
        git("-C", str(tree), "add", "-A")
        problems, todo = run_series_check(tree, News.of(root, tree))
        # a test that restates a tolerated class is let through only when check's own failure of that class was (and no other C18 is red)
        mine = RESTATES_CHURN if any("no churn row" in t for t in todo) and not any("C18" in str(p) for p in problems) else None
        problems += run_series_tests(tree, mine, todo) + run_ci_script_tests(tree, written, removed)
        if problems:
            raise SystemExit(_with_next(fail(
                "the series the export wrote (%d files written, %d removed)" % (len(written), len(removed)),
                "export refused: red on the series it would write:\n  " + "\n  ".join(str(p) for p in problems),
                "fix the tool or the source so that what export writes passes check and tools/tests", RULE),
                again))
        replace_series(tree, root, written, removed)
        for line in todo:
            print(line)
        print("export gate: green on the series written; the checkout took %d files and dropped %d%s"
              % (len(written), len(removed), "; %d TODO after export (check is red on them until they are done)" % len(todo) if todo else ""))
        return todo
    except SystemExit as stopped:
        message = str(stopped.code)
        raise SystemExit(message if "\nnext: " in message else _with_next(message, again)) from None
    finally:
        remove_scratch(tree, root)
