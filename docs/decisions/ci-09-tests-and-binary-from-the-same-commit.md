# ci-09: tests and binary come from the same commit

**Rule.** A test of the engine's behaviour runs against a binary built from the same series commit as the test. A run that takes a binary it did not build (a published release, another run's build) takes the tests from that binary's series commit (the seal's `series_commit`), never from the branch head. A test changed after a release is tested against the next build, not against that release.

**Enforced by.** The test `test_tests_and_binary_come_from_the_same_commit` in `platform/ci/src/scripts/ci/test_ab_package.py`, over every workflow: every job that downloads a binary of another run or of a release checks out the tests at that binary's series commit (`scripts/ci/binary_series.py`), or proves the two commits equal; a job that runs no test of the engine on it (a comparator of two binaries, a publisher, the wrapper's suites) is declared with its reason.

**Why.** The push mode ran the series' xpcshell tests of today (English console message) against firefox-69 (Italian message): red on a test, not on the engine.

**Files.** `platform/ci/src/scripts/ci/binary_series.py`, `platform/ci/src/.github/workflows/gate.yml` (job `gate`), `platform/ci/src/.github/workflows/xpcshell.yml` (job `xpcshell`), `platform/ci/src/scripts/ci/test_ab_package.py`.

**Don't.**
- Run the tests of the branch head on a published release or on another run's build.
- Skip or loosen a test that is red only because it is newer than the binary: take the binary's tests.
- Add a job that takes another binary without declaring how it meets this rule.
