# ci-06: artifacts are taken by name

**Rule.** An artifact of another run is downloaded by its exact name. A pattern is used only for artifacts of the same run, and then the count found is checked against the count expected.

**Enforced by.** The test in test_release_checks.py that refuses any download-artifact with pattern and run-id/github-token.
Test: platform/ci/src/scripts/ci/test_release_checks.py::no workflow downloads by

**Why.** A pattern sees one page of 100 artifacts: publish lost an archive, the hook-tests judge lost the Windows gtest reports.

**Files.** `platform/ci/src/scripts/ci/test_release_checks.py`, `.github/workflows/hook-tests-judge.yml`, `.github/workflows/publish.yml`.

**Don't.**
- Download an artifact of another run with `pattern:`.
- Use a pattern within a run without comparing the count found with the count expected.
