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
There is no switch to skip the gate.
"""
from __future__ import annotations

import glob
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from failure import fail  # noqa: E402

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


def run_series_check(tree: Path) -> list:
    """`tools/engine.py check` of the scratch tree, as the command line runs it."""
    done = _run([sys.executable, "tools/engine.py", "check"], tree)
    print("export gate: engine.py check: " + (done.stdout.strip().splitlines() or ["no output"])[0])
    if done.returncode:
        return [fail("engine.py check", "the series the export wrote breaks a rule: %s" % (done.stdout + done.stderr).strip()[-800:],
                     "fix the tool or the source so that what export writes passes check", RULE)]
    return []


def run_series_tests(tree: Path) -> list:
    """The series' own tests, `python -m pytest -q -n auto tools/tests`, in the scratch tree: their root is the scratch tree."""
    if importlib.util.find_spec("xdist") is None:
        raise SystemExit(_with_next(fail(
            "python module xdist", "export refused: pytest-xdist is not installed, so tools/tests cannot run in parallel here",
            "install it with `python -m pip install pytest-xdist`", RULE), "run the export again"))
    done = _run([sys.executable, "-m", "pytest", "-q", "-n", "auto", "-p", "no:cacheprovider", "tools/tests"], tree)
    print("export gate: tools/tests: " + (done.stdout.strip().splitlines() or ["no output"])[-1])
    if done.returncode:
        return [fail("tools/tests", "a test of the series is red: %s" % (done.stdout + done.stderr).strip()[-1500:],
                     "run `python -m pytest -q tools/tests`, fix what is red, then run the export again", RULE)]
    return []


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


def gate(source: Path, head: str, write: Callable[[Path], None], root: Path = ROOT) -> None:
    """The whole export: the engine tree's tests, then `write(scratch)` writes the series into a scratch copy of the checkout, the
    copy is checked and tested, and only if all is green does the checkout take what was written. Exits (SystemExit) on a red, with
    the checkout untouched."""
    again = "python tools/engine.py export --source <source> --head %s" % head
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
        problems = run_series_check(tree) + run_series_tests(tree) + run_ci_script_tests(tree, written, removed)
        if problems:
            raise SystemExit(_with_next(fail(
                "the series the export wrote (%d files written, %d removed)" % (len(written), len(removed)),
                "export refused: red on the series it would write:\n  " + "\n  ".join(str(p) for p in problems),
                "fix the tool or the source so that what export writes passes check and tools/tests", RULE),
                again))
        replace_series(tree, root, written, removed)
        print("export gate: green on the series written; the checkout took %d files and dropped %d" % (len(written), len(removed)))
    finally:
        remove_scratch(tree, root)
