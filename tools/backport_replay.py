"""A backport of upstream code, replayed on the revision Mozilla vendors (rule port-04).

The folder of a backport (BACKPORT.json, commits/, hooks.patch, MANIFEST.json, src/) carries the ordered list
of commits it needs: upstream's own, ours, and tests. This tool replays them on the vendored crates of a Mozilla
tag and says what the folder's vendored part has to be, so that nobody merges it by hand:

  1. The revision is read from the tag (gfx/wgpu_bindings/Cargo.toml), the crates from third_party/rust/ of the tag.
  2. Each commit, in order, is cut into the files Mozilla vendors (a crate's src/ and the files its checksum file
     lists); the others (tests, upstream's own Cargo.lock) are skipped and reported. A commit whose files apply in
     reverse, with its full context, is already in the revision: it is dropped and reported. A file that applies neither
     way is a conflict for a human, never a guess.
  3. Two pieces of glue follow the commits, produced by rules and never carried as text: an added line of a crate's
     Cargo.toml becomes the table `cargo vendor` writes (the workspace dependency expanded), and an added dependency
     of a package in upstream's Cargo.lock becomes the same line in Mozilla's Cargo.lock.
  4. The `.cargo-checksum.json` of every touched crate is regenerated (tools/regen_checksums.py).
  5. The result is a diff of the vendored paths, made as `export` makes hooks.patch (`git diff --binary
     --full-index --no-renames`), and the new files for the folder's src/.

Everything runs on git objects in a scratch repository that borrows the objects of the source repository: no
working tree, so no line-ending conversion, and the source repository is not written (except by `apply`).

    python tools/backport_replay.py report --source <repo> --tag <tag> --folder <folder>
    python tools/backport_replay.py check  --source <repo> [--tag <tag>] [--folder <folder>]   the folders against the replay
    python tools/backport_replay.py expect --source <repo> --tag <tag> --folder <folder> --out <dir>
    python tools/backport_replay.py record --source <repo> --tag <tag> --folder <folder>       vendored and contained_in
    python tools/backport_replay.py apply  --source <repo> --tag <tag> --folder <folder> --branch <branch>
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import regen_checksums  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BACKPORT = "BACKPORT.json"
VENDORED_DIR = "third_party/rust/"
LOCK = "Cargo.lock"
KINDS = ("upstream", "ours", "test")
HEX40 = re.compile(r"[0-9a-f]{40}")
IDENTITY = {"GIT_AUTHOR_NAME": "feder-cr", "GIT_COMMITTER_NAME": "feder-cr",
            "GIT_AUTHOR_EMAIL": "85809106+feder-cr@users.noreply.github.com",
            "GIT_COMMITTER_EMAIL": "85809106+feder-cr@users.noreply.github.com"}
DEPENDENCY_TABLES = ("dependencies", "dev-dependencies", "build-dependencies")


class Stop(Exception):
    """A step that only a hand could do: the replay stops there instead of inventing it."""


def in_scope(path: str) -> bool:
    """The paths the replay owns in a folder's hooks.patch: vendored crates and the lock."""
    return path.startswith(VENDORED_DIR) or path == LOCK


# ---------------------------------------------------------------------------------------------------- git

class Scratch:
    """A bare repository with an index of its own, borrowing the objects of `source`."""

    def __init__(self, source: Path, tmp: Path):
        self.source = Path(source)
        self.dir = Path(tmp) / "scratch.git"
        self.index = Path(tmp) / "index"
        subprocess.run(["git", "init", "--bare", "-q", str(self.dir)], check=True, capture_output=True)
        common = subprocess.run(["git", "-C", str(self.source), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                check=True, capture_output=True).stdout.decode().strip()
        alt = self.dir / "objects" / "info" / "alternates"
        alt.write_bytes(((Path(common) / "objects").as_posix() + "\n").encode("utf-8"))

    def run(self, *args, input=None, check=True, source=False):
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_OPTIONAL_LOCKS="0")
        if source:
            cmd = ["git", "-C", str(self.source)]
        else:
            cmd = ["git"]
            env.update(GIT_DIR=str(self.dir), GIT_INDEX_FILE=str(self.index))
        done = subprocess.run(cmd + ["-c", "core.autocrlf=false", "-c", "core.safecrlf=false"] + list(args),
                              env=env, input=input, capture_output=True)
        if check and done.returncode:
            raise subprocess.CalledProcessError(done.returncode, args, done.stdout, done.stderr)
        return done

    def out(self, *args, **kw) -> str:
        return self.run(*args, **kw).stdout.decode("utf-8", errors="replace").strip()

    def blob(self, ref: str) -> bytes:
        return self.run("cat-file", "blob", ref).stdout

    def hash(self, data: bytes) -> str:
        return self.out("hash-object", "-w", "--stdin", input=data)

    def blobs(self, oids: list) -> dict:
        """oid -> content, in one `cat-file --batch`."""
        if not oids:
            return {}
        data = self.run("cat-file", "--batch", input=("\n".join(oids) + "\n").encode()).stdout
        found, pos = {}, 0
        for oid in oids:
            end = data.index(b"\n", pos)
            head = data[pos:end].split()
            if len(head) != 3:
                raise Stop("object %s is missing" % oid)
            size = int(head[2])
            found[oid] = data[end + 1:end + 1 + size]
            pos = end + 1 + size + 1
        return found

    def entries(self, prefix: str) -> dict:
        """path -> (mode, oid) of the index under `prefix`."""
        raw = self.run("ls-files", "-s", "-z", "--", prefix).stdout
        found = {}
        for rec in raw.split(b"\0"):
            if rec:
                meta, path = rec.split(b"\t", 1)
                mode, oid, _stage = meta.decode().split()
                found[path.decode()] = (mode, oid)
        return found

    def load_tree(self, tree: str, prefix: str) -> None:
        """The files of `tree` into the index under `prefix` (a bare repository has no `read-tree --prefix`)."""
        raw = self.run("ls-tree", "-r", "-z", tree).stdout
        rows = []
        for rec in raw.split(b"\0"):
            if rec:
                meta, path = rec.split(b"\t", 1)
                mode, _kind, oid = meta.decode().split()
                rows.append(("%s %s\t" % (mode, oid)).encode() + prefix.encode() + path)
        self.run("update-index", "--add", "-z", "--index-info", input=b"\0".join(rows) + b"\0")

    def set(self, path: str, data: bytes, mode: str = "100644") -> None:
        self.run("update-index", "--add", "--cacheinfo", "%s,%s,%s" % (mode, self.hash(data), path))

    def remove(self, path: str) -> None:
        self.run("update-index", "--force-remove", "--", path)


