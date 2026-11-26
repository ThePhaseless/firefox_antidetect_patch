#!/usr/bin/env python3
"""The Python packages of a CI job, resolved ONCE per state and installed from files, by name, offline.

    python3 scripts/ci/py_deps.py lock NAME [--core-pyproject FILE --core-ref REF] [--exclude-newer DATE]
    python3 scripts/ci/py_deps.py check NAME          the lock still matches its input and the input its source
    python3 scripts/ci/py_deps.py spec  --lock FILE --out FILE [--core SHA] [--wrapper SHA] [--core-extras X] [--wrapper-extras X]
    python3 scripts/ci/py_deps.py build --lock FILE --house DIR [--core DIR] [--wrapper DIR] [--core-extras X] [--wrapper-extras X]
    python3 scripts/ci/py_deps.py install --house DIR     (the consumer: offline, by name, hashes required)

The rule (ci-03): a list of packages is resolved against the exact state it is installed on, once per state, by one job
(.github/workflows/py-deps.yml); the result is kept in a cache keyed by that state and the list; the legs install only from it, offline,
by name. No unpinned install anywhere.

THE LOCKS (scripts/ci/locks/<name>.txt, series-owned): a pip requirements file with an exact version and a `--hash=sha256:` for EVERY file of
that version on the index (every platform: Linux and Windows wheels, every Python from the lock's floor, and the sdist), so one lock serves every
OS and Python a consumer runs on. They are made by `lock`, which runs `uv pip compile --universal --generate-hashes` on the input
scripts/ci/locks/<name>.in and normalises what uv prints (entries by name, hashes sorted, one header). uv, not pip-compile: pip-compile resolves
for the machine it runs on (one OS, one Python) and a lock for two OSes would be two files and two sets of hashes; uv's universal resolution
is one resolution with environment markers, the file pip reads as it is. `--exclude-newer` (the date in the input's header) makes a lock a function of
its input: regenerating it later gives the same bytes; moving the date is a decision, and a reviewed diff. `--no-build`: a package with no wheel
for a consumer's platform fails the resolution here, as `pip download --only-binary=:all:` fails in the resolver job; no setup.py ever runs in CI.

The input of a lock is a function of its source, so it cannot drift from it: `lock` writes it, `check` (and test_py_deps.py) compares it again:
  tools         scripts/ci/locks/tools.in (pytest, pytest-xdist for the gate's `pytest -n`, pyyaml, fonttools==4.51.0: the checks' and the tree checks' tools)
  core-checks   the third-party dependencies and the `dev` extra of the core's pyproject.toml at the ref the series pins (the core wheel itself is built
                by the resolver from the core ref, --no-deps)
  lavapipe      scripts/ci/lavapipe/VERSIONS.json, "pip" (what lavapipe_build.py installs)
  mach          the pypi and pypi-optional lines of python/sites/mach.txt and build.txt (what `./mach build` installs from the index), and the
                vendored-fallback pyyaml at the version third_party/python/requirements.txt pins (as mach reads it)
  wheel-build   the build backend of the core and of the wrapper (hatchling), so building their wheels in the resolver needs no unpinned index read
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TREE = HERE.parent.parent
LOCKS = HERE / "locks"
LOCK_NAMES = ("tools", "core-checks", "lavapipe", "mach", "wheel-build")
PYTHON_FLOOR = {"tools": "3.11", "core-checks": "3.11", "lavapipe": "3.11", "mach": "3.11", "wheel-build": "3.11"}
HASH_RE = re.compile(r"^--hash=sha256:[0-9a-f]{64}$")
PIN_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*(?:\[[A-Za-z0-9,._-]+\])?)==([A-Za-z0-9][A-Za-z0-9.!+_-]*)(?: ; (.+))?$")


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


# ── the inputs ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def read_in(text: str) -> dict:
    """The input file: `# key: value` header lines, then one requirement per line."""
    meta, reqs = {}, []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^#\s*([a-z-]+):\s*(.*)$", line)
        if m:
            meta[m.group(1)] = m.group(2).strip()
        elif not line.startswith("#"):
            reqs.append(line)
    return {"meta": meta, "requirements": reqs}


def write_in(meta: dict, requirements: list, why: str) -> str:
    head = ["# %s" % why] + ["# %s: %s" % (k, v) for k, v in meta.items()]
    return "\n".join(head + sorted(set(requirements), key=lambda r: (norm(re.split(r"[\[<>=!~ ;]", r)[0]), r))) + "\n"


def _sites_requirements(tree: Path) -> list:
    """What mach installs from the index: the pypi and pypi-optional lines of its two sites, the way python/mach/mach/requirements.py reads them."""
    out = []
    for site in ("mach", "build"):
        for raw in (tree / "python" / "sites" / ("%s.txt" % site)).read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            action, params = line.split(":", 1)
            if action == "pypi":
                out.append(params)
            elif action == "pypi-optional":
                out.append(params.rsplit(":", 1)[0])
            elif action == "vendored-fallback":
                pkg = params.split(":")[0]
                text = (tree / "third_party" / "python" / "requirements.txt").read_text(encoding="utf-8")
                found = re.findall(r"^(%s==[^ ]+) \\$" % re.escape(pkg), text, re.M)
                if len(found) != 1:
                    raise SystemExit("vendored-fallback %s is not pinned once in third_party/python/requirements.txt" % pkg)
                out.append(found[0])
    return out


def derive(name: str, tree: Path = TREE, core_pyproject: Path | None = None) -> list | None:
    """The requirements a lock must cover, from the source the lock follows; None for an input that is its own source (tools)."""
    if name == "lavapipe":
        pins = json.loads((tree / "scripts" / "ci" / "lavapipe" / "VERSIONS.json").read_text(encoding="utf-8"))["pip"]
        return ["%s==%s" % kv for kv in pins.items()]
    if name == "mach":
        return _sites_requirements(tree)
    if name == "core-checks":
        if core_pyproject is None:
            return None
        import tomllib
        project = tomllib.loads(Path(core_pyproject).read_text(encoding="utf-8"))["project"]
        return list(project["dependencies"]) + list(project["optional-dependencies"]["dev"])
    return None


# ── the lock ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def parse_lock(text: str) -> list:
    """[(name, version, marker, [hashes])] of a lock file. A line that is not `name==version [; marker]` with hashes under it is an error: a range, a URL,
    an editable, an index option, an entry with no hash."""
    entries, current = [], None
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        body = line.strip()
        if body.endswith("\\"):
            body = body[:-1].rstrip()
        if body.startswith("--hash="):
            if current is None or not HASH_RE.match(body):
                raise ValueError("line %d: a hash that is not sha256:<64 hex>, or none to hold it: %r" % (lineno, body))
            current[3].append(body.split(":", 1)[1])
            continue
        m = PIN_RE.match(body)
        if not m or line[0] in " \t":
            raise ValueError("line %d: not `name==version`: %r" % (lineno, body))
        current = (m.group(1), m.group(2), m.group(3) or "", [])
        entries.append(current)
    for name, version, _, hashes in entries:
        if not hashes:
            raise ValueError("%s==%s has no --hash" % (name, version))
    return entries


def normalise(raw: str, header: str) -> str:
    """What uv printed (no header, no annotations) as a lock: entries by name, hashes sorted, the given header. Same input, same bytes."""
    entries = sorted(parse_lock(raw), key=lambda e: (norm(e[0]), e[1], e[2]))
    lines = [header.rstrip("\n")]
    for name, version, marker, hashes in entries:
        lines.append("%s==%s%s \\" % (name, version, (" ; " + marker) if marker else ""))
        hs = sorted(set(hashes))
        lines += ["    --hash=sha256:%s%s" % (h, " \\" if i < len(hs) - 1 else "") for i, h in enumerate(hs)]
    return "\n".join(lines) + "\n"


def lock_header(name: str, in_text: str, meta: dict) -> str:
    return "\n".join([
        "# Generated by `python scripts/ci/py_deps.py lock %s`: do not edit. Series-owned (ci-03)." % name,
        "# input: scripts/ci/locks/%s.in sha256 %s" % (name, hashlib.sha256(in_text.encode("utf-8")).hexdigest()),
        "# resolver: uv pip compile --universal --generate-hashes --no-build --python-version %s --exclude-newer %s"
        % (meta["python-version"], meta["exclude-newer"]),
        "# Every file of each version is hashed (Linux and Windows wheels of every Python from %s, and the sdist): one lock for every OS." % meta["python-version"],
        "# A consumer installs it with: pip install --no-index --find-links <wheelhouse> --require-hashes -r <this file>",
    ]) + "\n"


def compile_lock(in_text: str, name: str, uv: str | list = "uv") -> str:
    meta = read_in(in_text)["meta"]
    for key in ("python-version", "exclude-newer"):
        if key not in meta:
            raise SystemExit("locks/%s.in has no `# %s:` header" % (name, key))
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.txt"
        src.write_text("\n".join(read_in(in_text)["requirements"]) + "\n", encoding="utf-8")
        out = subprocess.run([*([uv] if isinstance(uv, str) else uv), "pip", "compile", str(src), "--universal", "--generate-hashes", "--no-build", "--no-header", "--no-annotate",
                              "--quiet", "--python-version", meta["python-version"], "--exclude-newer", meta["exclude-newer"]],
                             check=True, capture_output=True, text=True).stdout
    return normalise(out, lock_header(name, in_text, meta))


def cmd_lock(a) -> int:
    path_in = LOCKS / ("%s.in" % a.name)
    old = read_in(path_in.read_text(encoding="utf-8")) if path_in.exists() else {"meta": {}, "requirements": []}
    meta = dict(old["meta"])
    meta.setdefault("python-version", PYTHON_FLOOR[a.name])
    meta["exclude-newer"] = a.exclude_newer or meta.get("exclude-newer") or "2026-11-25T00:00:00Z"
    reqs = old["requirements"]
    derived = derive(a.name, TREE, Path(a.core_pyproject) if a.core_pyproject else None)
    if derived is not None:
        reqs = derived
        if a.name == "core-checks":
            meta["source"] = "oss-invisible/core %s pyproject.toml sha256 %s" % (a.core_ref or "?", sha256(Path(a.core_pyproject)))
    why = "Input of the %s lock; `python scripts/ci/py_deps.py lock %s` writes %s.txt from it." % (a.name, a.name, a.name)
    in_text = write_in(meta, reqs, why)
    path_in.write_text(in_text, encoding="utf-8", newline="\n")
    (LOCKS / ("%s.txt" % a.name)).write_text(compile_lock(in_text, a.name, a.uv), encoding="utf-8", newline="\n")
    print("locks/%s.in, locks/%s.txt written (%d direct requirements)" % (a.name, a.name, len(reqs)))
    return 0


def check_lock(name: str, tree: Path = TREE) -> list:
    """Problems of a committed lock: [] when its input is its source's, its header names its input, and it parses with every entry hashed."""
    problems = []
    in_path, txt_path = LOCKS / ("%s.in" % name), LOCKS / ("%s.txt" % name)
    if not in_path.exists() or not txt_path.exists():
        return ["locks/%s.in or locks/%s.txt is missing" % (name, name)]
    in_text = in_path.read_text(encoding="utf-8")
    derived = derive(name, tree)
    if derived is not None:
        have = sorted(read_in(in_text)["requirements"])
        if have != sorted(set(derived)):
            problems.append("locks/%s.in is not what its source says: input %s, source %s" % (name, have, sorted(set(derived))))
    text = txt_path.read_text(encoding="utf-8")
    want = "# input: scripts/ci/locks/%s.in sha256 %s" % (name, hashlib.sha256(in_text.encode("utf-8")).hexdigest())
    if want not in text.splitlines():
        problems.append("locks/%s.txt was not made from the present locks/%s.in (run `py_deps.py lock %s`)" % (name, name, name))
    try:
        entries = parse_lock(text)
    except ValueError as e:
        return problems + [str(e)]
    locked = {norm(n.split("[")[0]) for n, _, _, _ in entries}
    for req in read_in(in_text)["requirements"]:
        base = norm(re.split(r"[\[<>=!~ ;]", req)[0])
        if base not in locked:
            problems.append("%s is in the input and not in the lock" % base)
    return problems


