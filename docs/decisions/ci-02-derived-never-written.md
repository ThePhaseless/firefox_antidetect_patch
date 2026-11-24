# ci-02: derived, never written

**Rule.** A reference to something that changes (a release of the engine, a build run, a version of the core or the wrapper, a commit of another repository) is resolved at run time from its source of truth: the latest published release (`scripts/ci/published_release.py`), the seal of that release (build, series commit), the version the wrapper pins (the core), a branch head. A workflow input may name one explicitly, and then it wins.

**Enforced by.** The rule test `test_no_workflow_or_script_writes_a_reference_that_changes` in `platform/ci/src/scripts/ci/test_ab_package.py`, over every workflow and CI script: no literal `firefox-<N>` tag, no run id (a number of 8 or more digits in a ref, an input or an environment value), no version `\d+\.\d+\.\d+` of the core or the wrapper, outside input descriptions and comments.

**Why.** `firefox-68` stayed the A/B baseline after firefox-69 was published; a push mode read run 44921963200, whose artifacts expire.

**Files.** `platform/ci/src/scripts/ci/published_release.py`, the workflows under `platform/ci/src/.github/workflows/` (copied to `.github/workflows/` by `export`), `platform/ci/src/scripts/ci/node_bootstrap.sh` (the address of a release file from its tag and name), `platform/ci/src/scripts/ci/test_ab_package.py`.

**Don't.**
- Write a release tag, a run id, an asset id or a core or wrapper version as a value in a workflow or a CI script.
- Keep a run's artifacts as a baseline: they expire; a published release does not.
- Widen the rule test's exceptions to let a written reference through: resolve it.