# ---------------------------------------------------------------------------------------------------- patches

SECTION = re.compile(rb"(?m)^diff --git a/(.*?) b/(.*)$")


def split_sections(data: bytes) -> list:
    """[(path, bytes)]: each file's diff from its `diff --git` line to the next; a mail trailer after the last is cut."""
    marks = list(SECTION.finditer(data))
    found = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(data)
        found.append((m.group(2).decode("utf-8"), data[m.start():end]))
    if found:
        path, last = found[-1]
        lines = last.split(b"\n")
        while lines and (lines[-1] == b"" or lines[-1] == b"-- " or re.fullmatch(rb"\d+(\.\d+)+", lines[-1])):
            lines.pop()
        found[-1] = (path, b"\n".join(lines) + b"\n")
    return found


def rewrite(section: bytes, old: str, new: str) -> bytes:
    """The section with its file paths moved from `old` to `new` (header lines only)."""
    out, header = [], True
    for line in section.split(b"\n"):
        if header:
            if line.startswith(b"@@"):
                header = False
            else:
                for pre in (b"a/", b"b/"):
                    line = line.replace(pre + old.encode(), pre + new.encode())
        out.append(line)
    return b"\n".join(out)


def hunks(section: bytes) -> list:
    """[(header text after the second @@, [lines])] of a section."""
    found = []
    for line in section.decode("utf-8", errors="replace").split("\n"):
        if line.startswith("@@"):
            found.append((line.split("@@")[-1].strip(), []))
        elif found:
            found[-1][1].append(line)
    return found


# ---------------------------------------------------------------------------------------------------- the glue

def toml_stanza(name: str, spec: dict, workspace: dict) -> list:
    """The lines `cargo vendor` writes for a dependency whose source line is `name = { workspace = true, ... }`."""
    if spec.get("workspace") is not True:
        raise Stop("Cargo.toml: %s is not a workspace dependency: only that form is produced by rule" % name)
    base = workspace.get(name)
    if not base:
        raise Stop("Cargo.toml: BACKPORT.json workspace_dependencies has no %s (upstream's workspace table says "
                   "its version and features)" % name)
    unknown = set(spec) - {"workspace", "features", "optional"}
    if unknown:
        raise Stop("Cargo.toml: %s sets %s: not produced by rule" % (name, ", ".join(sorted(unknown))))
    features = list(base.get("features", []))
    features += [f for f in spec.get("features", []) if f not in features]
    lines = ["version = %s" % json.dumps(base["version"])]
    if len(features) == 1:
        lines.append("features = [%s]" % json.dumps(features[0]))
    elif features:
        lines += ["features = ["] + ["    %s," % json.dumps(f) for f in features] + ["]"]
    if base.get("default-features") is False:
        lines.append("default-features = false")
    if spec.get("optional"):
        lines.append("optional = true")
    return lines