def cmd_check(a) -> int:
    problems = check_lock(a.name)
    for p in problems:
        print("ERROR: " + p, file=sys.stderr)
    return 1 if problems else 0


# ── the state, the wheelhouse, the consumer ──────────────────────────────────────────────────────────────────────────────────────────────────

def python_vv(python: str = sys.executable) -> str:
    return subprocess.run([python, "-VV"], check=True, capture_output=True, text=True).stdout.strip()


def spec_text(lock: Path, core: str = "", wrapper: str = "", core_extras: str = "", wrapper_extras: str = "", python: str = sys.executable) -> str:
    """The state a wheelhouse is for: the lock, the exact interpreter, the commits whose wheels are built, the builder (this script and the lock of
    the build backend). The cache key is the hash of this text next to the image's OS, its release and the Python's minor."""
    return "\n".join([
        "form: wheelhouse of a lock",
        "lock: sha256 %s" % sha256(lock),
        "python: %s" % python_vv(python),
        "core: %s extras=%s" % (core or "-", core_extras),
        "wrapper: %s extras=%s" % (wrapper or "-", wrapper_extras),
        "builder: sha256 %s" % sha256(Path(__file__)),
        "wheel-build: sha256 %s" % sha256(LOCKS / "wheel-build.txt"),
    ]) + "\n"


