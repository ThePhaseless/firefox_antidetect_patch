"""series-01: a Mozilla file may belong to several folders, each holding exactly the lines its marker names (tools/split.py).

A tiny Firefox-like repository (a base commit and a head commit, built in a temp directory) has one file that two folders touch:
a hunk that mixes both markers, a rewrite with one marker, a blank line inside a block, a multi-line form whose marker is on its last
line. The tests give every line to its folder, build the folders' patches in series order, apply them one after the other on the
base and get the head byte for byte, and break one thing at a time to see each red say where, what, how to fix it and which rule.

    python -m pytest tools/tests/test_split.py
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import split  # noqa: E402
from split import Block, assign  # noqa: E402

A = "fingerprint/a"
B = "network/b"
KNOWN = {A, B}
ORDER = [B, A]          # as in SERIES: network before fingerprint
ENV = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@users.noreply.github.com",
           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@users.noreply.github.com")

F = "dom/f.cpp"
G = "dom/g.cpp"
BASE_F = "".join("int v%d;\n" % n for n in range(1, 31))
HEAD_LINES = BASE_F.splitlines(keepends=True)
# a hunk that mixes both markers (one block of added lines)
HEAD_LINES[2:2] = ["StealthA(); // STEALTH-HOOK(fingerprint/a)\n", "StealthB(); // STEALTH-HOOK(network/b)\n"]
# a rewrite: one removed line, one added line, one marker
HEAD_LINES[HEAD_LINES.index("int v8;\n")] = "int v8 = StealthA(8); // STEALTH-HOOK(fingerprint/a)\n"
# a blank line, unmarked, inside a block of one folder's lines
HEAD_LINES[HEAD_LINES.index("int v14;\n") + 1:HEAD_LINES.index("int v14;\n") + 1] = [
    "StealthA(1); // STEALTH-HOOK(fingerprint/a)\n", "\n", "StealthA(2); // STEALTH-HOOK(fingerprint/a)\n"]
# a multi-line form whose marker is on the last line
HEAD_LINES[HEAD_LINES.index("int v20;\n") + 1:HEAD_LINES.index("int v20;\n") + 1] = [
    "if (StealthB()) {\n", "  return;\n", "}  // STEALTH-HOOK(network/b)\n"]
HEAD_F = "".join(HEAD_LINES)
BASE_G = "".join("int w%d;\n" % n for n in range(1, 31))
HEAD_G = BASE_G.replace("int w3;\n", "").replace("int w25;\n", "int w25; // STEALTH-HOOK(fingerprint/a)\n")


def git(repo, *args, input=None):
    return subprocess.run(["git", "-C", str(repo), "-c", "core.autocrlf=false", *args], check=True, capture_output=True, env=ENV,
                          input=input).stdout


@pytest.fixture(scope="module")
def repo():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "firefox"
        root.mkdir()
        git(root, "init", "-q")
        (root / "dom").mkdir()
        for name, data in ((F, BASE_F), (G, BASE_G)):
            (root / name).write_bytes(data.encode())
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "base")
        base = git(root, "rev-parse", "HEAD").decode().strip()
        for name, data in ((F, HEAD_F), (G, HEAD_G)):
            (root / name).write_bytes(data.encode())
        git(root, "commit", "-q", "-a", "-m", "head")
        head = git(root, "rev-parse", "HEAD").decode().strip()
        yield root, base, head


def blocks_of(repo, path):
    root, base, head = repo
    return split.diff_blocks(root, base, head, path)


def assignment(repo, path=F, **kw):
    return assign(path, blocks_of(repo, path), KNOWN, set(), **kw)


def apply_in_order(base_files: dict, patches: dict, order) -> dict:
    """The files after `git apply` of each folder's patch, in `order`, on a plain directory holding `base_files`."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for name, data in base_files.items():
            (work / name).parent.mkdir(parents=True, exist_ok=True)
            (work / name).write_bytes(data.encode())
        for folder in order:
            if folder in patches and patches[folder]:
                subprocess.run(["git", "apply", "--binary", "-"], cwd=work, input=patches[folder], check=True, capture_output=True, env=ENV)
        return {name: (work / name).read_bytes() for name in base_files}


# ------------------------------------------------------------------------------------------------ the owner of every line

