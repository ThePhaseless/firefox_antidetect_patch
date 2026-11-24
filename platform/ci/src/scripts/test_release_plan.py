#!/usr/bin/env python3
"""release_plan.py, driven against the inputs it exists to refuse.

The plan decides before any build what a run is. These are the runs it must
refuse, each one a real way to get it wrong, and the runs it must accept:

  known-bad
    1. a candidate given a release tag - the old habit of naming a candidate
       `firefox-N` or `firefox-N-candidate-x`, which either collided with the
       real draft or died at the seal two hours later;
    2. a release by hand whose tag is not firefox-N (`firefox-49-candidate-b322`,
       the run that died at the seal twice);
    3. a release by hand with no tag at all;
    4. a pushed tag, any tag: the trigger is gone, and what a run from a tag saves
       nothing after it can read;
    5. a kind nobody declared;
    6. an event that is not a run by hand;
    7. a build dispatched from a tag ref, and a release from any branch but main;
    8. a compile cache nobody declared;
    8b. --builder: there is no such choice any more.
  known-good
    9. a candidate: nothing published, the gate's seal LOCAL and numbered
       (firefox-N-candidate, N the last release plus one), the cache on;
   10. a candidate with the cache off, a cold build;
   11. a release by hand: tag, number, previous tag, the seal under the tag,
       the cache on;
   12. a release by hand that asks for the cache off, or for it by name;
   13. a release from main, a candidate from a branch; republish.yml passes no ref
       type and is not asked.
  stop_after (the compile-only candidate: build the touched directories' objects and stop)
   14. refused: for a release, from main, from another branch, from a tag, with no ref
       type, by a push or the timer, and with a value nobody declared;
   15. accepted: a candidate by hand on a latitude/* branch, with the gtests turned off
       whatever the input said (nothing links, so none can run); the other plans carry
       stop_after empty.
  the core of every run (ci-05: the wrapper's pin and the core are one set; the resolved core_ref is `v<pin>`, or the plan stops naming both versions)
   16. accepted: an empty core_ref is `v<the version the wrapper at wrapper_ref pins>` for every event and kind (either spelling of the
       requirement, read at wrapper_ref); a given core_ref that builds the pinned version is kept;
       refused: a given core_ref that builds another version (the case the old plan accepted: it kept any given ref unchecked), no pin, two pins,
       a pin that is not X.Y.Z, a tag the core does not have, a pin or a core file that cannot be read, a core whose _version.py lacks the
       derivation or has no (or two) CORE_REVISION lines, a seal tag that is not firefox-N, no way to read at all.
   17. the command line: `--resolve-core-ref --wrapper-ref <ref> [--core-ref <ref>]` prints `core_ref=<resolved>` and nothing else, or exits 1
       with `PLAN REFUSED:`; the plan's own command line asks the same resolver.

Run it directly, like test_make_seal.py: `python3 scripts/test_release_plan.py`.
"""
from __future__ import annotations

import builtins
import io
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import release_plan as p  # noqa: E402

REFUSED = [
    ("a candidate given a release tag", ("workflow_dispatch", "candidate", "firefox-49", "x")),
    ("a candidate given a candidate's name",
     ("workflow_dispatch", "candidate", "firefox-49-candidate-b322", "x")),
    ("a release whose tag is not firefox-N",
     ("workflow_dispatch", "release", "firefox-49-candidate-b322", "x")),
    ("a release with no tag", ("workflow_dispatch", "release", "", "x")),
    ("a pushed tag that is not firefox-N", ("push", "", "", "firefox-49-rc")),
    ("a pushed firefox-N tag: its cache entries nothing could read", ("push", "", "", "firefox-50")),
    ("a candidate dispatched from a tag", ("workflow_dispatch", "candidate", "", "firefox-50", "", "tag")),
    ("a release dispatched from a tag", ("workflow_dispatch", "release", "firefox-50", "firefox-50", "", "tag")),
    ("a release dispatched from another branch", ("workflow_dispatch", "release", "firefox-50", "latitude/executor", "", "branch")),
    ("an undeclared kind", ("workflow_dispatch", "nightly", "", "x")),
    ("an empty kind by hand", ("workflow_dispatch", "", "", "x")),
    ("another event", ("pull_request", "release", "firefox-49", "x")),
    ("an undeclared compile cache", ("workflow_dispatch", "candidate", "", "x", "on")),
    # by itself: only from the branch main, and with no inputs
    ("a push to another branch", ("push", "", "", "latitude/executor", "", "branch")),
    ("a timer on another branch", ("schedule", "", "", "next/firefox-57", "", "branch")),
    ("a push to main that names a kind", ("push", "release", "", "main", "", "branch")),
    ("a push to main that asks for a cold build", ("push", "", "", "main", "off", "branch")),
]

