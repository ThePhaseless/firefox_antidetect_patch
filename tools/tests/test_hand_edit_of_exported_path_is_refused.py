"""series-01 / repo-06: a file under `<folder>/src/` is written by the export only. A hand edit of one (a line added to
platform/ci/src/.github/workflows/checks.yml, the edit a round made) leaves the bytes different from the sha256 the folder's MANIFEST.json
records, and `python tools/engine.py check` fails on that file and names the command that writes it again: `python tools/engine.py export`.

The fixture copies the series to a temporary directory (hard links where the volume allows, a copy otherwise: the edit replaces the file of
the copy and never writes through a link), gives the copy a git repository that reads the objects of this one and has this one's origin/main
(`check` compares the budgets with main's), applies the edit and runs the real `check` there.

    python -m pytest -q tools/tests/test_hand_edit_of_exported_path_is_refused.py
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
EDITED = "platform/ci/src/.github/workflows/checks.yml"
EXPORT = "python tools/engine.py export"
SKIP = {".git", "__pycache__", ".pytest_cache", "node_modules"}


def git(*args, cwd, check=True):
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert done.returncode == 0 or not check, "git %s failed: %s" % (" ".join(args), done.stderr)
    return done.stdout.strip()


def link_or_copy(src, dst):
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


@pytest.fixture(scope="module")
def series(tmp_path_factory):
    """A copy of this series that the test may change."""
    root = tmp_path_factory.mktemp("series")
    copy = root / "series"
    shutil.copytree(REPO, copy, ignore=lambda d, names: [n for n in names if n in SKIP], copy_function=link_or_copy)
    git("init", "-q", ".", cwd=copy)
    objects = Path(git("rev-parse", "--git-common-dir", cwd=REPO))
    objects = (objects if objects.is_absolute() else REPO / objects) / "objects"
    (copy / ".git" / "objects" / "info").mkdir(parents=True, exist_ok=True)
    (copy / ".git" / "objects" / "info" / "alternates").write_bytes((objects.as_posix() + "\n").encode("utf-8"))
    git("update-ref", "refs/remotes/origin/main", git("rev-parse", "refs/remotes/origin/main", cwd=REPO), cwd=copy)
    return copy


def check(root: Path):
    return subprocess.run([sys.executable, "tools/engine.py", "check"], cwd=root, capture_output=True, text=True, timeout=300)


def edit_by_hand(root: Path):
    """The hand edit of the round: a line added to the workflow file under src/, as an editor writes it (a new file, not a write through a link)."""
    path = root / EDITED
    lines = path.read_bytes().decode("utf-8").split("\n")
    lines.insert(1, "# a line added by hand")
    data = "\n".join(lines).encode("utf-8")
    path.unlink()
    path.write_bytes(data)


def test_the_unedited_series_passes_check(series):
    done = check(series)
    assert done.returncode == 0, done.stdout + done.stderr


def test_a_line_added_by_hand_under_src_fails_check_on_that_file_and_names_the_export(series):
    original = (REPO / EDITED).read_bytes()
    edit_by_hand(series)
    assert (REPO / EDITED).read_bytes() == original            # the copy is not linked to the repository
    done = check(series)
    out = done.stdout + done.stderr
    assert done.returncode != 0, out
    failing = [ln for ln in out.splitlines() if ln.startswith("FAIL " + EDITED)]
    assert len(failing) == 1, out
    assert "its bytes are not the sha256 its MANIFEST.json records" in failing[0]
    assert EXPORT in failing[0], failing[0]
