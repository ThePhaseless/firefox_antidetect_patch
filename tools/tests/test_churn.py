"""The churn of the series' hunks (tools/churn.py), each rule shown on a small repository built here.

Mozilla's releases are four tags of a few files; the series is one or two folders with a hooks.patch. The tests break one thing at a time:

  * a region is walked through the lines Mozilla inserted and deleted before it (a change that is only near by the wrong coordinates is not counted);
  * a hunk that inserts a line (no line of Mozilla touched) has its two neighbours, plus 3 lines each side, as its region, and the edge is exact;
  * a file that appears in a later release counts as changed in the release where it appears;
  * a hunk of a later folder is placed by Mozilla's lines, not by the lines an earlier folder added to the file;
  * the file is the same bytes for the same input, wherever it is built;
  * the band is the churn the constant says, and the file says which;
  * every release tag is recorded with its commit, and a tag of the source that resolves to another commit is red (compute, --check, --fetch);
  * `--check` is red unless the committed file is what the series gives now, byte for byte, and names the hunks that differ;
  * `--fetch` puts the tags a file lists into a repository, one commit deep and without file content, then the content of the files the series
    patches and nothing else; the cache key is the commits and the set of files, not the names of the tags;
  * a file of the series that the repository was not fetched for is red (where / what / fix / rule), never absent and never a churn of 0;
  * the numbers of three hunks of the real series at the base 159 equal the ones measured with the first tool, and the committed file is what the
    series gives (skipped when the release tags are not in the repository named by CHURN_TAGS_REPO; with CHURN_REQUIRE_TAGS=1, the round that
    runs it, their absence is a failure, not a skip).

    python -m pytest tools/tests/test_churn.py
"""
import difflib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import churn  # noqa: E402

TAGS = ["FIREFOX_151_0_RELEASE", "FIREFOX_152_0_RELEASE", "FIREFOX_153_0_RELEASE", "FIREFOX_154_0_RELEASE"]
BASE = TAGS[-1]
IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def git(repo, *args):
    done = subprocess.run(["git", "-C", str(repo), "-c", "core.autocrlf=false", *args], capture_output=True,
                          env=dict(os.environ, **IDENTITY))
    assert done.returncode == 0, done.stderr.decode()
    return done.stdout


def numbered(n, prefix="line"):
    return ["%s %d" % (prefix, i) for i in range(1, n + 1)]


def releases():
    """a.txt: R1 40 lines; R2 five lines inserted at the top; R3 'line 20' edited; R4 (the base) the first three lines deleted.
    b.txt: appears in R3. c.txt: appears in R4. d.txt: line 10 edited in R2 and again in R3, as it is in R4."""
    a1 = numbered(40)
    a2 = numbered(5, "new") + a1
    a3 = [("line 20 edited" if l == "line 20" else l) for l in a2]
    a4 = a3[3:]
    d1 = numbered(20, "d")
    d2 = [("d 10 first" if l == "d 10" else l) for l in d1]
    d3 = [("d 10 second" if l == "d 10 first" else l) for l in d2]
    return [
        {"a.txt": a1, "d.txt": d1},
        {"a.txt": a2, "d.txt": d2},
        {"a.txt": a3, "d.txt": d3, "b.txt": numbered(12, "b")},
        {"a.txt": a4, "d.txt": d3, "b.txt": numbered(12, "b"), "c.txt": numbered(12, "c")},
    ]


@pytest.fixture()
def source(tmp_path):
    repo = tmp_path / "mozilla"
    repo.mkdir()
    git(repo, "init", "-q")
    for tag, files in zip(TAGS, releases()):
        for old in repo.glob("*.txt"):
            old.unlink()
        for name, lines in files.items():
            (repo / name).write_bytes(("\n".join(lines) + "\n").encode())
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "--allow-empty", "-m", tag)
        git(repo, "tag", tag)
    return repo


