"""The series rule «export commits are named export:» (scripts/ci/export_commit_names.py), on small git repositories made here with real commits.

    python -m pytest scripts/ci/test_export_commit_names.py

Run by scripts/ci/test_ci.py through cases(), like the other modules of this folder.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import export_commit_names  # noqa: E402

SCRIPT = HERE / "export_commit_names.py"
IDENTITY = ["-c", "user.name=t", "-c", "user.email=t@users.noreply.github.com", "-c", "commit.gpgsign=false"]


def git(repo, *args):
    done = subprocess.run(["git", "-C", str(repo), *IDENTITY, *args], capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def run_script(repo, rng):
    return subprocess.run([sys.executable, str(SCRIPT), "--repo", str(repo), "--range", rng], capture_output=True, text=True, encoding="utf-8")


def make_repo(root):
    repo = Path(root)
    git(repo, "init", "-q", "-b", "main")
    (repo / "SERIES").write_text("base\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    return repo


def commit(repo, subject, *paths):
    for path in paths:
        target = Path(repo) / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(subject + "\n" + path + "\n" + git(repo, "rev-parse", "HEAD"), encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", subject)


def one(subject, *paths):
    """A repository with a base commit and one commit on top; (exit code, stdout) of the script on that commit."""
    with tempfile.TemporaryDirectory() as root:
        repo = make_repo(root)
        commit(repo, subject, *paths)
        done = run_script(repo, "HEAD~1..HEAD")
        return done.returncode, done.stdout


def test_a_commit_touching_only_exported_paths_is_red_without_export():
    code, out = one("fix x", "automation/x/src/a.js")
    assert code == 1 and out.count("FAIL ") == 1, out
    assert '"fix x"' in out and "automation/x/src/a.js" in out and "Fix:" in out and "Rule: export commits are named export:" in out, out


def test_the_same_commit_named_export_is_green():
    code, out = one("export: fix x", "automation/x/src/a.js")
    assert code == 0 and out.strip() == "OK 1 commits", out


def test_a_red_of_a_names_up_to_three_paths():
    code, out = one("fix x", *("platform/ci/src/f%d.py" % i for i in range(5)))
    assert code == 1 and out.count("platform/ci/src/f") == 3 and "2 more" in out, out


def test_an_export_commit_that_touches_a_series_own_path_is_red():
    code, out = one("export: y", "automation/x/src/a.js", "tools/foo.py")
    assert code == 1 and out.count("FAIL ") == 1 and "tools/foo.py" in out and "automation/x/src/a.js" not in out, out
    code, out = one("export: only own", "docs/a.md")
    assert code == 1 and "docs/a.md" in out, out


def test_manifest_json_and_hooks_patch_at_any_depth_are_exported():
    for path in ("MANIFEST.json", "automation/juggler/MANIFEST.json", "a/b/c/hooks.patch", "hooks.patch"):
        assert export_commit_names.is_exported(path), path
        assert one("export: m", path)[0] == 0, path
        assert one("m", path)[0] == 1, path


def test_the_exported_paths_are_src_under_a_folder_and_nothing_else():
    for path in ("automation/juggler/src/x.js", "platform/ci/src/scripts/ci/a.py", "a/src/b", "a/b/src/c/d"):
        assert export_commit_names.is_exported(path), path
    for path in ("tools/engine.py", "docs/a.md", ".github/workflows/checks.yml", "SERIES", "UPSTREAM.json", "src/a.py", "a/src", "a/srcs/b", "a/MANIFEST.jsonl"):
        assert not export_commit_names.is_exported(path), path


def test_a_commit_touching_src_and_tools_without_export_is_green():
    code, out = one("fix both", "automation/x/src/a.js", "tools/foo.py")
    assert code == 0 and out.strip() == "OK 1 commits", out


def test_a_commit_touching_only_series_own_paths_without_export_is_green():
    code, out = one("docs", "docs/a.md")
    assert code == 0, out


def test_merges_are_skipped():
    with tempfile.TemporaryDirectory() as root:
        repo = make_repo(root)
        base = git(repo, "rev-parse", "HEAD")
        git(repo, "checkout", "-q", "-b", "side")
        commit(repo, "export: side", "automation/x/src/a.js")
        git(repo, "checkout", "-q", "main")
        commit(repo, "main own", "docs/a.md")
        git(repo, "merge", "-q", "--no-ff", "-m", "export: merge, named like an export and merging series-own files", "side")
        assert len(git(repo, "rev-list", "--merges", "-n1", "HEAD")) == 40
        done = run_script(repo, base + "..HEAD")
        assert done.returncode == 0 and done.stdout.strip() == "OK 2 commits", done.stdout


def test_an_empty_commit_is_skipped():
    with tempfile.TemporaryDirectory() as root:
        repo = make_repo(root)
        git(repo, "commit", "-q", "--allow-empty", "-m", "export: nothing")
        done = run_script(repo, "HEAD~1..HEAD")
        assert done.returncode == 0 and done.stdout.strip() == "OK 1 commits", done.stdout


def test_a_bad_commit_among_good_ones_is_the_only_line():
    with tempfile.TemporaryDirectory() as root:
        repo = make_repo(root)
        base = git(repo, "rev-parse", "HEAD")
        commit(repo, "export: good", "automation/x/src/a.js")
        commit(repo, "bad", "automation/x/src/b.js")
        commit(repo, "own", "tools/t.py")
        done = run_script(repo, base + "..HEAD")
        assert done.returncode == 1 and done.stdout.count("FAIL ") == 1 and '"bad"' in done.stdout, done.stdout


def test_an_unreadable_range_or_repository_exits_two():
    with tempfile.TemporaryDirectory() as root:
        repo = make_repo(root)
        for rng in ("nosuchref..HEAD", "HEAD", "..HEAD"):
            done = run_script(repo, rng)
            assert done.returncode == 2 and "OK" not in done.stdout, (rng, done.returncode, done.stderr)
        assert run_script(os.path.join(root, "missing"), "a..b").returncode == 2
        done = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, encoding="utf-8")
        assert done.returncode == 2


def cases() -> list:
    """The tests above as (name, ok) pairs, for scripts/ci/test_ci.py, which the plan job runs (a test that no job runs is deleted)."""
    found = []
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and callable(function):
            try:
                function()
                ok = True
            except AssertionError:
                ok = False
            found.append(("export commit names: " + name[len("test_"):].replace("_", " "), ok))
    return found


if __name__ == "__main__":
    results = cases()
    for label, ok in results:
        print(("ok    " if ok else "FAIL  ") + label)
    print("%d/%d cases as expected" % (sum(ok for _, ok in results), len(results)))
    sys.exit(0 if all(ok for _, ok in results) else 1)