def test_every_line_goes_to_the_folder_its_marker_names(repo):
    got = assignment(repo)
    assert got.problems == []
    # block 0: the hunk that mixes both tags
    assert got.blocks[0].new == ["StealthA(); // STEALTH-HOOK(fingerprint/a)", "StealthB(); // STEALTH-HOOK(network/b)"]
    assert got.added[0] == [A, B] and got.removed[0] is None
    # block 1: the rewrite, the removed line goes with the added one
    assert got.blocks[1].old == ["int v8;"] and got.removed[1] == A and got.added[1] == [A]
    # block 2: the unmarked blank line between two lines of A is A's
    assert got.blocks[2].new[1] == "" and got.added[2] == [A, A, A]
    # block 3: the multi-line form takes the marker of its last line
    assert got.added[3] == [B, B, B]
    assert got.folders == [A, B]


def test_a_blank_line_next_to_one_folder_goes_there_whatever_the_side():
    leading = assign("x.cpp", [Block(0, [], 0, ["", "f(); // STEALTH-HOOK(fingerprint/a)"])], KNOWN, set())
    trailing = assign("x.cpp", [Block(0, [], 0, ["g(); // STEALTH-HOOK(network/b)", ""])], KNOWN, set())
    same_both_sides = assign("x.cpp", [Block(0, [], 0, ["f(); // STEALTH-HOOK(fingerprint/a)", "", "", "g(); // STEALTH-HOOK(fingerprint/a)"])],
                             KNOWN, set())
    assert (leading.problems, leading.added) == ([], [[A, A]])
    assert (trailing.problems, trailing.added) == ([], [[B, B]])
    assert (same_both_sides.problems, same_both_sides.added) == ([], [[A, A, A, A]])


def test_a_removal_only_block_goes_to_the_one_folder_of_the_file(repo):
    got = assignment(repo, G)
    assert got.problems == []
    assert got.blocks[0].old == ["int w3;"] and got.blocks[0].new == []
    assert got.removed[0] == A and got.folders == [A]


def test_a_removal_only_block_goes_to_the_folder_its_hunk_agrees_on():
    near = [Block(2, ["x"], 2, []), Block(5, [], 4, ["h(); // STEALTH-HOOK(fingerprint/a)"]),
            Block(40, [], 40, ["k(); // STEALTH-HOOK(network/b)"])]
    got = assign("x.cpp", near, KNOWN, set())
    assert got.problems == [] and got.removed[0] == A


def test_a_removal_only_block_of_a_file_with_no_marker_takes_the_inventory_folder():
    removal = [Block(2, ["gone"], 2, [])]
    assert assign("x.cpp", removal, KNOWN, set(), file_folder=A).removed == [A]
    assert assign("x.cpp", removal, KNOWN, set()).problems


# ------------------------------------------------------------------------------------------------ the reds

def one(problems):
    assert len(problems) == 1, problems
    return str(problems[0])


def check_failure(text, where, what):
    assert text.startswith("FAIL %s: " % where), text
    assert what in text
    assert ". Fix: " in text and ". Rule: docs/decisions/series-01-export-is-the-only-writer.md" in text


def test_a_block_with_no_marker_is_red():
    text = one(assign("dom/x.cpp", [Block(3, [], 3, ["foo();", "bar();"])], KNOWN, set()).problems)
    check_failure(text, "dom/x.cpp:4", "untagged change: 2 added lines, none with a marker")
    assert "STEALTH-HOOK(<folder>)" in text


def test_a_line_between_two_folders_hooks_is_red():
    block = Block(3, [], 3, ["a(); // STEALTH-HOOK(fingerprint/a)", "", "b(); // STEALTH-HOOK(network/b)"])
    text = one(assign("dom/x.cpp", [block], KNOWN, set()).problems)
    check_failure(text, "dom/x.cpp:5", "a line between two folders' hooks: it follows a hook of fingerprint/a and precedes one of network/b")


def test_a_rewrite_owned_by_two_folders_is_red():
    block = Block(3, ["old();"], 3, ["a(); // STEALTH-HOOK(fingerprint/a)", "b(); // STEALTH-HOOK(network/b)"])
    text = one(assign("dom/x.cpp", [block], KNOWN, set()).problems)
    check_failure(text, "dom/x.cpp:4", "a rewrite owned by two folders: lines 4-4 of the tag are replaced by lines of fingerprint/a and network/b")
    assert "one folder's form" in text


def test_a_removal_owned_by_no_folder_is_red():
    far = [Block(2, ["gone"], 2, []), Block(40, [], 39, ["a(); // STEALTH-HOOK(fingerprint/a)"]),
           Block(80, [], 79, ["b(); // STEALTH-HOOK(network/b)"])]
    text = one(assign("dom/x.cpp", far, KNOWN, set()).problems)
    check_failure(text, "dom/x.cpp:3", "a removal owned by no folder: lines 3-3 of the tag are removed")
    assert "fingerprint/a, network/b" in text