def patch_text(name, old, new, context=3):
    body = list(difflib.unified_diff(old, new, "a/" + name, "b/" + name, n=context, lineterm=""))
    return "diff --git a/%s b/%s\n%s\n" % (name, name, "\n".join(body))


def series(root, folders):
    """folders: [(name, patch text)] in order -> a series root."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "SERIES").write_text("\n".join(n for n, _ in folders) + "\n", encoding="utf-8")
    for name, text in folders:
        (root / name).mkdir(parents=True, exist_ok=True)
        (root / name / "hooks.patch").write_bytes(text.encode())
    return root


def edit(lines, number, text):
    out = list(lines)
    out[number - 1] = text
    return out


def blob_of(lines):
    return lambda p: ("\n".join(lines) + "\n").encode() if p in ("a.txt", "d.txt") else None


def by_hunk(data):
    return {(h["folder"], h["file"], h["hunk"]): h for h in data["hooks"]}


def run(root, source):
    return churn.compute(root, source, BASE, TAGS)


A4 = releases()[3]["a.txt"]
D4 = releases()[3]["d.txt"]


def test_a_region_is_walked_through_the_lines_mozilla_inserted_and_deleted_before_it(tmp_path, source):
    # in the base "line 20 edited" (Mozilla's R3 edit) is line 22; "line 22" is line 24 (near), "line 25" is line 27 (5 away: not near)
    assert A4[21] == "line 20 edited" and A4[23] == "line 22" and A4[26] == "line 25"
    near = patch_text("a.txt", A4, edit(A4, 24, "line 22 hook"))
    far = patch_text("a.txt", A4, edit(A4, 27, "line 25 hook"))
    data = run(series(tmp_path / "s", [("fingerprint/near", near), ("fingerprint/far", far)]), source)
    h = by_hunk(data)
    assert h[("fingerprint/near", "a.txt", 1)]["which"] == ["153"] and h[("fingerprint/near", "a.txt", 1)]["churn"] == 1
    assert h[("fingerprint/far", "a.txt", 1)]["which"] == [] and h[("fingerprint/far", "a.txt", 1)]["churn"] == 0
    # the R1 -> R2 insertion at the top and the R3 -> R4 deletion at the top are not "near" the lines they shift
    assert all(x["churn"] <= 1 for x in data["hooks"])


def test_the_edge_of_the_region_is_three_lines(tmp_path, source):
    # Mozilla's edit is base line 22. A rewrite of line 25 touches 25 and the line after it (the first tool's span), so its region is 22..29 (near); of line 26, 23..30 (not)
    on25 = patch_text("a.txt", A4, edit(A4, 25, "x"))
    on26 = patch_text("a.txt", A4, edit(A4, 26, "x"))
    h = by_hunk(run(series(tmp_path / "s", [("fingerprint/a", on25), ("fingerprint/b", on26)]), source))
    assert h[("fingerprint/a", "a.txt", 1)]["churn"] == 1
    assert h[("fingerprint/b", "a.txt", 1)]["churn"] == 0


def test_an_insertion_hunk_has_its_two_neighbours_as_the_region(tmp_path, source):
    # an insertion between base lines 25 and 26: neighbours 25, 26, region 22..29, reaches Mozilla's edit of line 22; between 26 and 27: 23..30, does not
    after25 = patch_text("a.txt", A4, A4[:25] + ["hook"] + A4[25:], context=0)
    after26 = patch_text("a.txt", A4, A4[:26] + ["hook"] + A4[26:], context=0)
    assert "@@ -25,0 +26 @@" in after25
    one = series(tmp_path / "one", [("fingerprint/a", after25)])
    two = series(tmp_path / "two", [("fingerprint/b", after26)])
    assert [r["region"] for r in churn.regions(one, blob_of(A4))] == [(22, 29)]
    assert [r["region"] for r in churn.regions(two, blob_of(A4))] == [(23, 30)]
    assert run(one, source)["hooks"][0]["which"] == ["153"]
    assert run(two, source)["hooks"][0]["which"] == []


def test_a_file_that_appears_in_a_later_release_is_changed_where_it_appears(tmp_path, source):
    b = releases()[3]["b.txt"]
    c = releases()[3]["c.txt"]
    root = series(tmp_path / "s", [("fingerprint/b", patch_text("b.txt", b, edit(b, 6, "x"))),
                                   ("fingerprint/c", patch_text("c.txt", c, edit(c, 6, "x")))])
    h = by_hunk(run(root, source))
    assert h[("fingerprint/b", "b.txt", 1)]["which"] == ["153"]      # absent in 151 and 152, new in 153
    assert h[("fingerprint/c", "c.txt", 1)]["which"] == ["154"]      # new in the last interval


def test_a_file_the_series_adds_is_not_churn(tmp_path, source):
    new = "diff --git a/e.txt b/e.txt\nnew file mode 100644\n--- /dev/null\n+++ b/e.txt\n@@ -0,0 +1,2 @@\n+one\n+two\n"
    warned = []
    data = churn.compute(series(tmp_path / "s", [("fingerprint/e", new)]), source, BASE, TAGS, warned)
    assert data["hooks"][0]["churn"] == 0 and data["hooks"][0]["which"] == []
    assert any("not in the base" in w for w in warned)


def test_a_later_folder_is_placed_by_mozillas_lines_not_by_the_lines_an_earlier_folder_added(tmp_path, source):
    after_first = ["hook one", "hook two"] + A4
    first = patch_text("a.txt", A4, after_first)
    # layered line 27 is Mozilla's line 25, its region 22..29; Mozilla's edit of line 22 is in it (the offset of 2 must not move it to 24..31)
    second = patch_text("a.txt", after_first, edit(after_first, 27, "x"))
    root = series(tmp_path / "s", [("fingerprint/one", first), ("fingerprint/two", second)])
    found = churn.regions(root, blob_of(A4))
    assert [(r["folder"], r["region"]) for r in found] == [("fingerprint/one", (1, 4)), ("fingerprint/two", (22, 29))]
    h = by_hunk(run(root, source))
    assert h[("fingerprint/two", "a.txt", 1)]["which"] == ["153"]


def test_the_edges_of_a_diff_between_releases():
    # (a, b, c, d) = -a,b +c,d ; Mozilla deleted old lines 5..6 (d == 0, the new side sits after line 4)
    deleted = [(5, 2, 4, 0)]
    assert churn.overlaps_new(deleted, 5, 8) and churn.overlaps_new(deleted, 1, 4)
    assert not churn.overlaps_new(deleted, 6, 8) and not churn.overlaps_new(deleted, 1, 3)
    assert churn.overlaps_new([(10, 0, 11, 2)], 12, 14) and not churn.overlaps_new([(10, 0, 11, 2)], 13, 14)
    assert churn.map_new_to_old([(0, 0, 1, 5)], 27, 33) == (22, 28)                  # five lines inserted at the top
    assert churn.map_new_to_old([(1, 3, 0, 0)], 21, 27) == (24, 30)                  # three lines deleted at the top


def test_the_file_is_the_same_bytes_wherever_it_is_built(tmp_path, source):
    folders = [("fingerprint/a", patch_text("a.txt", A4, edit(A4, 24, "x"))),
               ("network/b", patch_text("d.txt", D4, edit(D4, 10, "x")))]
    one = churn.render(run(series(tmp_path / "one", folders), source))
    two = churn.render(run(series(tmp_path / "elsewhere" / "deeper", folders), source))
    assert one == two
    assert one.endswith(b"\n") and b"\r" not in one
    hooks = json.loads(one)["hooks"]
    assert hooks == sorted(hooks, key=lambda h: (h["folder"], h["file"], h["hunk"]))
    assert list(hooks[0]) == ["key", "folder", "file", "hunk", "churn", "which"]


def test_the_band_is_a_churn_of_two_and_the_file_says_so(tmp_path, source, monkeypatch):
    # d.txt line 10 was edited in 152 and in 153: a hunk near it has churn 2
    root = series(tmp_path / "s", [("fingerprint/d", patch_text("d.txt", D4, edit(D4, 11, "x"))),
                                   ("fingerprint/a", patch_text("a.txt", A4, edit(A4, 24, "x")))])
    data = run(root, source)
    h = by_hunk(data)
    assert data["band"] == churn.BAND_MIN_CHURN == 2
    assert h[("fingerprint/d", "d.txt", 1)]["which"] == ["152", "153"] and churn.in_band(2)
    assert h[("fingerprint/a", "a.txt", 1)]["churn"] == 1 and not churn.in_band(1)
    assert churn.summary(data).splitlines()[-1] == "in the band (churn >= 2): 1"
    monkeypatch.setattr(churn, "BAND_MIN_CHURN", 3)
    again = run(root, source)
    assert again["band"] == 3 and not churn.in_band(2)
    assert churn.summary(again).splitlines()[-1] == "in the band (churn >= 3): 0"


def test_a_hunk_that_moved_keeps_its_key(tmp_path):
    # the same change one line further down the file: the key has no line number
    one = series(tmp_path / "one", [("fingerprint/a", patch_text("a.txt", A4, edit(A4, 30, "x")))])
    moved = ["pad"] + A4
    two = series(tmp_path / "two", [("fingerprint/a", patch_text("a.txt", moved, edit(moved, 31, "x")))])
    k1 = [r["key"] for r in churn.regions(one, blob_of(A4))]
    k2 = [r["key"] for r in churn.regions(two, blob_of(moved))]
    assert k1 == k2 and k1[0].startswith("H|fingerprint/a|a.txt|")


def test_a_missing_tag_is_named_with_the_way_to_fetch_it(tmp_path, source, capsys):
    root = series(tmp_path / "s", [("fingerprint/a", patch_text("a.txt", A4, edit(A4, 24, "x")))])
    with pytest.raises(churn.ChurnError) as err:
        churn.compute(root, source, BASE, ["FIREFOX_150_0_RELEASE"] + TAGS)
    assert "FIREFOX_150_0_RELEASE" in str(err.value) and "fetch --depth=1" in str(err.value)
    assert "FIREFOX_151_0_RELEASE" not in str(err.value).split("\n")[0]
    code = churn.main(["--source", str(source), "--base", BASE, "--series", str(root), "--releases", "FIREFOX_150_0_RELEASE," + BASE])
    assert code == 2 and "FIREFOX_150_0_RELEASE" in capsys.readouterr().err
    with pytest.raises(churn.ChurnError):
        churn.compute(root, source, BASE, TAGS[:2])          # the chain must end with the base


def test_the_default_chain_is_the_eight_releases_before_the_base():
    assert churn.default_releases("FIREFOX_159_0_RELEASE") == ["FIREFOX_%d_0_RELEASE" % n for n in range(151, 160)]
    assert [churn.release_label(t) for t in ("FIREFOX_152_0_RELEASE", "FIREFOX_160_0_1_RELEASE")] == ["152", "160.0.1"]


# --------------------------------------------------------------------------- the commits of the tags, --check, --fetch
def one_hook_series(tmp_path):
    """A series root with two hooks, a UPSTREAM.json for the fixture's base, and no churn.json yet."""
    root = series(tmp_path / "s", [("fingerprint/a", patch_text("a.txt", A4, edit(A4, 24, "x"))),
                                   ("network/b", patch_text("d.txt", D4, edit(D4, 11, "x")))])
    (root / "UPSTREAM.json").write_text(json.dumps({"mozilla_tag": BASE, "mozilla_repository": "unused"}), encoding="utf-8")
    return root