def toml_additions(section: bytes) -> list:
    """[(table, name, spec)] the lines a Cargo.toml diff adds to a dependency table; Stop on anything else."""
    found = []
    for _head, lines in hunks(section):
        table = None
        for line in lines:
            text = line[1:] if line[:1] in "+- " else line
            header = re.fullmatch(r"\[(.+)\]\s*", text)
            if header and line[:1] != "-":
                table = header.group(1)
            if line.startswith("-"):
                raise Stop("Cargo.toml: the commit removes or changes the line %r: only added dependencies are produced "
                           "by rule" % text)
            if not line.startswith("+") or not text.strip():
                continue
            if table not in DEPENDENCY_TABLES:
                raise Stop("Cargo.toml: the commit adds %r in %s: only added dependencies are produced by rule"
                           % (text, "table %r" % table if table else "an unknown table"))
            try:
                parsed = tomllib.loads(text)
            except tomllib.TOMLDecodeError as exc:
                raise Stop("Cargo.toml: cannot read the added line %r (%s)" % (text, exc))
            for name, spec in parsed.items():
                found.append((table, name, spec if isinstance(spec, dict) else {"version": spec}))
    return found


def add_stanza(text: str, table: str, name: str, stanza: list):
    """`text` (a vendored Cargo.toml) with `[table.name]` added where `cargo vendor` puts it (the tables of that kind
    are in alphabetical order); None when it is already there."""
    if "\r" in text:
        raise Stop("Cargo.toml has carriage returns: not produced by rule")
    lines = text.split("\n")
    blocks = []
    for i, line in enumerate(lines):
        m = re.fullmatch(r"\[%s\.([^\]]+)\]" % re.escape(table), line)
        if m:
            blocks.append((i, m.group(1)))
    if any(n == name for _i, n in blocks):
        return None
    if not blocks:
        raise Stop("Cargo.toml has no [%s.*] table to place %s next to" % (table, name))
    new = ["[%s.%s]" % (table, name)] + stanza + [""]
    after = next((i for i, n in blocks if n > name), None)
    if after is not None:
        lines[after:after] = new
    else:
        last = blocks[-1][0]
        end = next((i for i in range(last + 1, len(lines)) if lines[i].startswith("[")), None)
        if end is None:
            body = lines[:-1] if lines[-1] == "" else lines
            lines = body + [""] + new[:-1] + [""]
        else:
            lines[end:end] = new
    return "\n".join(lines)


def lock_additions(section: bytes) -> list:
    """[(package, dependency)] the dependency entries an upstream Cargo.lock diff adds; Stop on anything else."""
    found = []
    for head, lines in hunks(section):
        package = re.fullmatch(r'name = "([^"]+)"', head).group(1) if re.fullmatch(r'name = "([^"]+)"', head) else None
        first = next((l for l in lines if l.strip()), "")
        inside = bool(re.fullmatch(r' "[^"]+",', first[1:]))      # a hunk that opens inside the list
        for line in lines:
            text = line[1:] if line[:1] in "+- " else line
            m = re.fullmatch(r'name = "([^"]+)"', text)
            if m:
                package, inside = m.group(1), False
            elif text.startswith("dependencies = ["):
                inside = True
            elif text == "]":
                inside = False
            if line.startswith("-"):
                raise Stop("Cargo.lock: the commit removes the line %r: not produced by rule" % text)
            if line.startswith("+"):
                entry = re.fullmatch(r' "([^"]+)",', text)
                if not (entry and inside and package):
                    raise Stop("Cargo.lock: the commit adds %r: only a dependency of a package is produced by rule" % text)
                found.append((package, entry.group(1)))
    return found


def add_lock_dependency(text: str, package: str, entry: str, revision: str) -> str | None:
    """Mozilla's Cargo.lock with `entry` among the dependencies of `package`; None when it is there already."""
    if "\r" in text:
        raise Stop("Cargo.lock has carriage returns: not produced by rule")
    blocks = text.split("\n\n")
    named = [i for i, b in enumerate(blocks) if re.search(r'(?m)^name = "%s"$' % re.escape(package), b)]
    if len(named) > 1:
        named = [i for i in named if revision in blocks[i]]
    if len(named) != 1:
        raise Stop("Cargo.lock: %d packages named %s match the vendored revision: not produced by rule" % (len(named), package))
    name = entry.split(" ")[0]
    versions = [i for i, b in enumerate(blocks) if re.search(r'(?m)^name = "%s"$' % re.escape(name), b)]
    if len(versions) != 1:
        raise Stop("Cargo.lock: %d packages are named %s, the entry %r would need a version Mozilla's lock decides: not "
                   "produced by rule" % (len(versions), name, entry))
    lines = blocks[named[0]].split("\n")
    start = next((i for i, l in enumerate(lines) if l == "dependencies = ["), None)
    if start is None:
        raise Stop("Cargo.lock: the package %s has no dependencies list" % package)
    end = lines.index("]", start)
    deps = lines[start + 1:end]
    if any(d.strip().strip(",").strip('"').split(" ")[0] == name for d in deps):
        return None
    new = ' "%s",' % name
    place = next((i for i, d in enumerate(deps) if d.strip().strip(",").strip('"').split(" ")[0] > name), len(deps))
    deps.insert(place, new)
    lines[start + 1:end] = deps
    blocks[named[0]] = "\n".join(lines)
    return "\n\n".join(blocks)


