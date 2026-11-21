#!/usr/bin/env python3
"""The package manifest A/B of the engine's gate: the files of the archives of the engine published before, against the candidate's.

    python3 scripts/ci/ab_package.py seal-check <dir> [--github-output file]
    python3 scripts/ci/ab_package.py list <archive> [--out list.json]
    python3 scripts/ci/ab_package.py explain --series <dir> --from <commit> --to <commit> [--out explained.json]
    python3 scripts/ci/ab_package.py compare <published> <candidate> [--explained explained.json] [--report report.json] [--summary summary.md]

`seal-check` judges a downloaded release: every archive the seal names is in <dir>, with the sha256 and the size the seal says and the sha256 of
checksums.txt; it prints the series commit of the seal (and appends series_commit=<sha> to the file of --github-output).
`list` reads a .tar.gz or .zip and writes one entry per file: path, kind (by magic bytes: elf, so, pe, dll, exe, chk, ja, text, other, link), size and
sha256. A .ja (omni.ja, browser/omni.ja), .xpi or .jar is read with a reader of its own (Mozilla's optimized layout puts the central directory first,
which zipfile refuses) and every member is an entry too, at "<container>!<path inside>".
`compare` takes two lists or two archives. Exit 1 when it is red, 2 when an input cannot be read.

  RED      a file added or missing (also a member of a .ja); a file of a non-binary kind (text, other, link) whose content changed and that is not
           explained; a kind that changed from or to a non-binary one.
  REPORTED compiled files whose content changed (elf, so, pe, dll, exe, chk: the build writes them again; ja: the container), the members of a .ja
           that changed, and application.ini / platform.ini (they carry the BuildID and the source stamp of the build).

EXPLAINED. `explain` names the files of ours that changed between the series commit of the published seal and the candidate's: the paths of the
series' git diff under <folder>/src/<tree path> (the file as it lies in Firefox's tree), and, for a changed <folder>/hooks.patch, the Mozilla files
whose section of the patch differs between the two commits. A package file is explained when it is one of those, by this rule (the whole of it):
  1. juggler/<rest>  ->  modules/juggler/<rest>   (juggler/moz.build serves it from resource://gre/modules/juggler/; loose on Linux, inside omni.ja on
     Windows: the "<container>!" prefix is dropped before the comparison)
  2. any other source that is not C, C++, Rust, build or script code  ->  the package files with the same basename (jar.mn and moz.build flatten and move
     files, so the basename is what is stable: StealthPingsender.sys.mjs, firefox.js, ...)
A changed source that maps to nothing is no reason: a package file that changed and that no source maps to is red. A hooks.patch is named by its files,
not by its hunks: a section that changed explains its whole file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import struct
import subprocess
import sys
import tarfile
import zipfile
import zlib

JA_EXTS = (".ja", ".xpi", ".jar")
BINARY_KINDS = {"elf", "so", "pe", "dll", "exe", "chk", "ja"}
BUILD_IDENTITY = {"application.ini", "platform.ini"}
# What a source of ours ships as, by rule 2: everything but code that is compiled and files that only describe the build.
NOT_SHIPPED_AS_TEXT = (".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".rs", ".mm", ".m", ".build", ".mozbuild", ".py", ".patch", ".md", ".conf",
                       ".yaml", ".yml", ".toml", ".sh", ".ini", ".in", ".idl", ".webidl", ".ipdl", ".ipdlh", ".gyp", ".gn", ".cmake")
NOT_SHIPPED_NAMES = {"jar.mn", "moz.build", "hooks.patch", "CMakeLists.txt", "Cargo.toml", "Cargo.lock", "BUILD.gn"}


class Unreadable(Exception):
    """An input that cannot be listed: never a pass."""


# ---------------------------------------------------------------- the reader of a .ja

def read_jar(data: bytes) -> list:
    """[(name, bytes)] of every member of a zip, ordinary or Mozilla's optimized layout (central directory first, offsets from the start of the file)."""
    end = data.rfind(b"PK\x05\x06", max(0, len(data) - 0xFFFF - 22))
    if end < 0 or end + 22 > len(data):
        raise Unreadable("no end of central directory record")
    _sig, _d1, _d2, _n1, total, cd_size, cd_off, _clen = struct.unpack("<4s4H2LH", data[end:end + 22])
    pos, base = cd_off, 0
    if data[pos:pos + 4] != b"PK\x01\x02":  # an ordinary zip behind a prefix: the directory ends where the record starts
        pos = end - cd_size
        base = pos - cd_off
        if pos < 0 or data[pos:pos + 4] != b"PK\x01\x02":
            raise Unreadable("no central directory where the end record says")
    members = []
    for _ in range(total):
        if data[pos:pos + 4] != b"PK\x01\x02":
            raise Unreadable("a central directory entry is not where the one before ends")
        (_s, _vm, _vn, _fl, method, _t, _d, _crc, csize, _usize, nlen, elen, clen, _dk, _ia, _ea, loff) = struct.unpack("<4s6H3L5H2L", data[pos:pos + 46])
        name = data[pos + 46:pos + 46 + nlen].decode("utf-8", "replace")
        pos += 46 + nlen + elen + clen
        if name.endswith("/"):
            continue
        lpos = loff + base
        if data[lpos:lpos + 4] != b"PK\x03\x04":
            raise Unreadable("%s: no local header at its offset" % name)
        lnlen, lelen = struct.unpack("<2H", data[lpos + 26:lpos + 30])
        start = lpos + 30 + lnlen + lelen
        raw = data[start:start + csize]
        if method == 0:
            members.append((name, raw))
        elif method == 8:
            members.append((name, zlib.decompress(raw, -15)))
        else:
            raise Unreadable("%s: compression method %d" % (name, method))
    return members