def write_churn(root, source):
    assert churn.main(["--source", str(source), "--base", BASE, "--releases", ",".join(TAGS), "--series", str(root), "--write"]) == 0
    return root / "tools" / "churn.json"


def test_every_tag_is_recorded_with_its_commit(tmp_path, source):
    data = run(one_hook_series(tmp_path), source)
    heads = {t: git(source, "rev-parse", t + "^{commit}").decode().strip() for t in TAGS}
    assert data["releases"] == [{"tag": t, "commit": heads[t]} for t in TAGS]
    assert churn.recorded(data) == heads


def test_a_tag_that_resolves_to_another_commit_is_red(tmp_path, source, capsys):
    root = one_hook_series(tmp_path)
    good = run(root, source)
    wrong = churn.recorded(good)
    wrong[TAGS[1]] = "f" * 40
    with pytest.raises(churn.ChurnError) as err:
        churn.compute(root, source, BASE, TAGS, None, wrong)
    text = str(err.value)
    assert TAGS[1] in text and "f" * 40 in text and good["releases"][1]["commit"] in text
    assert TAGS[0] not in text                      # only the tag that is not the one recorded
    # the same from the command line: --check against a file that records another commit, and a --write over it
    path = write_churn(root, source)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["releases"][1]["commit"] = "f" * 40
    path.write_bytes(churn.render(data))
    capsys.readouterr()
    assert churn.main(["--source", str(source), "--check", "--series", str(root)]) == 2
    assert TAGS[1] in capsys.readouterr().err
    assert churn.main(["--source", str(source), "--base", BASE, "--releases", ",".join(TAGS), "--series", str(root), "--write"]) == 2
    assert json.loads(path.read_text(encoding="utf-8"))["releases"][1]["commit"] == "f" * 40       # nothing was overwritten


