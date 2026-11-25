#!/usr/bin/env python3
"""scripts/ci/py_deps.py, scripts/ci/locks/*.txt and .github/workflows/py-deps.yml: the rule of ci-03 for pip.

A list of packages is resolved against the exact state it is installed on, once per state, by one job; the result is kept in a cache keyed by that state and the
list; the legs install only from it, offline, by name; no unpinned install anywhere.

Red cases first, each against a known-bad copy of what it checks: a lock line that is a range, a URL, an editable or has no hash; a lock made from another input
than the one committed; a workflow whose key lacks the image's OS, its release, the Python or the spec's hash, whose step that reaches the index has no
cache-miss condition, whose artifact has another name; a consumer that would reach the index. The committed locks and workflow must pass the same checks.

    python3 scripts/ci/test_py_deps.py
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import py_deps as pd  # noqa: E402

WORKFLOW = HERE.parent.parent / ".github" / "workflows" / "py-deps.yml"
MISS = "steps.restore.outputs.cache-hit != 'true'"
# What reaches an index (or any host) in a step's script: pip, uv, our build command, curl, apt.
REACHES = re.compile(r"\b(pip3?\s+(install|download|wheel)|-m\s+pip\s+(install|download|wheel)|py_deps\.py\s+build|uv\s+pip|curl|wget|apt-get|apt\s+install)\b")
ARTIFACT = re.compile(r"^py-deps-[a-z0-9-]+-(linux|windows)$")

GOOD = ("sample==1.0 ; sys_platform == 'win32' \\\n    --hash=sha256:" + "a" * 64 + " \\\n    --hash=sha256:" + "b" * 64 + "\n"
        "other==2.1.0 \\\n    --hash=sha256:" + "c" * 64 + "\n")


def workflow_problems(text: str) -> list:
    """What is wrong with a py-deps.yml: the rule, as checks on its steps."""
    import yaml
    doc = yaml.safe_load(text)
    problems = []
    steps = doc["jobs"]["wheels"]["steps"]
    by_id = {s.get("id"): s for s in steps if s.get("id")}
    spec = by_id.get("spec", {}).get("run", "")
    key_lines = [ln for ln in spec.splitlines() if ln.strip().startswith('echo "key=')]
    if len(key_lines) != 1:
        problems.append("no single `echo key=` line in the spec step")
    else:
        key = key_lines[0]
        for need, label in (("py-deps-$ImageOS-", "the image's OS (ImageOS)"), ("$RELEASE", "the image's release"), ("-py$PYMINOR-", "the Python's minor"),
                            ("-$SHA", "the spec's hash")):
            if need not in key:
                problems.append("the key lacks %s: %s" % (label, key.strip()))
    if 'RELEASE="${ImageVersion%%.*}"' not in spec:
        problems.append("the release is not the first number of ImageVersion")
    if "sha256sum" not in spec or "py_deps.py spec" not in spec:
        problems.append("the key's hash is not the sha256 of the spec py_deps.py writes")
    if "${ImageOS:?" not in spec or "${ImageVersion:?" not in spec:
        problems.append("the spec step does not fail on a missing ImageOS or ImageVersion")
    restore, save = by_id.get("restore"), None
    for s in steps:
        if str(s.get("uses", "")).startswith("actions/cache/save@"):
            save = s
    if restore is None or not str(restore.get("uses", "")).startswith("actions/cache/restore@"):
        problems.append("no actions/cache/restore step with id restore")
    elif restore["with"].get("key") != "${{ steps.spec.outputs.key }}":
        problems.append("the restore key is not the spec's")
    if save is None:
        problems.append("no actions/cache/save step")
    else:
        if save["with"].get("key") != "${{ steps.spec.outputs.key }}":
            problems.append("the save key is not the spec's")
        if save.get("if") != "steps.restore.outputs.cache-hit != 'true'":
            problems.append("the save step has no cache-miss condition")
    for s in steps:
        scripts = "\n".join([s.get("run", "")])
        if REACHES.search(scripts) and MISS not in str(s.get("if", "")):
            problems.append("step %r reaches the index and has no `if: %s`" % (s.get("name"), MISS))
    builds = [s for s in steps if "py_deps.py build" in s.get("run", "")]
    if len(builds) != 1:
        problems.append("%d steps run `py_deps.py build`, not one" % len(builds))
    uploads = [s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact@")]
    if len(uploads) != 1 or uploads[0]["with"].get("name") != "py-deps-${{ inputs.name }}-${{ steps.spec.outputs.os }}":
        problems.append("the artifact is not py-deps-<name>-<os>")
    for s in steps:
        uses = str(s.get("uses", ""))
        if uses and not re.search(r"@[0-9a-f]{40}$", uses.split(" ")[0]):
            problems.append("%s is not pinned to a commit" % uses)
    # Workflows run in the series repository, where this tree's scripts live under platform/ci/src/ (as release.yml's node job and checks.yml's core-ref job read them):
    # the resolver and the series' locks are checked out from there, the resolver runs from there, a series-owned lock is relative to it, and a lock of another
    # repository stays relative to that repository's root.
    first = steps[0]
    sparse = str((first.get("with") or {}).get("sparse-checkout", "")).split()
    if first.get("with", {}).get("path") != "py-deps-tools" or sparse != ["platform/ci/src/scripts/ci/py_deps.py", "platform/ci/src/scripts/ci/locks"]:
        problems.append("the resolver and the locks are not checked out from platform/ci/src/scripts/ci/ of the series")
    runs = "\n".join(str(s.get("run", "")) for s in steps)
    calls = re.findall(r"python (\S*py_deps\.py) ", runs)
    if not calls or any(c != "py-deps-tools/platform/ci/src/scripts/ci/py_deps.py" for c in calls):
        problems.append("py_deps.py is not run from py-deps-tools/platform/ci/src/scripts/ci/ (%s)" % calls)
    if 'LOCK_FILE="py-deps-tools/platform/ci/src/$LOCK"' not in spec or 'LOCK_FILE="py-deps-lock/$LOCK"' not in spec:
        problems.append("a series lock is not relative to platform/ci/src/, or a lock of another repository is not relative to its root")
    inputs = doc[True]["workflow_call"]["inputs"] if True in doc else doc["on"]["workflow_call"]["inputs"]
    for need in ("name", "python", "lock", "lock_repository", "lock_ref", "core_ref", "wrapper_ref", "runners"):
        if need not in inputs:
            problems.append("no input %s" % need)
    if doc["permissions"] != {"contents": "read"}:
        problems.append("permissions are not contents: read")
    return problems


def cases() -> list:
    out = []

    def add(name, ok):
        out.append(("py_deps: " + name, bool(ok)))

    def bad_lock(text):
        try:
            pd.parse_lock(text)
        except ValueError:
            return True
        return False

    # ── the lock format: red on a known-bad line of each kind
    add("a lock line with a range is refused", bad_lock("pytest>=7 \\\n    --hash=sha256:" + "a" * 64 + "\n"))
    add("a lock line with no version is refused", bad_lock("pytest \\\n    --hash=sha256:" + "a" * 64 + "\n"))
    add("an entry with no --hash is refused", bad_lock("pytest==9.0.0\nother==1.0 \\\n    --hash=sha256:" + "a" * 64 + "\n"))
    add("a hash that is not 64 hex characters of sha256 is refused", bad_lock("pytest==9.0.0 \\\n    --hash=sha256:abc\n")
        and bad_lock("pytest==9.0.0 \\\n    --hash=md5:" + "a" * 32 + "\n"))
    add("a URL, an editable and an index option are refused", all(bad_lock(t) for t in (
        "pytest @ https://example.invalid/p.whl \\\n    --hash=sha256:" + "a" * 64 + "\n", "-e ./core\n", "--index-url https://example.invalid/simple\n",
        "git+https://example.invalid/core@main\n")))
    add("a hash with no entry above it is refused", bad_lock("    --hash=sha256:" + "a" * 64 + "\n"))
    add("name==version with markers and hashes parses to name, version, marker, hashes",
        pd.parse_lock(GOOD) == [("sample", "1.0", "sys_platform == 'win32'", ["a" * 64, "b" * 64]), ("other", "2.1.0", "", ["c" * 64])])

    # ── the committed locks pass: every line name==version, every entry hashed, made from the committed input, the input from its source
    for name in pd.LOCK_NAMES:
        problems = pd.check_lock(name)
        add("lock %s: every line is name==version with a hash, made from its input, and its input is its source's%s"
            % (name, "" if not problems else ": " + "; ".join(problems)), not problems)
    for name in pd.LOCK_NAMES:
        entries = pd.parse_lock((pd.LOCKS / ("%s.txt" % name)).read_text(encoding="utf-8"))
        add("lock %s: %d entries, each with at least one sha256" % (name, len(entries)), entries and all(h for *_, h in entries))
    lav = {n: v for n, v, *_ in pd.parse_lock((pd.LOCKS / "lavapipe.txt").read_text(encoding="utf-8"))}
    pins = json.loads((HERE / "lavapipe" / "VERSIONS.json").read_text(encoding="utf-8"))["pip"]
    add("lock lavapipe holds exactly the versions lavapipe_build.py installs (VERSIONS.json), and MarkupSafe for mako",
        all(lav.get(pd.norm(k)) == v for k, v in pins.items()) and "markupsafe" in lav)
    mach = {pd.norm(n) for n, *_ in pd.parse_lock((pd.LOCKS / "mach.txt").read_text(encoding="utf-8"))}
    add("lock mach holds what mach.txt and build.txt install from the index (glean-sdk, orjson, psutil, rtoml, zstandard, pyyaml, taskcluster-taskgraph)",
        {"glean-sdk", "orjson", "psutil", "rtoml", "zstandard", "pyyaml", "taskcluster-taskgraph"} <= mach)
    tools = {pd.norm(n): v for n, v, *_ in pd.parse_lock((pd.LOCKS / "tools.txt").read_text(encoding="utf-8"))}
    add("lock tools holds pytest, pyyaml and fonttools==4.51.0", {"pytest", "pyyaml"} <= set(tools) and tools.get("fonttools") == "4.51.0")
    # A drifted input is red: the input of lavapipe says a package the source does not.
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp)
        (tree / "scripts" / "ci" / "lavapipe").mkdir(parents=True)
        (tree / "scripts" / "ci" / "lavapipe" / "VERSIONS.json").write_text(json.dumps({"pip": {"meson": "9.9.9"}}), encoding="utf-8")
        drift = pd.check_lock("lavapipe", tree)
        add("a lock whose input is not its source's is named (lavapipe against another VERSIONS.json)", any("not what its source says" in p for p in drift))

    # ── the generator is deterministic: same input, same bytes, whatever order and whatever uv printed
    header = "# header\n"
    raw_a = GOOD
    raw_b = ("other==2.1.0 \\\n    --hash=sha256:" + "c" * 64 + "\n"
             "sample==1.0 ; sys_platform == 'win32' \\\n    --hash=sha256:" + "b" * 64 + " \\\n    --hash=sha256:" + "a" * 64 + "\n")
    add("normalise: the same entries in another order, with the hashes in another order, give the same bytes",
        pd.normalise(raw_a, header) == pd.normalise(raw_b, header) and pd.normalise(raw_a, header) == pd.normalise(pd.normalise(raw_a, header), header))
    add("normalise: entries by name, hashes sorted, the last hash with no continuation",
        pd.normalise(raw_b, header).splitlines()[1].startswith("other==2.1.0") and pd.normalise(raw_b, header).endswith("--hash=sha256:" + "b" * 64 + "\n")
        and ("--hash=sha256:" + "a" * 64 + " \\\n") in pd.normalise(raw_b, header))
    with tempfile.TemporaryDirectory() as tmp:
        fake = Path(tmp) / "fake_uv.py"
        calls = Path(tmp) / "calls.json"
        fake.write_text("import json, sys\nopen(%r, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\nsys.stdout.write(open(%r).read())\n" % (str(calls), str(Path(tmp) / "raw.txt")),
                        encoding="utf-8")
        (Path(tmp) / "raw.txt").write_text(raw_b, encoding="utf-8")
        in_text = "# python-version: 3.11\n# exclude-newer: 2026-01-02T00:00:00Z\nsample\nother\n"
        first = pd.compile_lock(in_text, "fixture", [sys.executable, str(fake)])
        second = pd.compile_lock(in_text, "fixture", [sys.executable, str(fake)])
        argv = json.loads(calls.read_text(encoding="utf-8").splitlines()[0])
        add("compile_lock: a fixture compiled twice is byte-identical, and a lock made from it parses", first == second and len(pd.parse_lock(first)) == 2)
        add("compile_lock: uv is asked for a universal resolution with hashes, wheels only, at the input's Python and date",
            argv[:2] == ["pip", "compile"] and {"--universal", "--generate-hashes", "--no-build"} <= set(argv) and argv[argv.index("--python-version") + 1] == "3.11"
            and argv[argv.index("--exclude-newer") + 1] == "2026-01-02T00:00:00Z")
        add("compile_lock: the header names the input's sha256, the date and the Python (a lock is a function of its input)",
            hashlib_hex(in_text) in first and "--exclude-newer 2026-01-02T00:00:00Z" in first and "--python-version 3.11" in first)
        refused = False
        try:
            pd.compile_lock("sample\n", "fixture", [sys.executable, str(fake)])
        except SystemExit:
            refused = True
        add("compile_lock: an input with no date is refused (it would resolve to whatever is newest that day)", refused)

    # ── the spec, the wheelhouse, the consumer
    with tempfile.TemporaryDirectory() as tmp:
        lock_a, lock_b = Path(tmp) / "a.txt", Path(tmp) / "b.txt"
        lock_a.write_text(GOOD, encoding="utf-8")
        lock_b.write_text(GOOD.replace("2.1.0", "2.1.1"), encoding="utf-8")
        s = pd.spec_text(lock_a, "c" * 40, "d" * 40)
        add("spec: names the lock's sha256, the exact python -VV, both commits and the builder", pd.sha256(lock_a) in s and pd.python_vv() in s
            and "c" * 40 in s and "d" * 40 in s and "builder: sha256" in s and "wheel-build: sha256" in s)
        add("spec: another lock, another core commit, another wrapper commit or other extras is another spec",
            len({s, pd.spec_text(lock_b, "c" * 40, "d" * 40), pd.spec_text(lock_a, "e" * 40, "d" * 40), pd.spec_text(lock_a, "c" * 40, "e" * 40),
                 pd.spec_text(lock_a, "c" * 40, "d" * 40, core_extras="dev")}) == 5)
        house = Path(tmp) / "house"
        house.mkdir()
        (house / "lock.txt").write_text(GOOD, encoding="utf-8")
        (house / "refs.json").write_text(json.dumps({"core": {"dist": "invisible_core", "wheel": "x.whl", "sha256": "0", "commit": "c", "extras": ""},
                                                     "wrapper": {"dist": "invisible_playwright", "wheel": "y.whl", "sha256": "0", "commit": "d", "extras": ""}}),
                                         encoding="utf-8")
        cmds = pd.install_commands(house)
        flat = [" ".join(c) for c in cmds]
        add("consumer: every pip call has --no-index and --find-links, never an index option", all("--no-index" in c and "--find-links" in c for c in flat)
            and not any("--index-url" in c or "--extra-index-url" in c for c in flat))
        add("consumer: the lock's packages with --require-hashes -r lock.txt", "--require-hashes" in flat[0] and flat[0].rstrip().endswith("lock.txt"))
        add("consumer: ours by name with --no-deps (no path, no URL)", len(flat) == 3 and all("--no-deps" in c and not re.search(r"[/\\]\S*\.whl|://", c.split("--find-links", 1)[1].split(None, 1)[1])
                                                                                          for c in flat[1:]) and flat[1].endswith("invisible_core") and flat[2].endswith("invisible_playwright"))
        add("consumer: pip's own version check (a read of the index) is off", all("--disable-pip-version-check" in c for c in flat))

    # ── the workflow: the committed file passes, a known-bad copy of each rule does not
    text = WORKFLOW.read_text(encoding="utf-8")
    add("py-deps.yml: the committed workflow follows the rule%s" % ("" if not workflow_problems(text) else ": " + "; ".join(workflow_problems(text))), not workflow_problems(text))
    key = 'echo "key=py-deps-$ImageOS-$RELEASE-py$PYMINOR-$SHA"'
    add("py-deps.yml: the key is the image's OS, its release, the Python's minor and the spec's hash", key in text)

    def red(label, mutated, expect):
        found = workflow_problems(mutated) if mutated != text else []
        add("py-deps.yml: %s is red (%s)" % (label, expect), any(expect in p for p in found))

    red("a key without ImageOS", text.replace("py-deps-$ImageOS-", "py-deps-"), "image's OS")
    red("a key without the image's release", text.replace("-$RELEASE-py", "-py"), "image's release")
    red("a key without the Python's minor", text.replace("-py$PYMINOR-", "-"), "Python's minor")
    red("a key without the spec's hash", text.replace("py$PYMINOR-$SHA\"", "py$PYMINOR\""), "spec's hash")
    red("a release that is the whole ImageVersion (a key per build)", text.replace('RELEASE="${ImageVersion%%.*}"', 'RELEASE="$ImageVersion"'), "first number of ImageVersion")
    red("a build step without the cache-miss condition", re.sub(r"(      - name: A new image, Python, lock or ref[^\n]*\n)        if: [^\n]*\n", r"\1", text), "reaches the index")
    red("a cache save without the cache-miss condition", text.replace("      - name: Keep the entry\n        if: steps.restore.outputs.cache-hit != 'true'\n",
                                                                     "      - name: Keep the entry\n"), "save step has no cache-miss condition")
    red("an added unpinned pip install with no condition",
        text.replace("      - name: Keep the entry\n", "      - name: extra\n        run: python -m pip install pytest\n      - name: Keep the entry\n"), "reaches the index")
    red("an added curl with no condition", text.replace("      - name: Keep the entry\n", "      - name: extra\n        run: curl -sSL https://example.invalid/x\n      - name: Keep the entry\n"),
        "reaches the index")
    red("an artifact with another name", text.replace("name: py-deps-${{ inputs.name }}-${{ steps.spec.outputs.os }}", "name: wheels-${{ inputs.name }}"), "py-deps-<name>-<os>")
    red("an action that is not pinned to a commit", text.replace("actions/cache/save@55cc8345863c7cc4c66a329aec7e433d2d1c52a9", "actions/cache/save@v4"), "not pinned")
    red("a restore key that is not the spec's", text.replace("key: ${{ steps.spec.outputs.key }}\n      - name: A new image", "key: py-deps-fixed\n      - name: A new image"),
        "restore key")
    red("the resolver and the locks checked out from scripts/ci/ of the root (the old path: nothing there in the series)",
        text.replace("            platform/ci/src/scripts/ci/py_deps.py\n            platform/ci/src/scripts/ci/locks\n",
                     "            scripts/ci/py_deps.py\n            scripts/ci/locks\n"),
        "not checked out from platform/ci/src")
    red("the resolver run from scripts/ci/ of the checkout (the old path)", text.replace("py-deps-tools/platform/ci/src/scripts/ci/py_deps.py spec", "py-deps-tools/scripts/ci/py_deps.py spec"),
        "py_deps.py is not run from")
    red("a series lock read from the root of the checkout (the old path)", text.replace('LOCK_FILE="py-deps-tools/platform/ci/src/$LOCK"', 'LOCK_FILE="py-deps-tools/$LOCK"'),
        "not relative to platform/ci/src/")
    red("a lock of another repository read under platform/ci/src/", text.replace('LOCK_FILE="py-deps-lock/$LOCK"', 'LOCK_FILE="py-deps-lock/platform/ci/src/$LOCK"'),
        "not relative to platform/ci/src/")
    red("a spec step that does not fail without ImageOS", text.replace('"${ImageOS:?no ImageOS: not a GitHub runner image}" ', ""), "missing ImageOS")
    add("artifact names: py-deps-<name>-linux and -windows match the pattern, anything else does not",
        all(ARTIFACT.match(n) for n in ("py-deps-tools-linux", "py-deps-gate-windows", "py-deps-core-checks-linux"))
        and not any(ARTIFACT.match(n) for n in ("py-deps-tools", "wheels-tools-linux", "py-deps-tools-macos", "py-deps--linux ")))
    return out


def hashlib_hex(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    results = cases()
    for label, ok in results:
        print(("ok    " if ok else "FAIL  ") + label)
    print("%d/%d cases as expected" % (sum(ok for _, ok in results), len(results)))
    sys.exit(0 if all(ok for _, ok in results) else 1)