def sibling_problems(scratch: Scratch, name: str, base: dict) -> list:
    """BACKPORT.json's workspace entry against the stanzas of the vendored wgpu and naga crates of the tag, which all
    expand the same workspace table: the version equal, the features a superset."""
    found = []
    for path in sorted(scratch.entries(VENDORED_DIR)):
        crate = path[len(VENDORED_DIR):].split("/")[0]
        if not path.endswith("/Cargo.toml") or path.count("/") != 3 or not crate.startswith(("wgpu", "naga")):
            continue
        doc = tomllib.loads(scratch.blob(":" + path).decode("utf-8"))
        tables = [doc.get("dependencies", {})] + [t.get("dependencies", {}) for t in doc.get("target", {}).values()]
        for table in tables:
            spec = table.get(name)
            if isinstance(spec, dict) and (spec.get("version") != base.get("version")
                                           or not set(base.get("features", [])) <= set(spec.get("features", []))):
                found.append("%s: its %s is %s %s, workspace_dependencies says %s %s"
                             % (path, name, spec.get("version"), spec.get("features"), base.get("version"), base.get("features")))
    return found


# ---------------------------------------------------------------------------------------------------- the replay

@dataclass
class CommitResult:
    file: str
    kind: str
    status: str = ""             # applied, dropped, partial, conflict, tests, nothing
    carried: list = field(default_factory=list)
    contained: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)      # [(path, why)]
    glue: list = field(default_factory=list)


@dataclass
class Replay:
    tag: str
    revision: str
    commits: list
    sections: dict               # path -> diff bytes, for the modified (or deleted) vendored paths
    added: dict                  # path -> (mode, bytes), the new files
    notes: list = field(default_factory=list)

    @property
    def conflicts(self) -> list:
        return [(c.file, p, why) for c in self.commits for p, why in c.conflicts]

    @property
    def dropped(self) -> list:
        return [c for c in self.commits if c.status == "dropped"]

    @property
    def patch(self) -> bytes:
        return b"".join(self.sections[p] for p in sorted(self.sections, key=lambda p: p.encode()))

    def summary(self) -> str:
        lines = ["tag %s vendors wgpu %s" % (self.tag, self.revision)]
        for c in self.commits:
            extra = ""
            if c.status == "dropped":
                extra = " (already in the revision: %d files)" % len(c.contained)
            elif c.status == "partial":
                extra = " (in the revision: %s; applied: %s)" % (", ".join(c.contained), ", ".join(c.carried))
            elif c.conflicts:
                extra = " " + "; ".join("%s: %s" % x for x in c.conflicts)
            lines.append("  %-9s %s%s" % (c.status.upper() if c.conflicts or c.status == "partial" else c.status, c.file, extra))
            for g in c.glue:
                lines.append("            glue: %s" % g)
            if c.skipped:
                lines.append("            skipped: %s" % ", ".join(c.skipped))
        lines += ["  %s" % n for n in self.notes]
        lines.append("%d commits: %d applied, %d dropped, %d test-only, %d with conflicts" % (
            len(self.commits), sum(c.status == "applied" for c in self.commits), len(self.dropped),
            sum(c.status == "tests" for c in self.commits), sum(bool(c.conflicts) for c in self.commits)))
        return "\n".join(lines)


def vendored_revision(text: str) -> str:
    revs = set(re.findall(r'git = "https://github\.com/gfx-rs/wgpu"\nrev = "([0-9a-f]{40})"', text))
    if len(revs) != 1:
        raise Stop("gfx/wgpu_bindings/Cargo.toml names %d wgpu revisions, one expected" % len(revs))
    return revs.pop()


def load_record(folder: Path) -> dict:
    return json.loads((Path(folder) / BACKPORT).read_text(encoding="utf-8"))


def replay(source: Path, tag: str, folder: Path, record: dict | None = None) -> Replay:
    folder = Path(folder)
    record = record if record is not None else load_record(folder)
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Scratch(source, Path(tmp))
        return _replay(scratch, tag, folder, record)