def test_check_is_green_on_a_file_that_is_what_the_series_gives(tmp_path, source, capsys):
    root = one_hook_series(tmp_path)
    write_churn(root, source)
    assert churn.main(["--source", str(source), "--check", "--series", str(root)]) == 0
    assert "ok" in capsys.readouterr().out


def test_check_is_red_on_a_stale_file_and_names_the_hunks(tmp_path, source, capsys):
    root = one_hook_series(tmp_path)
    path = write_churn(root, source)
    # (1) a number of the file edited: the hunk is named with both values
    data = json.loads(path.read_text(encoding="utf-8"))
    row = [h for h in data["hooks"] if h["file"] == "d.txt"][0]
    row["churn"], row["which"] = 0, []
    path.write_bytes(churn.render(data))
    capsys.readouterr()
    assert churn.main(["--source", str(source), "--check", "--series", str(root)]) == 1
    err = capsys.readouterr().err
    assert "network/b d.txt hunk 1: churn 0 [] in tools/churn.json, churn 2 ['152', '153'] now" in err
    assert "a.txt" not in err and "docs/decisions/port-07-quiet-anchors.md" in err and "--write" in err
    # (2) the series moved on: a hunk the file does not have, a hunk it has that is gone
    write_churn(root, source)
    newer = series(tmp_path / "t", [("fingerprint/a", patch_text("a.txt", A4, edit(A4, 24, "x"))),
                                    ("network/b", patch_text("d.txt", D4, edit(D4, 11, "changed")))])
    (newer / "UPSTREAM.json").write_bytes((root / "UPSTREAM.json").read_bytes())
    (newer / "tools").mkdir()
    (newer / "tools" / "churn.json").write_bytes(path.read_bytes())
    assert churn.main(["--source", str(source), "--check", "--series", str(newer)]) == 1
    err = capsys.readouterr().err
    assert "network/b d.txt hunk 1: in tools/churn.json (churn 2), no longer in the series" in err
    assert "network/b d.txt hunk 1: in the series (churn 2), not in tools/churn.json" in err


