# ci-05: a candidate's references are one consistent set

**Rule.** The engine, the core and the wrapper a run uses are a set that pins itself: the wrapper ref names the core version it pins, and the core ref is derived from it unless given; a given core ref that differs from the wrapper's pin is refused before any build.
- The core ref of a run is `v<the core version the wrapper at wrapper_ref pins>`, for every event and kind, unless one is given; a given one is kept only when it builds that same version.
- `checks.yml` reads the core for its checks (the `rebuilds` job, step `core`) by the same resolver, with the `wrapper_ref` of its caller (`main` for `series.yml`, the run's own for `release.yml`): the core under the series' checks is the one that wrapper pins, never a commit written in the workflow.

**Enforced by.** A plan-level test: the resolved core ref equals the wrapper's pin, or the plan stops with the two versions named. A test of `checks.yml` refuses a literal core commit in its checkout and a missing resolver step.
Test: platform/ci/src/scripts/test_release_plan.py::a given core_ref that builds another version

**Why.** Run 45348928499 took the core of main (69.82.0) and the wrapper of main (pinning 68.80.0): every e2e leg died at import. A core commit written by hand in a workflow is the same fault waiting for the next port.

**Files.** `platform/ci/src/scripts/release_plan.py` (`resolve_core_ref`, `core_version_at`, `--resolve-core-ref`), `platform/ci/src/scripts/test_release_plan.py`, `.github/workflows/release.yml` (Plan step), `.github/workflows/checks.yml` (`rebuilds`, the core step), `.github/workflows/series.yml` (its call, `wrapper_ref: main`), `tools/tests/test_series_yml_core_is_derived.py`.

**Don't.**
- Write a core commit or version by hand in a workflow.
- Pass a core_ref that builds another version than the wrapper pins.
