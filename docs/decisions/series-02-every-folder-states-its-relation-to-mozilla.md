# series-02: every folder states its relation to Mozilla, and every port carries a range-diff

**Rule.** Every folder of `SERIES` that has no `BACKPORT.json` has exactly one `FOLDER.json`, written by hand, in one of these shapes and no other:
- `{"relation": "product"}`: the change is ours for good; Mozilla would not make it.
- `{"relation": "defect", "upstream": "not-filed"}`: a defect of Mozilla's that nobody has reported.
- `{"relation": "defect", "upstream": "https://bugzilla.mozilla.org/show_bug.cgi?id=<N>"}`: the same, with the bug Mozilla has.
- for a `defect` only, `"fixed_in": "FIREFOX_<N>_<M>_RELEASE"` (or `FIREFOX_<N>_<M>_<P>_RELEASE`): the release that ships Mozilla's fix.

No other key and no other value. The file never points outside the repository: no local path, no other URL, no text where a bug URL goes. A backport is not a value: it is derived from `BACKPORT.json`, and a backport folder has no `FOLDER.json`. A `FOLDER.json` anywhere but directly in a folder of `SERIES` is red.

A `fixed_in` at or before `mozilla_tag` of `UPSTREAM.json` is red: Mozilla ships the fix, so the folder is dropped or rebased onto Mozilla's fix. Release tags compare by version (`FIREFOX_99_0_RELEASE` is before `FIREFOX_159_0_RELEASE`), never by name.

Every port carries one file, `ports/range-diff.txt`: `git range-diff` of the layers of main's series on main's tag against the layers of this series on its tag. Its first line is `<OLD_TAG>..<NEW_TAG>`. It is replaced at every port, never kept from an earlier one.

**Enforced by.**
- `check` (`tools/folders.py`, called by `engine.py check`): a missing file, a value or a key outside the shapes, a `relation` of `backport`, a `FOLDER.json` in a backport folder, a `fixed_in` at or before the tag, a `FOLDER.json` outside `SERIES`. Each message says where, what, fix and rule.
- `port --to <tag>` (`engine.py`): when a folder's `fixed_in` is at or before the new tag, it stops with a non-zero exit before it merges anything. The message names the folders and gives the command to run again once each is decided (drop the folder, or rebase it onto Mozilla's fix and change or delete its `fixed_in`).
- `range-diff` (`tools/range_diff.py`): `--write` writes `ports/range-diff.txt`; `--check` regenerates it and compares the bytes. The old series is read from git (`--old-series`, default `origin/main`), never from the branch's files. It builds the layer stack of each series on its tag (`build_stack`, one commit per folder) in a partial clone of Mozilla's repository, one commit deep for each tag, without file content, plus the content of the files the two series patch (`--fetch`; the same fetch as `tools/churn.py`); `write-tree --missing-ok` and `GIT_NO_LAZY_FETCH` keep the stack to those objects, and an object it lacks is an error that names the fix. The tree of each stack must be the `exported_tree` of its series. No tree is materialized, no configuration of the machine reaches git, and the same input gives the same bytes.
- The job `range-diff` of `checks.yml`: `range-diff --decide` says whether this run is a port (`mozilla_tag` is not main's); on a port, `range-diff --fetch --check` is red when the file is missing, stale, or its first line is not `<main's tag>..<this tag>`; on any other run the job says so in its log and is green.
- Tests: `tools/tests/test_folders.py` (the check on one fixture per rule, `port` stopping, export leaving the file alone), `tools/tests/test_range_diff.py` (the file, the check, the decision, the partial clone), `tools/tests/test_range_diff_job.py` (the job).

**Why.** A port has to know which folders are ours for good and which should die when Mozilla fixes the defect. Without the relation written down, a folder that Mozilla has since fixed is carried forward and merged for as long as nobody remembers why it exists; with it, the port stops at the folder whose fix is in the new tag, and the reviewer sees the bug it was written for. The range-diff answers the other question of a port, what it did to every folder, in one file the reviewer reads instead of 79 diffs of diffs: which layers are the same patch, which changed and how, which are new or gone. It is regenerated in CI so that it cannot say anything the series does not.

**Files.** `tools/folders.py`, `tools/range_diff.py`, `tools/engine.py` (`check`, `port`, `range-diff`, `build_stack`), `tools/churn.py` (`partial_clone`, `fetch_tag`, `fetch_blobs`), `<folder>/FOLDER.json`, `ports/range-diff.txt`, `platform/ci/src/.github/workflows/checks.yml` (the job `range-diff`; exported to `.github/workflows/checks.yml`), [STRUCTURE.md](../STRUCTURE.md), [UPDATE.md](../UPDATE.md).

**Don't.**
- Write `relation: backport`, put a `FOLDER.json` in a folder that has a `BACKPORT.json`, or let `export` write one: `export` never creates or edits it.
- Put a path, a link to another site, a note or any other key in `FOLDER.json`: the reason for a defect goes in the pull request that adds the folder, the bug in `upstream`.
- Write `fixed_in` for a release that is not out, or leave one at or before the tag: the folder goes, or is rebased onto Mozilla's fix.
- Edit `ports/range-diff.txt` by hand, keep it from an earlier port, or write it from a materialized tree: `range-diff --write` makes it from the two tags.
- Point `--fetch` at a working repository: it makes a partial clone, so it takes a directory of its own.