def test_check_is_red_on_bytes_alone(tmp_path, source, capsys):
    root = one_hook_series(tmp_path)
    path = write_churn(root, source)
    path.write_bytes(json.dumps(json.loads(path.read_text(encoding="utf-8")), indent=2).encode() + b"\n")      # the same data, another layout
    capsys.readouterr()
    assert churn.main(["--source", str(source), "--check", "--series", str(root)]) == 1
    assert "the bytes differ and no hunk does" in capsys.readouterr().err


def test_check_is_red_when_the_file_is_for_another_base(tmp_path, source, capsys):
    root = one_hook_series(tmp_path)
    write_churn(root, source)
    (root / "UPSTREAM.json").write_text(json.dumps({"mozilla_tag": "FIREFOX_155_0_RELEASE"}), encoding="utf-8")
    assert churn.main(["--source", str(source), "--check", "--series", str(root)]) == 1
    assert "tools/churn.json: base: the file is for %s, the series is on FIREFOX_155_0_RELEASE" % BASE in capsys.readouterr().err


def test_check_is_red_when_the_file_is_missing(tmp_path, source, capsys):
    root = one_hook_series(tmp_path)
    assert churn.main(["--source", str(source), "--check", "--series", str(root)]) == 2
    assert "tools/churn.json: the file is missing" in capsys.readouterr().err