def _replay(s: Scratch, tag: str, folder: Path, record: dict) -> Replay:
    rev_tree = s.out("rev-parse", "%s:third_party/rust" % tag, source=True)
    lock_oid = s.out("rev-parse", "%s:%s" % (tag, LOCK), source=True)
    revision = vendored_revision(s.blob(s.out("rev-parse", "%s:gfx/wgpu_bindings/Cargo.toml" % tag, source=True)).decode("utf-8"))
    s.load_tree(rev_tree, VENDORED_DIR)
    s.run("update-index", "--add", "--cacheinfo", "100644,%s,%s" % (lock_oid, LOCK))
    base = s.out("write-tree")
    crates = {p[len(VENDORED_DIR):].split("/")[0] for p in s.entries(VENDORED_DIR)}
    listed = {}

    def checksum_files(crate: str) -> set:
        if crate not in listed:
            path = "%s%s/%s" % (VENDORED_DIR, crate, regen_checksums.CHECKSUM)
            listed[crate] = set(json.loads(s.blob(":" + path))["files"]) if s.entries(path) else set()
        return listed[crate]

    workspace = record.get("workspace_dependencies", {})
    notes, results = [], []
    for entry in record["commits"]:
        patch_file = folder / entry["file"]
        result = CommitResult(entry["file"], entry["kind"])
        results.append(result)
        if entry["kind"] == "test":
            result.status = "tests"
            continue
        vendored, toml_parts, lock_part = [], [], None
        for path, section in split_sections(patch_file.read_bytes()):
            crate, _, rel = path.partition("/")
            if path == LOCK:
                lock_part = section
            elif crate in crates and rel == "Cargo.toml":
                toml_parts.append((crate, section))
            elif crate in crates and (rel.startswith("src/") or rel in checksum_files(crate)):
                new = VENDORED_DIR + path
                vendored.append((new, rewrite(section, path, new)))
            else:
                result.skipped.append(path)
        # What each file says: it applies as written, or the revision has its change already (it applies in reverse), or
        # it conflicts. Both applications use the full context of the commit: a file that fits neither way, because
        # Mozilla changed the lines next to the change, is a conflict for a human, never a guess.
        state = {}
        for path, section in vendored:
            def fits(*flags):
                return s.run("apply", "--cached", "--check", "--whitespace=nowarn", *flags, input=section,
                             check=False).returncode == 0
            if fits():
                state[path] = "applies"
            elif fits("--reverse"):
                state[path] = "contained"
            else:
                state[path] = "conflict"
        for path, section in vendored:
            if state[path] == "applies":
                s.run("apply", "--cached", "--whitespace=nowarn", input=section)
                result.carried.append(path)
            elif state[path] == "contained":
                result.contained.append(path)
            else:
                result.conflicts.append((path, "does not apply on the revision (neither forward nor in reverse)"))
        dropped = bool(vendored) and all(v == "contained" for v in state.values())
        if dropped:
            result.status = "dropped"
            continue
        if result.conflicts:
            result.status = "conflict"
        elif result.contained:
            result.status = "partial"
        elif result.carried or toml_parts or lock_part:
            result.status = "applied"
        else:
            result.status = "nothing"
        if result.contained and not result.conflicts:
            result.conflicts.append((", ".join(result.contained), "partly in the revision, partly not: a commit is whole or not at all"))
        try:
            for crate, section in toml_parts:
                for table, name, spec in toml_additions(section):
                    path = "%s%s/Cargo.toml" % (VENDORED_DIR, crate)
                    if name in workspace:
                        problems = sibling_problems(s, name, workspace[name])
                        if problems:
                            raise Stop("Cargo.toml: workspace_dependencies for %s disagrees with the tag: %s" % (name, "; ".join(problems)))
                    text = add_stanza(s.blob(":" + path).decode("utf-8"), table, name, toml_stanza(name, spec, workspace))
                    if text is not None:
                        s.set(path, text.encode("utf-8"))
                        result.glue.append("%s: [%s.%s] added in the form cargo vendor writes" % (path, table, name))
            if lock_part is not None:
                for package, dep in lock_additions(lock_part):
                    text = add_lock_dependency(s.blob(":" + LOCK).decode("utf-8"), package, dep, revision)
                    if text is not None:
                        s.set(LOCK, text.encode("utf-8"))
                        result.glue.append("Cargo.lock: %s depends on %s" % (package, dep.split(" ")[0]))
        except Stop as stop:
            result.conflicts.append(("glue", str(stop)))
            result.status = "conflict"
    # the checksum files of the touched crates
    after = s.out("write-tree")
    changes = _raw_diff(s, base, after)
    touched = sorted({p[len(VENDORED_DIR):].split("/")[0] for p in changes if p.startswith(VENDORED_DIR)})
    for crate in touched:
        prefix = "%s%s/" % (VENDORED_DIR, crate)
        path = prefix + regen_checksums.CHECKSUM
        old = s.blob(":" + path)
        before = s.entries(prefix)
        # the tag's own file must be what the tool writes for the tag's files, or the regeneration would carry its fault
        base_files = {p[len(prefix):]: o for p, (_m, o) in _tree_entries(s, base, prefix).items() if not p.endswith(regen_checksums.CHECKSUM)}
        contents = s.blobs(sorted(set(base_files.values())))
        bad = regen_checksums.disagreements(old, {p: regen_checksums.sha256(contents[o]) for p, o in base_files.items()})
        if bad:
            notes.append("the checksum file of %s disagrees with its files at the tag: %s" % (crate, "; ".join(bad[:5])))
        edits = {}
        for p, (status, _m, oid) in changes.items():
            if p.startswith(prefix):
                edits[p[len(prefix):]] = None if status == "D" else regen_checksums.sha256(s.blob(oid))
        s.set(path, regen_checksums.update(old, edits), before[path][0])
    final = s.out("write-tree")
    changes = _raw_diff(s, base, final)
    modified = sorted(p for p, (status, _m, _o) in changes.items() if status in ("M", "D"))
    sections = {}
    if modified:
        diff = s.run("diff", "--binary", "--full-index", "--no-renames", base, final, "--", *modified).stdout
        sections = {path: sec for path, sec in split_sections(diff)}
    added = {p: (mode, s.blob(oid)) for p, (status, mode, oid) in changes.items() if status == "A"}
    return Replay(tag, revision, results, sections, added, notes)


