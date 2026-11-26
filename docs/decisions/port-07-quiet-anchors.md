# port-07: an anchor is chosen where Mozilla is quiet

**Rule.** A new hook, or a hook moved by a port, sits at the anchor with the least churn over the last 8 releases among the places its form allows ([hook-02](hook-02-shape-and-contract.md) and the other contract rules still bind: a quieter place that breaks one is not allowed). `tools/churn.py` gives the churn of every hunk of the series: in how many of the 8 intervals between the 9 release tags ending with the base Mozilla changed a line within `PAD` lines of the hunk. A hunk is in the top churn band when its churn is at least `BAND_MIN_CHURN` (the one constant of `tools/churn.py`; nothing else restates the number). A hook in the band names in its `HOOKS.json` entry why no quieter anchor serves, in the hand field `quiet_anchor_why`, one of two forms:
- `{"kind": "only-place", "why": "<words>"}`: no quieter anchor serves, and why;
- `{"kind": "deferred", "quieter": "<mozilla file>:<anchor text>"}`: a quieter anchor exists, the hook moves there at the next port. It is accepted only while `tools/churn.json` is for the tag the series is on (`base` equals `mozilla_tag` of `UPSTREAM.json`); at the next port every `deferred` hook is red until it is moved or given an `only-place` reason.

**Enforced by.**
- `check` (rule C18 of `tools/hook_contract.py`, offline: it reads `tools/churn.json` and `UPSTREAM.json`, and is never debt): a hook whose hunk is in the band without a valid `quiet_anchor_why` fails; a hook whose hunk is not in `tools/churn.json` fails ("a new or moved hook has no churn: run `churn.py --write`"); a `deferred` reason at another base fails; a field of another shape fails.
- Churn is recomputed at every port (`python tools/churn.py --source <repo with the tags> --write`, commit the file). `python tools/churn.py --source <repo> --check` recomputes it and compares with the committed file byte for byte; the job `churn` of `checks.yml` runs it on every pull request and every candidate, on a small partial clone of the tags: each of the nine tags fetched one commit deep without file content and checked against the commit `tools/churn.json` records for it (a tag that resolves to another commit is red), then only the content of the files the series patches (every file of every `hooks.patch` and of `tools/churn.json`), by the shas the trees give, tens of megabytes where whole tags are 1.6 GB (the cache entry must not evict the repository's other caches). The cache key is the commits and that set of files, so a new hook file makes another entry. A file of the series whose content the repository lacks is red with where, what, fix and rule: never read as absent, never a churn of 0.
- Tests: `tools/tests/test_quiet_anchors.py` (C18 on one-hook series), `tools/tests/test_churn.py` (the churn, `--check`, the recorded commits, `--fetch`, the files not fetched, the real series), `tools/tests/test_churn_job.py` (the job).

**Why.** Hunks untouched in 8 releases conflicted 1.0% of the time, the others 3.6%.

**Files.** `tools/churn.py`, `tools/churn.json` (written by the tool, never by hand), `tools/hook_contract.py` (`churn_violations`, `quiet_anchor_problem`, rule C18), `tools/hooks_list.py` (`quiet_anchor_why` is a hand field), `tools/engine.py` (`check` runs C18), `platform/ci/src/.github/workflows/checks.yml` (the job `churn`; exported to `.github/workflows/checks.yml`), `<folder>/HOOKS.json`, [UPDATE.md](../UPDATE.md).

**Don't.**
- Put a hook where its form allows a quieter place only because the nearby lines are easier to write: read the churn of the candidates and take the quietest.
- Write the threshold as a number in a message, a document or a test: cite `BAND_MIN_CHURN`.
- Fetch the tags whole for the check, or let the repository be fetched for fewer files than the series patches: a missing file is red, and the fix is `churn.py --fetch`.
- Edit `tools/churn.json` by hand, or keep it from an older base: it is written by `churn.py --write` for the base of `UPSTREAM.json`.
- Leave a `deferred` reason through a port: move the hook, or say in `only-place` why it cannot move.
- Put a C18 in the debt list, or fetch the tags for the check with anything but `churn.py --fetch`: a tag that is not the recorded commit would make every number meaningless.