def offer_partial_clone(source):
    """What Mozilla's repository does (GitHub): serve a filter and a file asked for by its sha."""
    git(source, "config", "uploadpack.allowFilter", "true")
    git(source, "config", "uploadpack.allowAnySHA1InWant", "true")


def test_fetch_puts_the_listed_tags_into_a_repository_and_checks_each_commit(tmp_path, source, capsys):
    offer_partial_clone(source)
    root = one_hook_series(tmp_path)
    path = write_churn(root, source)
    (root / "UPSTREAM.json").write_text(json.dumps({"mozilla_tag": BASE, "mozilla_repository": source.as_uri()}), encoding="utf-8")
    into = tmp_path / "cache" / "tags.git"
    capsys.readouterr()
    assert churn.main(["--source", str(into), "--fetch", "--series", str(root)]) == 0
    assert all(churn.commit_of(into, t) == git(source, "rev-parse", t + "^{commit}").decode().strip() for t in TAGS)
    assert capsys.readouterr().out.count("fetched in") == len(TAGS) + 1        # the nine tags (here four), then the files
    # the content of the files the series patches is there, the content of the others is not: the repository stays small
    patched = {"a.txt", "d.txt"}
    wanted = {sha for (tag, name), sha in churn.tree_blobs(into, TAGS, ["a.txt", "b.txt", "c.txt", "d.txt"]).items() if name in patched}
    others = {sha for (tag, name), sha in churn.tree_blobs(into, TAGS, ["a.txt", "b.txt", "c.txt", "d.txt"]).items() if name not in patched}
    assert wanted and others and churn.missing_blobs(into, wanted) == [] and set(churn.missing_blobs(into, others)) == others
    # a second run (a restored cache) fetches nothing, and the repository is the one the check reads
    assert churn.main(["--source", str(into), "--fetch", "--series", str(root)]) == 0
    again = capsys.readouterr().out
    assert again.count("in the repository") == len(TAGS) and "0 fetched" in again
    assert churn.main(["--source", str(into), "--check", "--series", str(root)]) == 0
    # a file that records another commit: the fetch fetches the tag and refuses it
    data = json.loads(path.read_text(encoding="utf-8"))
    data["releases"][2]["commit"] = "e" * 40
    path.write_bytes(churn.render(data))
    other = tmp_path / "cold.git"
    assert churn.main(["--source", str(other), "--fetch", "--series", str(root)]) == 2
    assert TAGS[2] in capsys.readouterr().err
    # a cache that holds a tag at another commit is refused too
    assert churn.main(["--source", str(into), "--fetch", "--series", str(root)]) == 2