def _raw_diff(s: Scratch, base: str, other: str) -> dict:
    """path -> (status, mode of the new side, new oid)."""
    raw = s.run("diff-tree", "-r", "--raw", "--no-renames", "-z", base, other).stdout.split(b"\0")
    found = {}
    for meta, path in zip(raw[0::2], raw[1::2]):
        if meta:
            fields = meta.decode().lstrip(":").split()
            found[path.decode()] = (fields[4], fields[1], fields[3])
    return found


def _tree_entries(s: Scratch, tree: str, prefix: str) -> dict:
    raw = s.run("ls-tree", "-r", "-z", tree, "--", prefix).stdout
    found = {}
    for rec in raw.split(b"\0"):
        if rec:
            meta, path = rec.split(b"\t", 1)
            mode, _kind, oid = meta.decode().split()
            found[path.decode()] = (mode, oid)
    return found


# ---------------------------------------------------------------------------------------------------- the folder against it

def own_sections(patch: bytes) -> dict:
    return {p: sec for p, sec in split_sections(patch)}


def expected_patch(result: Replay, existing: bytes) -> bytes:
    """The folder's hooks.patch: the replay's sections of the vendored paths and, as they are, the folder's own hooks
    (its sections of every other path), in the order git writes them."""
    sections = {p: sec for p, sec in own_sections(existing).items() if not in_scope(p)}
    sections.update(result.sections)
    return b"".join(sections[p] for p in sorted(sections, key=lambda p: p.encode()))


def record_problems(folder: Path, record: dict) -> list:
    """What the series alone says about a backport record: no tag needed."""
    name = label(folder)
    found = []
    outside = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/]|~)|\.\.[\\/]|\\")

    def walk(value, where):
        if isinstance(value, dict):
            for k, v in value.items():
                walk(v, "%s.%s" % (where, k))
        elif isinstance(value, list):
            for i, v in enumerate(value):
                walk(v, "%s[%d]" % (where, i))
        elif isinstance(value, str) and outside.search(value):
            found.append("%s/%s: %s is a path outside the series (%s): everything a backport needs is in its folder"
                         % (name, BACKPORT, where, value[:60]))
    walk(record, "")
    if "ours_where" in record:
        found.append("%s/%s: ours_where points to a clone outside the series: our commits are files of the folder (commits/)"
                     % (name, BACKPORT))
    commits = record.get("commits")
    if not isinstance(commits, list) or not commits:
        return found + ["%s/%s: commits is empty or not a list" % (name, BACKPORT)]
    if not HEX40.fullmatch(str(record.get("vendored", ""))):
        found.append("%s/%s: vendored %r is not a full revision" % (name, BACKPORT, record.get("vendored")))
    listed = set()
    for i, c in enumerate(commits):
        if not isinstance(c, dict):
            found.append("%s/%s: commits[%d] is %r, not {file, sha256, kind, upstream_sha, contained_in}: one patch file "
                         "per commit, stored in the series" % (name, BACKPORT, i, c if isinstance(c, str) else type(c).__name__))
            continue
        where = "commits[%d]" % i
        if c.get("kind") not in KINDS:
            found.append("%s/%s: %s kind %r is none of %s" % (name, BACKPORT, where, c.get("kind"), "/".join(KINDS)))
        if c.get("kind") == "upstream" and not HEX40.fullmatch(str(c.get("upstream_sha", ""))):
            found.append("%s/%s: %s is an upstream pick with no full upstream_sha" % (name, BACKPORT, where))
        contained = c.get("contained_in")
        if "contained_in" not in c or (contained is not None and not HEX40.fullmatch(str(contained))):
            found.append("%s/%s: %s contained_in is null or the full upstream revision that contains the commit" % (name, BACKPORT, where))
        file = str(c.get("file", ""))
        if not re.fullmatch(r"commits/[A-Za-z0-9._-]+\.patch", file):
            found.append("%s/%s: %s file %r is not commits/<name>.patch" % (name, BACKPORT, where, file))
            continue
        listed.add(file)
        path = Path(folder) / file
        if not path.is_file():
            found.append("%s/%s: %s is not in the folder" % (name, BACKPORT, file))
            continue
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != c.get("sha256"):
            found.append("%s/%s: %s differs from the sha256 BACKPORT.json records: a commit of a backport is not edited, "
                         "it is replaced by the commit it should be, with its new sha256" % (name, BACKPORT, file))
        if c.get("kind") == "upstream" and str(c.get("upstream_sha", "")).encode() not in data:
            found.append("%s/%s: %s does not name upstream commit %s" % (name, BACKPORT, file, c.get("upstream_sha")))
    folder_commits = Path(folder) / "commits"
    if folder_commits.is_dir():
        for p in sorted(folder_commits.iterdir()):
            if "commits/%s" % p.name not in listed:
                found.append("%s/commits/%s is in no entry of %s" % (name, p.name, BACKPORT))
    return found