def pip(*args: str, python: str = sys.executable) -> list:
    return [python, "-m", "pip", "--disable-pip-version-check", *args]


def build_house(lock: Path, house: Path, core: Path | None = None, wrapper: Path | None = None, core_extras: str = "", wrapper_extras: str = "",
                python: str = sys.executable) -> dict:
    """THE ONLY PLACE THAT READS THE INDEX: every file the lock names (hash-checked, wheels only), the wheels of ours (built with a build backend taken from
    its own lock, --no-deps), and the proof the whole is installable offline. Returns refs.json's content."""
    house.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PIP_DISABLE_PIP_VERSION_CHECK="1")
    subprocess.run(pip("download", "--only-binary=:all:", "--require-hashes", "--no-deps", "-r", str(lock), "-d", str(house), python=python), check=True, env=env)
    refs = {}
    sources = [(k, p, x) for k, p, x in (("core", core, core_extras), ("wrapper", wrapper, wrapper_extras)) if p is not None]
    if sources:
        subprocess.run(pip("install", "--require-hashes", "-r", str(LOCKS / "wheel-build.txt"), python=python), check=True, env=env)
    for kind, src, extras in sources:
        before = set(house.glob("*.whl"))
        subprocess.run(pip("wheel", "--no-deps", "--no-build-isolation", "-w", str(house), str(src), python=python), check=True, env=env)
        new = sorted(set(house.glob("*.whl")) - before)
        if len(new) != 1:
            raise SystemExit("the build of the %s made %d wheels, not one: %s" % (kind, len(new), [w.name for w in new]))
        sha = subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
        refs[kind] = {"dist": new[0].name.split("-")[0], "wheel": new[0].name, "sha256": sha256(new[0]), "commit": sha, "extras": extras}
    shutil.copyfile(lock, house / "lock.txt")
    # The proof, offline: the lock alone, then each wheel of ours with its extras against what the house holds. A dependency a wheel declares that the
    # lock does not cover is named by pip here, in the resolver, red.
    offline = ("install", "--dry-run", "--ignore-installed", "--no-index", "--find-links", str(house))
    subprocess.run(pip(*offline, "--require-hashes", "-r", str(house / "lock.txt"), python=python), check=True, env=env)
    for kind in refs:
        target = refs[kind]["dist"] + ("[%s]" % refs[kind]["extras"] if refs[kind]["extras"] else "")
        subprocess.run(pip(*offline, target, python=python), check=True, env=env)
    (house / "refs.json").write_text(json.dumps(refs, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return refs


def install_commands(house: Path, python: str = sys.executable) -> list:
    """The consumer, as commands: the lock's packages offline with their hashes, ours by name, no dependencies, no index."""
    house = Path(house)
    cmds = [pip("install", "--no-index", "--find-links", str(house), "--require-hashes", "-r", str(house / "lock.txt"), python=python)]
    refs = json.loads((house / "refs.json").read_text(encoding="utf-8")) if (house / "refs.json").exists() else {}
    for kind in sorted(refs):
        cmds.append(pip("install", "--no-index", "--no-deps", "--find-links", str(house), refs[kind]["dist"], python=python))
    return cmds


def cmd_install(a) -> int:
    house = Path(a.house)
    refs = json.loads((house / "refs.json").read_text(encoding="utf-8")) if (house / "refs.json").exists() else {}
    for kind, ref in refs.items():
        if sha256(house / ref["wheel"]) != ref["sha256"]:
            print("ERROR: the %s wheel is not the one the resolver built (sha256)" % kind, file=sys.stderr)
            return 1
    for cmd in install_commands(house):
        print("+ " + " ".join(cmd), flush=True)
        subprocess.run(cmd, check=True, env=dict(os.environ, PIP_DISABLE_PIP_VERSION_CHECK="1"))
    subprocess.run(pip("check"), check=True)
    return 0


def cmd_build(a) -> int:
    build_house(Path(a.lock), Path(a.house), Path(a.core) if a.core else None, Path(a.wrapper) if a.wrapper else None, a.core_extras, a.wrapper_extras)
    return 0


def cmd_spec(a) -> int:
    Path(a.out).write_text(spec_text(Path(a.lock), a.core, a.wrapper, a.core_extras, a.wrapper_extras), encoding="utf-8", newline="\n")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("lock")
    p.add_argument("name", choices=LOCK_NAMES)
    p.add_argument("--core-pyproject")
    p.add_argument("--core-ref")
    p.add_argument("--exclude-newer")
    p.add_argument("--uv", default="uv")
    p.set_defaults(fn=cmd_lock)
    p = sub.add_parser("check")
    p.add_argument("name", choices=LOCK_NAMES)
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("spec")
    p.add_argument("--lock", required=True)
    p.add_argument("--out", required=True)
    for opt in ("--core", "--wrapper", "--core-extras", "--wrapper-extras"):
        p.add_argument(opt, default="")
    p.set_defaults(fn=cmd_spec)
    p = sub.add_parser("build")
    p.add_argument("--lock", required=True)
    p.add_argument("--house", required=True)
    p.add_argument("--core")
    p.add_argument("--wrapper")
    p.add_argument("--core-extras", default="")
    p.add_argument("--wrapper-extras", default="")
    p.set_defaults(fn=cmd_build)
    p = sub.add_parser("install")
    p.add_argument("--house", required=True)
    p.set_defaults(fn=cmd_install)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