#: The last published release the workflow reads from the tags: a candidate is the engine after it.
LAST_RELEASE = "48"

#: The wrapper's dependencies as pyproject.toml has them, with the one core pin: every run uses that core.
PYPROJECT = 'dependencies = [\n    "playwright==1.49.0",\n    "invisible_core==68.80.0",\n]\n'
CORE_TAGS = {"v68.80.0", "v69.82.0"}

#: The core's _version.py as it is (the derivation from seal.json and the one hand-edited number), and a seal with its tag.
VERSION_PY = ('"""Package version."""\nimport json\nimport pathlib\n\nCORE_REVISION = {rev}\n\n_seal = json.loads(\n'
              '    pathlib.Path(__file__).with_name("seal.json").read_text(encoding="utf-8")\n)\n'
              '__version__ = f"{{int(_seal[\'tag\'].split(\'-\')[1])}}.{{CORE_REVISION}}.0"\n')


def core_files(rev=82, tag="firefox-69"):
    return {p.CORE_VERSION_PY: VERSION_PY.format(rev=rev), p.CORE_SEAL_JSON: json.dumps({"tag": tag, "assets": {}})}


#: What the core has at each ref: the tag of a release is that release; main is ahead of the wrapper's pin.
CORE_AT = {"v68.80.0": core_files(80, "firefox-68"), "v69.82.0": core_files(82, "firefox-69"), "main": core_files(82, "firefox-69"),
           "same-pin-branch": core_files(80, "firefox-68")}


def fake_core_file(ref, path):
    try:
        return CORE_AT[ref][path]
    except KeyError:
        raise p.PlanError(f"{path} of the core at {ref!r} cannot be read: not found") from None


def fake_resolve(wrapper_ref, core_ref):
    """What the plan step does with the API and the tags, on text: the plan's own resolver, offline."""
    return p.resolve_core_ref(wrapper_ref, core_ref, lambda ref: PYPROJECT, lambda tag: tag in CORE_TAGS, fake_core_file)


def plan(*args, **kw):
    """p.plan with the offline resolver: every plan asks the pin and the core, so every test hands them in."""
    return p.plan(*args, core_ref_resolver=kw.pop("core_ref_resolver", fake_resolve), **kw)


#: What every plan carries besides its kind: the gtests and the refs.
DEFAULTS = {"gtests": "false", "gtest_filter": p.DEFAULT_GTEST_FILTER,
            "core_ref": "v68.80.0", "wrapper_ref": "main", "stop_after": ""}

#: (name, positional inputs, stop_after): the plan must refuse each.
STOP_REFUSED = [
    ("stop_after=objects on a release from main", ("workflow_dispatch", "release", "firefox-50", "main", "", "branch"), "objects"),
    ("stop_after=objects on a release from a latitude branch",
     ("workflow_dispatch", "release", "firefox-50", "latitude/x", "", "branch"), "objects"),
    ("stop_after=objects on a candidate from main", ("workflow_dispatch", "candidate", "", "main", "", "branch"), "objects"),
    ("stop_after=objects on a candidate from another branch",
     ("workflow_dispatch", "candidate", "", "next/firefox-49", "", "branch"), "objects"),
    ("stop_after=objects on a candidate from a tag", ("workflow_dispatch", "candidate", "", "latitude/x", "", "tag"), "objects"),
    ("stop_after=objects with no ref type", ("workflow_dispatch", "candidate", "", "latitude/x"), "objects"),
    ("stop_after=objects on a push", ("push", "", "", "main", "", "branch"), "objects"),
    ("stop_after=objects on the weekly timer", ("schedule", "", "", "main", "", "branch"), "objects"),
    ("a stop_after nobody declared", ("workflow_dispatch", "candidate", "", "latitude/x", "", "branch"), "link"),
    ("a stop_after that is only a prefix", ("workflow_dispatch", "candidate", "", "latitude/x", "", "branch"), "object"),
]