def folder_problems(result: Replay, folder: Path, record: dict) -> list:
    """The folder's vendored part (and src/ files of vendored paths) against the replay."""
    folder = Path(folder)
    name = label(folder)
    found = []
    if record.get("vendored") != result.revision:
        found.append("%s/%s: vendored is %s, the tag %s vendors %s: record it (backport_replay.py record)"
                     % (name, BACKPORT, record.get("vendored"), result.tag, result.revision))
    for c in result.commits:
        for path, why in c.conflicts:
            found.append("%s: %s: %s: %s" % (name, c.file, path, why))
    entries = {c["file"]: c for c in record["commits"]}
    for c in result.commits:
        contained = entries[c.file].get("contained_in")
        if c.status == "dropped" and contained is None:
            found.append("%s/%s: the revision %s already contains %s: record contained_in (backport_replay.py record)"
                         % (name, BACKPORT, result.revision[:10], c.file))
        if c.status != "dropped" and contained == result.revision:
            found.append("%s/%s: %s is recorded as contained in %s, which the replay does not find there"
                         % (name, BACKPORT, c.file, result.revision[:10]))
    for note in result.notes:
        found.append("%s: %s" % (name, note))
    patch_path = folder / "hooks.patch"
    existing = patch_path.read_bytes() if patch_path.exists() else b""
    have = {p: sec for p, sec in own_sections(existing).items() if in_scope(p)}
    names_wrong = []
    for p in sorted(set(have) | set(result.sections)):
        if have.get(p) == result.sections.get(p):
            continue
        if p.endswith(regen_checksums.CHECKSUM):
            names_wrong.append(p)
            found.append("%s/hooks.patch: the line of %s is not the one the checksum tool produces for the replayed files "
                         "(a checksum line is regenerated, never merged or edited by hand)" % (name, p))
        elif p not in result.sections:
            found.append("%s/hooks.patch changes %s, which no commit of the backport touches" % (name, p))
        elif p not in have:
            found.append("%s/hooks.patch lacks the change to %s that the commits make" % (name, p))
        else:
            found.append("%s/hooks.patch differs from the replay of the commits in %s" % (name, p))
    if not found and existing != expected_patch(result, existing):
        found.append("%s/hooks.patch holds the replayed sections in another order than git writes them" % name)
    manifest = json.loads((folder / "MANIFEST.json").read_text(encoding="utf-8"))
    for p, (mode, data) in sorted(result.added.items()):
        stored = folder / "src" / p
        if manifest["added"].get(p) != mode:
            found.append("%s/MANIFEST.json does not list %s (mode %s) as added: the commits create it" % (name, p, mode))
        elif not stored.is_file() or stored.read_bytes() != data:
            found.append("%s/src/%s differs from the file the commits create" % (name, p))
    for p in sorted(manifest["added"]):
        if in_scope(p) and p not in result.added:
            found.append("%s/MANIFEST.json lists %s as added, a vendored path no commit creates: upstream code in src/ is a "
                         "commit, not a copy" % (name, p))
    return found


def label(folder: Path, root: Path = ROOT) -> str:
    """The folder as the series names it (its path from the root), or its own name when it is not under the root."""
    folder, root = Path(folder).resolve(), Path(root).resolve()
    return folder.relative_to(root).as_posix() if root in folder.parents else folder.name


def backport_folders(series: Path = ROOT) -> list:
    """The folders of the series whose BACKPORT.json is a replayable list of commits."""
    found = []
    for record in sorted(Path(series).glob("*/**/" + BACKPORT)):
        if "src" in record.relative_to(series).parts:
            continue
        data = json.loads(record.read_text(encoding="utf-8"))
        if isinstance(data.get("commits"), list) and data["commits"] and isinstance(data["commits"][0], dict):
            found.append(record.parent)
    return found


def check_folders(source: Path, tag: str, folders: list) -> list:
    found = []
    for folder in folders:
        record = load_record(folder)
        bad = record_problems(folder, record)
        found += bad
        if bad:
            continue
        try:
            found += folder_problems(replay(source, tag, folder, record), folder, record)
        except Stop as stop:
            found.append("%s: %s" % (label(folder), stop))
    return found


# ---------------------------------------------------------------------------------------------------- record, apply

def record_drops(folder: Path, result: Replay) -> bool:
    """BACKPORT.json after a port: `vendored` is the revision of the tag and every commit the replay dropped has
    `contained_in` set to it (an entry already set stays). The one thing about the record the tool writes."""
    record = load_record(folder)
    record["vendored"] = result.revision
    names = {c.file for c in result.dropped}
    for c in record["commits"]:
        if c["file"] in names and c.get("contained_in") is None:
            c["contained_in"] = result.revision
    (Path(folder) / BACKPORT).write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8", newline="\n")
    return True