def test_a_marker_naming_a_folder_the_series_does_not_have_is_red():
    block = Block(3, [], 3, ["a(); // STEALTH-HOOK(fingerprint/aa)"])
    text = one(assign("dom/x.cpp", [block], KNOWN, set()).problems)
    check_failure(text, "dom/x.cpp:4", "the marker names fingerprint/aa, which is not a folder of the series")
    assert "did you mean fingerprint/a?" in text


def test_a_marker_may_name_a_backport_folder():
    block = Block(3, [], 3, ["a(); // STEALTH-HOOK(fingerprint/a)"])
    assert assign("dom/x.cpp", [block], KNOWN, {A}).problems == []


# ------------------------------------------------------------------------------------------------ the patches

def patches_of(repo, order=ORDER):
    root, base, head = repo
    plan = {F: assignment(repo), G: assignment(repo, G)}
    return split.folder_patches(root, base, head, plan, order)


def test_each_folder_holds_exactly_its_lines(repo):
    patches = patches_of(repo)
    assert patches.problems == [] and patches.skipped == []
    assert set(patches) == KNOWN
    network, finger = patches[B].decode(), patches[A].decode()
    assert "diff --git a/dom/f.cpp b/dom/f.cpp\nindex " in network and "diff --git a/dom/g.cpp" not in network
    assert "+StealthB(); // STEALTH-HOOK(network/b)" in network and "+if (StealthB()) {" in network
    assert "StealthA" not in network and "-int v8;" not in network
    assert "+StealthA(); // STEALTH-HOOK(fingerprint/a)" in finger and "-int v8;" in finger
    assert "+\n" in finger                                                  # the blank line is A's
    assert "+StealthB()" not in finger and "+if (StealthB())" not in finger
    # B went first, so A's patch sees B's line as context
    assert " StealthB(); // STEALTH-HOOK(network/b)" in finger
    assert "diff --git a/dom/g.cpp b/dom/g.cpp" in finger                   # the file only A touches is whole in A


def test_the_folders_patches_in_series_order_give_the_head(repo):
    patches = patches_of(repo)
    got = apply_in_order({F: BASE_F, G: BASE_G}, patches, ORDER)
    assert got[F] == HEAD_F.encode() and got[G] == HEAD_G.encode()


def test_the_other_series_order_gives_the_head_too(repo):
    patches = patches_of(repo, [A, B])
    got = apply_in_order({F: BASE_F, G: BASE_G}, patches, [A, B])
    assert got[F] == HEAD_F.encode() and got[G] == HEAD_G.encode()
    assert patches[A] != patches_of(repo)[A]                                 # the second folder's context is the first's lines


def test_a_file_of_one_folder_has_the_patch_export_makes(repo):
    root, base, head = repo
    patches = split.folder_patches(root, base, head, {G: assignment(repo, G)}, ORDER)
    want = git(root, "diff", "--binary", "--full-index", "--no-renames", base, head, "--", G)
    assert patches[A] == want and list(patches) == [A]


def test_a_whole_file_goes_whole_to_its_folder(repo):
    root, base, head = repo
    patches = split.folder_patches(root, base, head, {F: B}, ORDER)
    assert patches[B] == git(root, "diff", "--binary", "--full-index", "--no-renames", base, head, "--", F)


def test_a_red_file_is_left_out_and_its_reds_are_reported(repo):
    root, base, head = repo
    red = assign(F, [Block(1, [], 1, ["x();"])], KNOWN, set())
    patches = split.folder_patches(root, base, head, {F: red, G: assignment(repo, G)}, ORDER)
    assert patches.skipped == [F] and len(patches.problems) == 1 and patches.problems[0].startswith("FAIL dom/f.cpp:2: untagged change")
    assert list(patches) == [A]


def test_lines_that_no_folder_took_make_the_file_red(repo):
    root, base, head = repo
    got = assignment(repo)
    got.added[0][1] = None                      # a line nobody owns, with no red from assign: the last check must catch it
    patches = split.folder_patches(root, base, head, {F: got}, ORDER)
    assert patches.skipped == [F] and not patches
    text = one(patches.problems)
    check_failure(text, F, "the folders' lines do not add up to the head: 1 line of the head taken by no folder (head lines 4)")


def test_a_folder_outside_the_series_order_is_red(repo):
    root, base, head = repo
    patches = split.folder_patches(root, base, head, {F: assignment(repo)}, [A])
    check_failure(one(patches.problems), F, "the folder network/b owns lines of the file and is not in the series order")


def test_the_source_repository_is_not_written(repo):
    root, base, head = repo
    before = git(root, "count-objects", "-v")
    patches_of(repo)
    assert git(root, "count-objects", "-v") == before
    assert git(root, "status", "--porcelain") == b""