# ---------------------------------------------------------------- list

def kind_of(path: str, head: bytes) -> str:
    low = path.lower()
    base = posixpath.basename(low)
    if low.endswith(JA_EXTS):
        return "ja"
    if head[:4] == b"\x7fELF":
        return "so" if ".so" in base else "elf"
    if head[:2] == b"MZ":
        return "dll" if low.endswith(".dll") else "exe" if low.endswith(".exe") else "pe"
    if low.endswith(".chk"):
        return "chk"  # NSS's signature of a library: written again with the library
    return "other" if b"\0" in head[:8000] else "text"


def _entry(path: str, data: bytes) -> dict:
    return {"path": path, "kind": kind_of(path, data[:8192]), "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _files(archive: str):
    """(path, bytes or None for a link, link target) of every file of the archive, whole in memory one at a time."""
    if archive.endswith((".tar.gz", ".tgz", ".tar")):
        with tarfile.open(archive, "r:*") as tf:
            for m in tf:
                name = m.name[2:] if m.name.startswith("./") else m.name
                if m.isfile():
                    yield name, tf.extractfile(m).read(), None
                elif m.issym() or m.islnk():
                    yield name, None, m.linkname
    elif archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            for i in zf.infolist():
                if not i.is_dir():
                    yield i.filename, zf.read(i), None
    else:
        raise Unreadable("%s: neither .tar.gz nor .zip" % archive)


def list_archive(archive: str) -> dict:
    entries = []
    for name, data, target in _files(archive):
        if data is None:
            entries.append({"path": name, "kind": "link", "size": 0, "sha256": hashlib.sha256(target.encode()).hexdigest()})
            continue
        entry = _entry(name, data)
        entries.append(entry)
        if entry["kind"] == "ja":
            try:
                members = read_jar(data)
            except (Unreadable, struct.error, zlib.error) as exc:
                raise Unreadable("%s!: cannot read it as a zip: %s" % (name, exc))
            entries += [_entry("%s!%s" % (name, inner), blob) for inner, blob in members]
    entries.sort(key=lambda e: e["path"])
    return {"archive": os.path.basename(archive), "count": len(entries), "entries": entries}


# ---------------------------------------------------------------- the published release

def seal_check(directory: str) -> dict:
    with open(os.path.join(directory, "seal.json"), encoding="utf-8") as f:
        seal = json.load(f)
    with open(os.path.join(directory, "checksums.txt"), encoding="utf-8") as f:
        sums = {line.split(None, 1)[1].strip().lstrip("*"): line.split()[0] for line in f if line.strip()}
    problems = []
    for name, want in sorted(seal["assets"].items()):
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            problems.append("%s: named by the seal, not downloaded" % name)
            continue
        h, size = hashlib.sha256(), 0
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
                size += len(chunk)
        if h.hexdigest() != want["sha256"]:
            problems.append("%s: sha256 %s, the seal says %s" % (name, h.hexdigest(), want["sha256"]))
        if size != want["size"]:
            problems.append("%s: %d bytes, the seal says %d" % (name, size, want["size"]))
        if sums.get(name) != want["sha256"]:
            problems.append("%s: checksums.txt says %s, the seal says %s" % (name, sums.get(name), want["sha256"]))
    return {"tag": seal["tag"], "series_commit": seal["series_commit"], "source_commit": seal["source_commit"], "assets": sorted(seal["assets"]), "problems": problems}


# ---------------------------------------------------------------- explain

def _sections(patch: str) -> dict:
    """{file: the section of the patch for it, without the index line}."""
    out, name, lines = {}, None, []
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            if name:
                out[name] = "\n".join(lines)
            name, lines = line.split(" b/", 1)[1], []
        elif not line.startswith("index "):
            lines.append(line)
    if name:
        out[name] = "\n".join(lines)
    return out


def _git(series: str, *args: str) -> str:
    done = subprocess.run(["git", "-C", series, *args], capture_output=True, text=True, encoding="utf-8", check=False)
    return done.stdout if done.returncode == 0 else ""


def explain(series: str, old: str, new: str) -> dict:
    names = _git(series, "diff", "--name-only", "--no-renames", old, new).splitlines()
    if not names and _git(series, "rev-parse", "--verify", old + "^{commit}") == "":
        raise Unreadable("%s is not a commit of %s" % (old, series))
    sources = set()
    for path in names:
        if posixpath.basename(path) == "hooks.patch":
            before, after = _sections(_git(series, "show", "%s:%s" % (old, path))), _sections(_git(series, "show", "%s:%s" % (new, path)))
            sources |= {f for f in set(before) | set(after) if before.get(f) != after.get(f)}
        elif "/src/" in path:
            sources.add(path.split("/src/", 1)[1])
    return {"from": old, "to": new, "changed_files_of_the_series": len(names), "sources": sorted(sources)}


def _is_explained(path: str, sources) -> bool:
    inside = path.rsplit("!", 1)[-1]
    base = posixpath.basename(inside)
    for src in sources:
        if src.startswith("juggler/") and inside == "modules/" + src:
            return True
        if posixpath.basename(src) == base and base not in NOT_SHIPPED_NAMES and not src.lower().endswith(NOT_SHIPPED_AS_TEXT):
            return True
    return False


# ---------------------------------------------------------------- compare

def compare(published: dict, candidate: dict, sources=()) -> dict:
    pub = {e["path"]: e for e in published["entries"]}
    cand = {e["path"]: e for e in candidate["entries"]}
    out = {k: [] for k in ("added", "missing", "changed_binary", "changed_ja_entry", "changed_build_identity", "changed_non_binary")}
    same = 0
    for path in sorted(set(pub) | set(cand)):
        a, b = pub.get(path), cand.get(path)
        if a is None:
            out["added"].append({"path": path, "kind": b["kind"], "explained": _is_explained(path, sources)})
        elif b is None:
            out["missing"].append({"path": path, "kind": a["kind"], "explained": _is_explained(path, sources)})
        elif a["sha256"] == b["sha256"] and a["kind"] == b["kind"]:
            same += 1
        else:
            row = {"path": path, "kind": b["kind"], "was": a["kind"], "size": [a["size"], b["size"]], "explained": _is_explained(path, sources)}
            if "!" in path:
                out["changed_ja_entry"].append(row)
            elif a["kind"] in BINARY_KINDS and b["kind"] in BINARY_KINDS:
                out["changed_binary"].append(row)
            elif path in BUILD_IDENTITY:
                out["changed_build_identity"].append(row)
            else:
                out["changed_non_binary"].append(row)
    red = {"added": out["added"], "missing": out["missing"], "changed_non_binary_unexplained": [r for r in out["changed_non_binary"] if not r["explained"]]}
    report = {"published": published.get("archive"), "candidate": candidate.get("archive"), "unchanged": same, "sources_named": len(sources)}
    report.update(out)
    report["counts"] = {k: len(v) for k, v in out.items()}
    report["counts"]["unchanged"] = same
    report["red"] = {k: len(v) for k, v in red.items() if v}
    report["verdict"] = "red" if report["red"] else "green"
    return report


def summary(report: dict, limit: int = 40) -> str:
    lines = ["package A/B: %s -> %s: %s" % (report["published"], report["candidate"], report["verdict"].upper())]
    lines.append("  " + ", ".join("%s %d" % (k.replace("_", " "), n) for k, n in report["counts"].items()) + "; %d sources named" % report["sources_named"])
    for key in ("added", "missing", "changed_non_binary", "changed_build_identity"):
        for row in report[key][:limit]:
            if key in ("added", "missing"):
                mark = "  <-- RED"
            elif key == "changed_non_binary":
                mark = "  (explained)" if row["explained"] else "  <-- RED"
            else:
                mark = "  (reported)"
            lines.append("  %-22s %s [%s]%s" % (key.replace("_", " "), row["path"], row["kind"], mark))
        if len(report[key]) > limit:
            lines.append("  %s: %d more in the report" % (key, len(report[key]) - limit))
    lines.append("  changed binaries (reported): %d; changed members of a .ja (reported): %d" % (report["counts"]["changed_binary"], report["counts"]["changed_ja_entry"]))
    return "\n".join(lines)


def _load(path: str) -> dict:
    if path.endswith(".json"):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return list_archive(path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("seal-check")
    p.add_argument("directory")
    p.add_argument("--github-output")
    p = sub.add_parser("list")
    p.add_argument("archive")
    p.add_argument("--out")
    p = sub.add_parser("explain")
    p.add_argument("--series", required=True)
    p.add_argument("--from", dest="old", required=True)
    p.add_argument("--to", required=True)
    p.add_argument("--out")
    p = sub.add_parser("compare")
    p.add_argument("published")
    p.add_argument("candidate")
    p.add_argument("--explained")
    p.add_argument("--report")
    p.add_argument("--summary")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "seal-check":
            result = seal_check(a.directory)
            for problem in result["problems"]:
                print("ab_package: " + problem, file=sys.stderr)
            print("%s: series %s, source %s, %d assets, %d problems" % (result["tag"], result["series_commit"], result["source_commit"], len(result["assets"]), len(result["problems"])))
            if a.github_output and not result["problems"]:
                with open(a.github_output, "a", encoding="utf-8", newline="\n") as f:
                    f.write("series_commit=%s\n" % result["series_commit"])
            return 1 if result["problems"] else 0
        if a.cmd == "list":
            result = list_archive(a.archive)
            text = json.dumps(result, indent=0)
            print("%s: %d entries" % (result["archive"], result["count"]))
        elif a.cmd == "explain":
            result = explain(a.series, a.old, a.to)
            text = json.dumps(result, indent=1)
            print("%d files of the series changed, %d tree paths named" % (result["changed_files_of_the_series"], len(result["sources"])))
        else:
            sources = []
            if a.explained:
                with open(a.explained, encoding="utf-8") as f:
                    sources = json.load(f)["sources"]
            result = compare(_load(a.published), _load(a.candidate), sources)
            text = json.dumps(result, indent=1)
            print(summary(result))
            if a.summary:
                with open(a.summary, "w", encoding="utf-8", newline="\n") as f:
                    f.write(summary(result, 200) + "\n")
    except (Unreadable, OSError, ValueError, KeyError, tarfile.TarError, zipfile.BadZipFile) as exc:
        print("ab_package: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return 2
    target = getattr(a, "out", None) or getattr(a, "report", None)
    if target:
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
    return 1 if a.cmd == "compare" and result["verdict"] == "red" else 0


if __name__ == "__main__":
    sys.exit(main())