def apply_to_commit(source: Path, tag: str, folder: Path, head: str, when: str | None = None,
                    record: dict | None = None) -> tuple:
    """A commit on `head` (a commit of `source`) holding the vendored part of the folder as the replay makes it: for every
    path the folder owns (its MANIFEST) or the replay changes, the replay's content, or the tag's where the replay leaves
    the path alone. Returns (commit, replay). A conflict stops it: nothing is written but unreferenced objects."""
    folder = Path(folder)
    record = record if record is not None else load_record(folder)
    with tempfile.TemporaryDirectory() as tmp:
        s = Scratch(source, Path(tmp))
        result = _replay(s, tag, folder, record)
        if result.conflicts:
            raise Stop("the replay has conflicts: %s" % "; ".join("%s: %s" % (p, w) for _c, p, w in result.conflicts))
        manifest = json.loads((folder / "MANIFEST.json").read_text(encoding="utf-8"))
        paths = {p for p in manifest["modified"] if in_scope(p)} | set(result.sections) | set(result.added)
        paths |= {p for p in manifest["added"] if in_scope(p)}
        env = dict(os.environ, **IDENTITY, GIT_INDEX_FILE=str(Path(tmp) / "branch-index"))
        if when:
            env.update(GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)

        def git(*args, input=None):
            done = subprocess.run(["git", "-C", str(source), "-c", "core.autocrlf=false"] + list(args), env=env,
                                  input=input, capture_output=True)
            if done.returncode:
                raise subprocess.CalledProcessError(done.returncode, args, done.stdout, done.stderr)
            return done.stdout.decode().strip()
        parent = git("rev-parse", "%s^{commit}" % head)
        git("read-tree", parent)
        final = s.out("write-tree")
        replayed = _tree_entries(s, final, VENDORED_DIR)
        replayed.update(_tree_entries(s, final, LOCK))
        for path in sorted(paths):
            if path in replayed:
                mode, oid = replayed[path]
                blob = git("hash-object", "-w", "--stdin", input=s.blob(oid))
                git("update-index", "--add", "--cacheinfo", "%s,%s,%s" % (mode, blob, path))
            else:
                git("update-index", "--force-remove", "--", path)
        message = "%s: the vendored part rebuilt by replaying its commits on %s" % (label(folder), tag)
        return git("commit-tree", git("write-tree"), "-p", parent, "-m", message), result


def apply_to_branch(source: Path, tag: str, folder: Path, branch: str) -> str:
    """apply_to_commit on the tip of `branch`, which moves to the new commit."""
    commit, _result = apply_to_commit(source, tag, folder, "refs/heads/%s" % branch)
    subprocess.run(["git", "-C", str(source), "update-ref", "refs/heads/%s" % branch, commit], check=True, capture_output=True)
    return commit


# ---------------------------------------------------------------------------------------------------- command line

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["report", "check", "expect", "record", "apply"])
    ap.add_argument("--source", type=Path, required=True, help="the Firefox source repository holding the tag")
    ap.add_argument("--tag", help="the Mozilla tag (default: mozilla_tag of UPSTREAM.json)")
    ap.add_argument("--folder", type=Path, help="the backport folder (check: every backport folder of the series)")
    ap.add_argument("--out", type=Path, help="expect: where to write hooks.patch and src/")
    ap.add_argument("--branch", help="apply: the branch of --source that gets the commit")
    a = ap.parse_args(argv)
    tag = a.tag or json.loads((ROOT / "UPSTREAM.json").read_text(encoding="utf-8"))["mozilla_tag"]
    try:
        if a.command == "check":
            folders = [a.folder] if a.folder else backport_folders()
            found = check_folders(a.source, tag, folders)
            for p in found:
                print("FAIL", p)
            if not found:
                print("ok: %d backport folders equal the replay of their commits on %s" % (len(folders), tag))
            return 1 if found else 0
        if a.folder is None:
            ap.error("%s needs --folder" % a.command)
        if a.command == "apply":
            if not a.branch:
                ap.error("apply needs --branch")
            print(apply_to_branch(a.source, tag, a.folder, a.branch))
            return 0
        result = replay(a.source, tag, a.folder)
        print(result.summary())
        if a.command == "expect":
            if a.out is None:
                ap.error("expect needs --out")
            a.out.mkdir(parents=True, exist_ok=True)
            existing = (a.folder / "hooks.patch").read_bytes() if (a.folder / "hooks.patch").exists() else b""
            (a.out / "hooks.patch").write_bytes(expected_patch(result, existing))
            for path, (_mode, data) in result.added.items():
                (a.out / "src" / path).parent.mkdir(parents=True, exist_ok=True)
                (a.out / "src" / path).write_bytes(data)
        if a.command == "record":
            record_drops(a.folder, result)
        return 1 if result.conflicts else 0
    except Stop as stop:
        print("STOP:", stop)
        return 1


if __name__ == "__main__":
    sys.exit(main())