STOP_ACCEPTED = [
    ("a candidate on a latitude branch that stops after the objects",
     ("workflow_dispatch", "candidate", "", "latitude/objects-only", "", "branch"), "objects",
     {"kind": "candidate", "tag": "", "num": "", "prevtag": "", "seal_tag": "firefox-49-candidate",
      "compile_cache": "gha", "stop_after": "objects", "gtests": "false"}),
    ("the same asking for the gtests: they stay off, nothing links",
     ("workflow_dispatch", "candidate", "", "latitude/objects-only", "", "branch", "true", "StealthA.*"), "objects",
     {"kind": "candidate", "tag": "", "num": "", "prevtag": "", "seal_tag": "firefox-49-candidate",
      "compile_cache": "gha", "stop_after": "objects", "gtests": "false", "gtest_filter": "StealthA.*"}),
    ("a candidate on a latitude branch that does not stop",
     ("workflow_dispatch", "candidate", "", "latitude/objects-only", "", "branch"), "",
     {"kind": "candidate", "tag": "", "num": "", "prevtag": "", "seal_tag": "firefox-49-candidate",
      "compile_cache": "gha", "stop_after": "", "gtests": "false"}),
]

ACCEPTED = [
    ("a candidate", ("workflow_dispatch", "candidate", "", "next/firefox-49"),
     {"kind": "candidate", "tag": "", "num": "", "prevtag": "", "seal_tag": "firefox-49-candidate",
      "compile_cache": "gha"}),
    ("a candidate without the cache",
     ("workflow_dispatch", "candidate", "", "next/firefox-49", "off"),
     {"kind": "candidate", "tag": "", "num": "", "prevtag": "", "seal_tag": "firefox-49-candidate",
      "compile_cache": "off"}),
    ("a release by hand", ("workflow_dispatch", "release", "firefox-49", "next/firefox-49"),
     {"kind": "release", "tag": "firefox-49", "num": "49", "prevtag": "firefox-48",
      "seal_tag": "firefox-49", "compile_cache": "gha"}),
    ("a push to main: a candidate with the gtests and the cache",
     ("push", "", "", "main", "", "branch"),
     {"kind": "candidate", "tag": "", "num": "", "prevtag": "", "seal_tag": "firefox-49-candidate",
      "compile_cache": "gha", "gtests": "true"}),
    ("the weekly timer on main: the same candidate, on the core its wrapper pins",
     ("schedule", "", "", "main", "", "branch"),
     {"kind": "candidate", "tag": "", "num": "", "prevtag": "", "seal_tag": "firefox-49-candidate",
      "compile_cache": "gha", "gtests": "true"}),
    ("a candidate by hand with the gtests and its own refs (a core ref that builds the pinned version is kept)",
     ("workflow_dispatch", "candidate", "", "main", "", "branch", "true",
      "StealthGfxFeatureStatus.*", "same-pin-branch", "remove-font-gate"),
     {"kind": "candidate", "tag": "", "num": "", "prevtag": "", "seal_tag": "firefox-49-candidate",
      "compile_cache": "gha", "gtests": "true", "gtest_filter": "StealthGfxFeatureStatus.*",
      "core_ref": "same-pin-branch", "wrapper_ref": "remove-font-gate"}),
    ("a release by hand asking for the cache",
     ("workflow_dispatch", "release", "firefox-49", "next/firefox-49", "gha"),
     {"kind": "release", "tag": "firefox-49", "num": "49", "prevtag": "firefox-48",
      "seal_tag": "firefox-49", "compile_cache": "gha"}),
    ("a release by hand asking for no cache",
     ("workflow_dispatch", "release", "firefox-49", "next/firefox-49", "off"),
     {"kind": "release", "tag": "firefox-49", "num": "49", "prevtag": "firefox-48",
      "seal_tag": "firefox-49", "compile_cache": "off"}),
    ("a release dispatched from main",
     ("workflow_dispatch", "release", "firefox-50", "main", "", "branch"),
     {"kind": "release", "tag": "firefox-50", "num": "50", "prevtag": "firefox-49",
      "seal_tag": "firefox-50", "compile_cache": "gha"}),
    ("a candidate dispatched from a branch",
     ("workflow_dispatch", "candidate", "", "latitude/executor", "", "branch"),
     {"kind": "candidate", "tag": "", "num": "", "prevtag": "", "seal_tag": "firefox-49-candidate",
      "compile_cache": "gha"}),
]