def test_a_file_the_repository_was_not_fetched_for_is_red_never_absent_never_zero(tmp_path, source, capsys):
    """The files the series patches are the set the repository is fetched for. A hook file outside that set (the repository was
    fetched before the hook was added) has its tree entry and no content: the churn must stop and say so, where / what / fix / rule,
    and not read it as a file that is not there (a change in every release) nor as a file that never changed (churn 0)."""
    offer_partial_clone(source)
    root = one_hook_series(tmp_path)
    path = write_churn(root, source)
    (root / "UPSTREAM.json").write_text(json.dumps({"mozilla_tag": BASE, "mozilla_repository": source.as_uri()}), encoding="utf-8")
    into = tmp_path / "old-cache.git"
    churn.fetch(into, json.loads(path.read_text(encoding="utf-8")), ["a.txt"], source.as_uri(), say=lambda *_: None)       # d.txt was not a hook file then
    capsys.readouterr()
    assert churn.main(["--source", str(into), "--check", "--series", str(root)]) == 2
    err = capsys.readouterr().err
    assert "no content in the repository" in err and "d.txt" in err and TAGS[0] in err           # where and what: the files, the tag
    assert "Fix: python tools/churn.py --source" in err and "--fetch" in err                     # fix
    assert "Rule: docs/decisions/port-07-quiet-anchors.md" in err                                # rule
    assert "a.txt" not in err.split("first:")[1].split("):")[0]
    with pytest.raises(churn.ChurnError):
        run(root, into)                                       # the compute too: no number is produced
    with pytest.raises(churn.ChurnError):
        churn.Releases(into, TAGS, ["a.txt", "d.txt"])
    # the fetch for the right set repairs it, and the numbers are the ones of the whole repository
    assert churn.main(["--source", str(into), "--fetch", "--series", str(root)]) == 0
    assert churn.main(["--source", str(into), "--check", "--series", str(root)]) == 0


def test_the_cache_key_is_the_commits_and_the_files_not_the_names_of_the_tags(tmp_path, source, capsys):
    data = run(one_hook_series(tmp_path), source)
    files = ["a.txt", "d.txt"]
    renamed = json.loads(json.dumps(data))
    for r in renamed["releases"]:
        r["tag"] = r["tag"].lower()
    other = json.loads(json.dumps(data))
    other["releases"][0]["commit"] = "d" * 40
    key = churn.cache_key(data, files)
    assert key == churn.cache_key(renamed, files) == churn.cache_key(data, list(reversed(files)))
    assert key != churn.cache_key(other, files)
    assert key != churn.cache_key(data, files + ["gfx/new/Hook.cpp"])          # a new hook file is another key: the cache is made again
    root = one_hook_series(tmp_path / "again")
    write_churn(root, source)
    capsys.readouterr()
    assert churn.main(["--cache-key", "--series", str(root)]) == 0
    assert capsys.readouterr().out.strip() == key
    # a new file in a hooks.patch changes the key the job computes
    (root / "network" / "b" / "hooks.patch").write_text(
        patch_text("d.txt", D4, edit(D4, 11, "x")) + patch_text("a.txt", A4, edit(A4, 5, "y")), encoding="utf-8", newline="")
    assert churn.series_paths(root) == files
    (root / "network" / "c").mkdir()
    (root / "network" / "c" / "hooks.patch").write_text(patch_text("c.txt", releases()[3]["c.txt"], ["x"] + releases()[3]["c.txt"][1:]),
                                                       encoding="utf-8", newline="")
    (root / "SERIES").write_text((root / "SERIES").read_text(encoding="utf-8") + "network/c\n", encoding="utf-8")
    assert churn.series_paths(root) == ["a.txt", "c.txt", "d.txt"]
    capsys.readouterr()
    assert churn.main(["--cache-key", "--series", str(root)]) == 0
    assert capsys.readouterr().out.strip() == churn.cache_key(data, files + ["c.txt"]) != key


