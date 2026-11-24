# This tree is not mozilla-central: it is our patched Firefox

Mozilla's instructions above apply; these come first when they contradict.

## You are in the only place where the source is changed

This is the source repository. Do not look for another and do not create
one: a build mirror only exists because Firefox compiles natively on each
system, and a pre-commit hook there refuses commits. The series repository
(`oss-invisible/firefox_antidetect_patch`) holds the same work as patches on
the Mozilla tag, produced from this tree with `tools/engine.py`
(`export`, `verify`, `check`).

There is a single `.mozconfig`, at the root, identical for both machines - and
it also decides what the CI builds, which has none of its own and only appends
the per-target options.

## Building

`./mach build`. It is incremental. **Never `mach clobber`**, never delete the
objdir: 15-60 minutes against 3-4 hours, and a clobber almost never solves
anything that a `mach build` does not.

**The cost depends on WHAT you touch, not on how much you write**, and they are
different orders of magnitude: a lone `.cpp` takes about 2 minutes;
`dom/base/Element.h`, which is included almost everywhere, 38 minutes for three
lines. When the same change can be made without touching a widely included
header, that choice is worth half an hour and must be made when writing the
patch, not afterwards. Touching `.mozconfig` forces a reconfigure.

The compile cache is already declared in the `.mozconfig` (`sccache`, for Rust
too) and works by itself: there is nothing to launch first. Check it with
`sccache --show-stats`. The first run after a reconfigure is SLOWER with the
cache than without, because it has to populate.

## Building in CI (`release.yml`)

- **Candidate** (`kind=candidate`): builds with sccache backed by the GitHub
  Actions cache (`compile_cache=gha`, the default), so the run after a fix
  recompiles only what changed. Build errors are fixed by iterating this way,
  not with cold runs.
- **Release**: with the cache too (decision of 03/11). `compile_cache=off`
  asks for a cold build, and `publish.yml` refuses nothing because of the
  cache. It is launched by hand from `main`, a candidate from a branch; no
  build starts from a tag. A candidate is published without recompiling by
  `republish.yml`.
- Every build runs with `--keep-going`: a failed run lists all the errors of
  the leg, not only the first.
- The decision lives in one place, `scripts/release_plan.py` (with its cases in
  `scripts/test_release_plan.py`); the workflows only read the plan.
- An empty `core_ref` means `main`. A new version of the engine passes the
  branch of the core that follows it: the surface check judges the branding
  that core declares.

## The two rules that break the product if ignored

1. **Every spoof goes through a pref** `zoom.stealth.*` or `stealthfox.*` (or
   `STEALTHFOX_*` for the binary/Juggler contract). Never values hardwired in
   C++ or in Python, and **never rename those prefs**: they are the contract
   between the binary and the wrapper.
2. **Look real, not "lose nothing".** A suppressed, blocked or empty signal is
   itself a clue and counts as a failure. Before writing "real browsers do
   this", test it on a retail Firefox of the same major version we declare.

## Where the rest is written

The design documents are NOT in this tree: they are kept outside it, in
the project's private documentation. They hold the list of our patches and
why, and the open bugs.

**Every change to the source updates those documents in the same piece of
work.**