def main() -> int:
    failures = 0
    cases = 0

    def print(*args, **kw):  # every verdict line ("ok ..." or "FAIL ...") is a case; the count is what was said, not a sum kept by hand
        nonlocal cases
        cases += bool(args) and str(args[0]).startswith(("ok  ", "FAIL  "))
        builtins.print(*args, **kw)

    for name, args in REFUSED:
        try:
            got = plan(*args, last_release=LAST_RELEASE)
        except p.PlanError as exc:
            print(f"ok    refused: {name}: {exc}")
        else:
            print(f"FAIL  accepted: {name}: {got}")
            failures += 1
    for name, args, want in ACCEPTED:
        want = {**DEFAULTS, **want}
        try:
            got = plan(*args, last_release=LAST_RELEASE)
        except p.PlanError as exc:
            print(f"FAIL  refused: {name}: {exc}")
            failures += 1
            continue
        if got != want:
            print(f"FAIL  {name}: {got} != {want}")
            failures += 1
        else:
            print(f"ok    {name}")
    # the command line: outputs on stdout for $GITHUB_OUTPUT, a refusal as exit 1
    if p.main(["--event", "workflow_dispatch", "--kind", "release",
               "--release-tag", "firefox-49-candidate-b322"]) != 1:
        print("FAIL  the command line accepted a bad release tag")
        failures += 1
    # A candidate is sealed firefox-N-candidate (the wrapper's tests read N from the seal, and fail on `local`): N is the
    # last published release plus one, and a candidate without the last release is refused, not sealed `local`.
    for name, last, want in (("a candidate after firefox-62 is firefox-63-candidate", "62", "firefox-63-candidate"),
                             ("a candidate after firefox-9 is firefox-10-candidate (numbers, not strings)", "9", "firefox-10-candidate")):
        got = plan("workflow_dispatch", "candidate", "", "latitude/firefox-63-udp", "", "branch", last_release=last)
        if got["seal_tag"] != want:
            print(f"FAIL  {name}: {got['seal_tag']} != {want}")
            failures += 1
        else:
            print(f"ok    {name}")
    for name, last in (("a candidate without the last release", ""), ("a candidate with a last release that is no number", "firefox-62"),
                       ("a candidate with a negative last release", "-1")):
        try:
            got = plan("workflow_dispatch", "candidate", "", "latitude/firefox-63-udp", "", "branch", last_release=last)
        except p.PlanError as exc:
            print(f"ok    refused: {name}: {exc}")
        else:
            print(f"FAIL  accepted: {name}: {got}")
            failures += 1
    for name, args, stop in STOP_REFUSED:
        try:
            got = plan(*args, last_release=LAST_RELEASE, stop_after=stop)
        except p.PlanError as exc:
            print(f"ok    refused: {name}: {exc}")
        else:
            print(f"FAIL  accepted: {name}: {got}")
            failures += 1
    for name, args, stop, want in STOP_ACCEPTED:
        want = {**DEFAULTS, **want}
        try:
            got = plan(*args, last_release=LAST_RELEASE, stop_after=stop)
        except p.PlanError as exc:
            print(f"FAIL  refused: {name}: {exc}")
            failures += 1
            continue
        if got != want:
            print(f"FAIL  {name}: {got} != {want}")
            failures += 1
        else:
            print(f"ok    {name}")
    # The command line says it too: the workflow passes --stop-after, and a refusal is exit 1.
    base = ["--event", "workflow_dispatch", "--kind", "candidate", "--last-release", LAST_RELEASE, "--ref-type", "branch"]
    stderr, sys.stderr = sys.stderr, open(os.devnull, "w")
    real_readers = (p.github_pyproject, p.github_tag_exists, p.github_core_file)
    p.github_pyproject, p.github_tag_exists, p.github_core_file = (lambda ref: PYPROJECT), (lambda tag: tag in CORE_TAGS), fake_core_file
    try:
        stops = (p.main(base + ["--ref-name", "main", "--stop-after", "objects"]),
                 p.main(base + ["--ref-name", "latitude/x", "--stop-after", "objects"]))
    finally:
        p.github_pyproject, p.github_tag_exists, p.github_core_file = real_readers
        sys.stderr.close()
        sys.stderr = stderr
    if stops != (1, 0):
        print(f"FAIL  --stop-after objects: main refused and latitude/x accepted, got {stops}")
        failures += 1
    else:
        print("ok    --stop-after objects on the command line")
    got = plan("workflow_dispatch", "release", "firefox-63", "main", "", "branch", last_release="62")
    if got["seal_tag"] != "firefox-63":
        print(f"FAIL  a release is sealed under its own tag whatever the last release: {got['seal_tag']}")
        failures += 1
    else:
        print("ok    a release is sealed under its own tag")

    # The core of every run: the one its wrapper pins (ci-05), never `main` by default (run 45348928499: wrapper 0.58.1 pinned invisible_core==68.80.0, the
    # core's main was 69.82.0, and every wrapper e2e died at import). Offline: the pyproject text, the tags and the core's files are handed in.
    def run(pyproject=PYPROJECT, tags=CORE_TAGS, core="", wrapper="", args=("push", "", "", "main", "", "branch"), core_files_at=None):
        seen = []

        def read(ref):
            seen.append(ref)
            return pyproject

        files = CORE_AT if core_files_at is None else core_files_at

        def read_core(ref, path):
            try:
                return files[ref][path]
            except KeyError:
                raise p.PlanError(f"{path} of the core at {ref!r} cannot be read") from None

        got = p.plan(*args, core_ref=core, wrapper_ref=wrapper, last_release=LAST_RELEASE,
                     core_ref_resolver=lambda w, c: p.resolve_core_ref(w, c, read, lambda tag: tag in tags, read_core))
        return got, seen

    every = (("push", "", "", "main", "", "branch"), ("schedule", "", "", "main", "", "branch"),
             ("workflow_dispatch", "candidate", "", "main", "", "branch"), ("workflow_dispatch", "candidate", "", "latitude/x", "", "branch"),
             ("workflow_dispatch", "release", "firefox-50", "main", "", "branch"))
    pin_ok = True
    for args in every:
        got, seen = run(args=args)
        pin_ok = pin_ok and (got["core_ref"], got["wrapper_ref"], seen) == ("v68.80.0", "main", ["main"])
    got, seen = run(PYPROJECT.replace("invisible_core", "invisible-core"), wrapper="some-branch")
    pin_ok = pin_ok and (got["core_ref"], got["wrapper_ref"], seen) == ("v68.80.0", "some-branch", ["some-branch"])
    same_ok = True
    for args in every:
        for given in ("same-pin-branch", "v68.80.0"):
            got, _ = run(core=given, args=args)
            same_ok = same_ok and got["core_ref"] == given
    for name, ok in (("every event and kind with no core_ref uses v<the core its wrapper pins>, either spelling, read at wrapper_ref", pin_ok),
                     ("a given core_ref that builds the pinned version is kept, for every event and kind", same_ok)):
        print(("ok    " if ok else "FAIL  ") + name)
        failures += not ok

    def refused(name, **kw):
        nonlocal failures
        try:
            got, _ = run(**kw)
        except p.PlanError as exc:
            print(f"ok    refused: {name}: {exc}")
            return str(exc)
        print(f"FAIL  accepted: {name}: {got}")
        failures += 1
        return ""

    # The red-on-old case: the old plan kept any given core_ref unchecked.
    for args in every:
        said = refused(f"a given core_ref that builds another version ({args[0]} {args[1] or '-'})", core="main", args=args)
        named = "pins invisible_core 68.80.0" in said and "core_ref main builds 69.82.0" in said
        print(("ok    " if named else "FAIL  ") + "  ... and the refusal names both versions")
        failures += not named
    refused("a pin whose tag the core does not have (no fall back to main)", tags={"v69.82.0"})
    refused("no core pin", pyproject='dependencies = ["playwright==1.49.0"]')
    refused("two core pins", pyproject=PYPROJECT + '"invisible-core==68.80.0"')
    refused("a core requirement that is no exact pin", pyproject='dependencies = ["invisible_core>=68.80.0"]')
    refused("a core pin that is not X.Y.Z", pyproject='dependencies = ["invisible_core==68.80"]')
    refused("a given core_ref when the pyproject has no pin", pyproject="", core="same-pin-branch")
    refused("a given core_ref the core does not have", core="no-such-branch")
    good = CORE_AT["same-pin-branch"]

    def broken(**files):
        return {"core": "same-pin-branch", "core_files_at": {"same-pin-branch": files}}

    refused("a core with no _version.py", **broken(**{p.CORE_SEAL_JSON: good[p.CORE_SEAL_JSON]}))
    refused("a core with no seal.json", **broken(**{p.CORE_VERSION_PY: good[p.CORE_VERSION_PY]}))
    version_py = good[p.CORE_VERSION_PY]
    refused("a _version.py without the derivation from the seal (a hand-written version)",
            **broken(**{p.CORE_SEAL_JSON: good[p.CORE_SEAL_JSON], p.CORE_VERSION_PY: 'CORE_REVISION = 80\n__version__ = "68.80.0"\n'}))
    refused("a _version.py that derives the version some other way",
            **broken(**{p.CORE_SEAL_JSON: good[p.CORE_SEAL_JSON], p.CORE_VERSION_PY: version_py.replace("[1]", "[-1]")}))
    refused("a _version.py with no CORE_REVISION line",
            **broken(**{p.CORE_SEAL_JSON: good[p.CORE_SEAL_JSON], p.CORE_VERSION_PY: version_py.replace("CORE_REVISION = 80\n", "")}))
    refused("a _version.py with two CORE_REVISION lines",
            **broken(**{p.CORE_SEAL_JSON: good[p.CORE_SEAL_JSON], p.CORE_VERSION_PY: version_py + "CORE_REVISION = 81\n"}))
    refused("a CORE_REVISION that is no integer",
            **broken(**{p.CORE_SEAL_JSON: good[p.CORE_SEAL_JSON], p.CORE_VERSION_PY: version_py.replace("CORE_REVISION = 80", "CORE_REVISION = 8x")}))
    refused("a seal that is not JSON", **broken(**{p.CORE_VERSION_PY: version_py, p.CORE_SEAL_JSON: "not json"}))
    refused("a seal with no tag", **broken(**{p.CORE_VERSION_PY: version_py, p.CORE_SEAL_JSON: "{}"}))
    for bad in ("local", "firefox-68-candidate", "firefox-x", "68", ""):
        refused(f"a seal tag that is not firefox-N ({bad!r})", **broken(**{p.CORE_VERSION_PY: version_py, p.CORE_SEAL_JSON: json.dumps({"tag": bad})}))
    refused("a seal tag that is not a string", **broken(**{p.CORE_VERSION_PY: version_py, p.CORE_SEAL_JSON: json.dumps({"tag": 68})}))

    def unreadable_pin(ref):
        raise p.PlanError("pyproject.toml cannot be read: no API")

    for name, resolver in (("a run with no way to read the pin", None),
                           ("a pyproject that cannot be read", lambda w, c: p.resolve_core_ref(w, c, unreadable_pin, lambda t: True, fake_core_file))):
        for args in every:
            try:
                got = p.plan(*args, last_release=LAST_RELEASE, core_ref_resolver=resolver)
            except p.PlanError as exc:
                print(f"ok    refused: {name} ({args[0]} {args[1] or '-'}): {exc}")
            else:
                print(f"FAIL  accepted: {name} ({args[0]} {args[1] or '-'}): {got}")
                failures += 1

    # The core's version by its formula: N from the seal tag, the revision from its one line.
    versions_ok = all(p.core_version_at("r", lambda ref, path, f=core_files(rev, tag): f[path]) == want
                      for rev, tag, want in ((82, "firefox-69", "69.82.0"), (80, "firefox-68", "68.80.0"), (5, "firefox-9", "9.5.0"),
                                             (100, "firefox-100", "100.100.0")))
    print(("ok    " if versions_ok else "FAIL  ") + "the core's version at a ref is <N from the seal tag>.<CORE_REVISION>.0")
    failures += not versions_ok

    # The command line, the readers replaced by text. The plan's own: a push says v<pin>, a pin with no tag is exit 1. And the mode
    # another workflow calls: one line `core_ref=<resolved>` on stdout, or `PLAN REFUSED:` on stderr and exit 1; no other argument.
    real = (p.github_pyproject, p.github_tag_exists, p.github_core_file)

    def cli(argv, tags=CORE_TAGS):
        out, err = io.StringIO(), io.StringIO()
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = out, err
        try:
            p.github_pyproject, p.github_tag_exists, p.github_core_file = (lambda ref: PYPROJECT), (lambda tag: tag in tags), fake_core_file
            code = p.main(argv)
        finally:
            p.github_pyproject, p.github_tag_exists, p.github_core_file = real
            sys.stdout, sys.stderr = old_out, old_err
        return code, out.getvalue(), err.getvalue()

    push_cli = ["--event", "push", "--ref-name", "main", "--ref-type", "branch", "--last-release", LAST_RELEASE]
    code, out, err = cli(push_cli)
    plan_ok = code == 0 and "core_ref=v68.80.0\n" in out
    code, out, err = cli(push_cli, tags={"v69.82.0"})
    plan_ok = plan_ok and code == 1 and "PLAN REFUSED" in err and out == ""
    code, out, err = cli(push_cli + ["--core-ref", "main"])
    plan_ok = plan_ok and code == 1 and "pins invisible_core 68.80.0; core_ref main builds 69.82.0" in err and out == ""
    print(("ok    " if plan_ok else "FAIL  ") + "the plan's command line plans on the pinned core, and refuses a pin with no tag or a core that is another version")
    failures += not plan_ok
    resolve = ["--resolve-core-ref", "--wrapper-ref", "main"]
    results = (cli(resolve), cli(resolve + ["--core-ref", "same-pin-branch"]), cli(resolve + ["--core-ref", "main"]),
               cli(resolve + ["--core-ref", "no-such-branch"]), cli(resolve, tags=set()), cli(["--resolve-core-ref"]))
    shape_ok = (results[0] == (0, "core_ref=v68.80.0\n", "")
                and results[1] == (0, "core_ref=same-pin-branch\n", "")
                and results[2][0] == 1 and results[2][1] == "" and results[2][2].startswith("PLAN REFUSED: ")
                and "pins invisible_core 68.80.0; core_ref main builds 69.82.0" in results[2][2]
                and results[3][0] == 1 and results[3][1] == "" and results[3][2].startswith("PLAN REFUSED: ")
                and results[4][0] == 1 and results[4][1] == "" and results[4][2].startswith("PLAN REFUSED: ")
                and results[5] == (0, "core_ref=v68.80.0\n", ""))
    print(("ok    " if shape_ok else "FAIL  ") + f"--resolve-core-ref prints one core_ref= line or PLAN REFUSED and exit 1, with no other argument {'' if shape_ok else results}")
    failures += not shape_ok

    # No fallback: the choice of who compiles does not exist, so it cannot be made.
    stderr, sys.stderr = sys.stderr, open(os.devnull, "w")
    try:
        p.main(["--event", "workflow_dispatch", "--kind", "candidate", "--builder", "github"])
        took = True
    except SystemExit as exc:
        took = exc.code != 2
    finally:
        sys.stderr.close()
        sys.stderr = stderr
    if took:
        print("FAIL  the command line took a builder")
        failures += 1
    total = cases
    print(f"{total - failures}/{total} cases as expected")
    return 1 if failures else 0


def test_the_plan_refuses_and_accepts_what_it_must(capsys):
    """pytest's door to the same cases: every line is printed, and none may say FAIL."""
    code = main()
    assert "FAIL" not in capsys.readouterr().out
    assert code == 0


if __name__ == "__main__":
    sys.exit(main())