# --------------------------------------------------------------------------- the real series
SNAPSHOTS = os.environ.get("CHURN_TAGS_REPO", "")
REQUIRED = os.environ.get("CHURN_REQUIRE_TAGS") == "1"      # the round that runs the real series: no tags there is red, not a skip
REAL = churn.default_releases("FIREFOX_159_0_RELEASE")


def snapshots_available():
    if not SNAPSHOTS or not Path(SNAPSHOTS).exists():
        return False
    try:
        churn.check_tags(SNAPSHOTS, REAL)
    except churn.ChurnError:
        return False
    return True


def test_the_round_that_requires_the_tags_has_them():
    assert snapshots_available() or not REQUIRED, "CHURN_REQUIRE_TAGS=1 and the tags 151..159 are not in CHURN_TAGS_REPO=%r" % SNAPSHOTS


@pytest.mark.skipif(not snapshots_available() and not REQUIRED,
                    reason="the Mozilla release tags 151..159 are not in the repository named by CHURN_TAGS_REPO")
def test_three_hunks_of_the_series_at_159_equal_the_first_measurement():
    data = churn.compute(churn.ROOT, SNAPSHOTS, "FIREFOX_159_0_RELEASE")
    h = by_hunk(data)
    assert h[("fingerprint/fonts/font-list", "gfx/thebes/gfxDWriteFontList.cpp", 5)]["which"] == ["153"]
    assert h[("network/proxy-udp", "netwerk/socket/nsSOCKSIOLayer.cpp", 1)]["which"] == ["154"]
    assert h[("platform/hidden-desktop", "dom/media/webrtc/moz.build", 1)]["which"] == ["152", "153", "158"]
    rel = churn.Releases(SNAPSHOTS, REAL, ["gfx/thebes/gfxDWriteFontList.cpp"])
    last = len(REAL) - 1
    found = churn.regions(churn.ROOT, lambda p: rel.blob(last, p) if rel.exists(last, p) else None)
    region = [r["region"] for r in found if (r["folder"], r["file"], r["hunk"]) ==
              ("fingerprint/fonts/font-list", "gfx/thebes/gfxDWriteFontList.cpp", 5)]
    assert region == [(1128, 1135)]
    committed = json.loads((churn.ROOT / "tools" / "churn.json").read_text(encoding="utf-8"))
    assert committed["base"] == data["base"] and committed["hooks"] == data["hooks"] and committed["releases"] == data["releases"]
    assert churn.check(churn.ROOT, SNAPSHOTS) == []


# --------------------------------------------------------------------------- repo-04: every failure is a fail(), none is cut
def test_every_difference_is_a_whole_fail_line_and_none_is_cut():
    hooks = [{"key": "H|f|a|%d" % i, "folder": "network/b", "file": "d.txt", "hunk": i, "churn": 1, "which": ["152"]} for i in range(40)]
    old = {"base": BASE, "band": 2, "releases": [], "hooks": hooks}
    new = {"base": BASE, "band": 2, "releases": [], "hooks": []}
    found = churn.differences(old, new)
    assert len(found) == 40, "forty differences, forty lines: the old message named 25 and counted the rest"
    for line in found:
        assert line.startswith("FAIL network/b d.txt hunk ") and ". Fix: python tools/churn.py --source " in line
        assert line.endswith("Rule: docs/decisions/port-07-quiet-anchors.md")


def test_a_git_failure_names_the_whole_command_and_the_whole_error(tmp_path):
    with pytest.raises(churn.ChurnError) as err:
        churn.git(tmp_path / "nowhere", "rev-parse", "--verify", "refs/tags/x^{commit}", "--quiet", "--end-of-options")
    text = str(err.value)
    assert text.startswith("FAIL git ") and "--end-of-options" in text.split(". Fix: ")[0]
    assert ". Fix: run the same git command by hand" in text and text.endswith("Rule: docs/decisions/port-07-quiet-anchors.md")
