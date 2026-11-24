# ci-07: every check runs before the merge

**Rule.** A check that guards `main` (series rules, births, hook contract, budgets, the judges) runs, with the same code, in the round before the merge: on the pull request and on every `latitude/*` candidate. Nothing is first run on `main`.

**Enforced by.** A test that lists the jobs of `series.yml` and of the push candidate on `main` and requires each to be in the PR round and in the latitude candidate's plan.
Test: tools/tests/test_every_check_runs_before_the_merge.py::test_every_check_runs_in_the_round_before_the_merge_and_in_the_candidate

**Why.** births.py ran first on the release PR of firefox-69 and was red there.

**Files.** `platform/ci/src/.github/workflows/checks.yml` (the checks, written in the source repository and exported to `.github/workflows/checks.yml`), `.github/workflows/series.yml` (a call of it and the `gate` over the call), `platform/ci/src/.github/workflows/release.yml` (job `checks`: a call of it, which the job `node` waits for; job `still-head`: the guard of a superseded candidate, which is not a check), `tools/tests/test_every_check_runs_before_the_merge.py`, `tools/hooks_list.py` (the node tests that rule T3 looks for are read from every workflow), `platform/ci/src/scripts/ci/test_release_checks.py`.

How it is built:
- One reusable workflow, `checks.yml`, with the jobs `rules` (`tools/tests`, `engine.py check`), `rebuilds` (`materialize`, which stops when the tree is not the `exported_tree` of `UPSTREAM.json`: the CI form of `verify`; `births.py`; the core's checks), `noreply-identity` and `tree` (the release plan's own tests, the release scripts' known-bad inputs, asset names, the declared upstream source, our sources and build files, Juggler's tests without a browser, the wrapper's required suites against `gate.yml`, and the junit the hook tests judge reads).
- `series.yml` calls it on every pull request and every push to `main`; `release.yml` calls it on every candidate, a release and the weekly run, with no `if`, and the build node is turned on only after it is green.
- `wrapper_ref` is its one input: `main` for `series.yml`, the run's own for `release.yml`; it names the core under the core's checks ([ci-05](ci-05-a-candidates-references-are-one-consistent-set.md)) and the list of required suites.
- `engine.py verify` needs the source repository and is not a CI check; `materialize` against `exported_tree` is its equivalent here.

**Don't.**
- Add a check to `series.yml` or to `release.yml`: it goes in `checks.yml`, and its command in the table of the test.
- Put an `if`, a `needs` or a `continue-on-error` on a job of `checks.yml`, or an `if` on its call.
- Run a script or a test for the first time in the push candidate on `main`.
