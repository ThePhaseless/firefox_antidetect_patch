"""The crash symbols of a release are kept: published beside its archives, named by the build they describe, never part of checksums.txt or the seal.

    python3 scripts/ci/release_symbols.py ...   # through `scripts/ci`:
    python3 scripts/ci symbols-release --leg L --package P --symbols DIR --out DIR
    python3 scripts/ci symbols-seal --dir DIR
    python3 scripts/ci symbols-guard --dir DIR... [--checksums F]

A release's build leg makes `symbols-<leg>` (release.yml: buildsymbols, then symbols-match against the archive it ships). publish.yml downloads it by name, and
here it is checked AGAIN against the archive that is about to be published, renamed `symbols-<os>-<arch>-<BuildID>.zip` (the BuildID is the package's own,
from its application.ini) and listed in `symbols.sha256`. A crash report of a published build is read with exactly those files; before this nothing of a
published build's symbols survived the 14 days of an artifact.

A client picks an engine archive by `firefox-*-stealth-*` (checksums.txt, the seal's NAME_RE and every `gh release download` of ours). No symbols name may
match that, and checksums.txt may not list one: `guard` is the proof, run by publish.yml after checksums.txt is made.
"""
from __future__ import annotations

import fnmatch
import hashlib
import io
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

import make_seal
import symbols_match

#: The glob of the engine's archives: checksums.txt is `sha256sum` of it, and the client resolves an engine asset by it.
ENGINE_GLOB = "firefox-*-stealth-*"
PREFIX = "symbols-"
SHA_FILE = "symbols.sha256"
BUILD_ID = re.compile(r"^\d{14}$")


class SymbolsError(Exception):
    pass


def build_id(package: Path) -> str:
    """The BuildID of a package (.zip or .tar.gz): `[App] BuildID` of its shallowest application.ini, 14 digits."""
    package = Path(package)
    try:
        index = dict(make_seal._members(package))
    except (OSError, ValueError, make_seal.zipfile.BadZipFile, make_seal.tarfile.TarError) as exc:
        raise SymbolsError("%s cannot be read as a package: %s" % (package.name, exc))
    ini_name = make_seal._shallowest(list(index), "application.ini")
    if ini_name is None:
        raise SymbolsError("%s: no application.ini inside" % package.name)
    value = make_seal._parse_ini(index[ini_name]().decode("utf-8", "replace")).get("App", {}).get("BuildID", "")
    if not BUILD_ID.match(value):
        raise SymbolsError("%s: application.ini has no 14-digit [App] BuildID (it says %r)" % (package.name, value))
    return value


def symbols_name(leg: str, build: str) -> str:
    """`symbols-<os>-<arch>-<BuildID>.zip` for a leg named `<os>-<arch>` (legs.py)."""
    if not BUILD_ID.match(build) or "-" not in leg:
        raise SymbolsError("no symbols name for leg %r and BuildID %r" % (leg, build))
    return "%s%s-%s.zip" % (PREFIX, leg, build)


def release(leg: str, package: Path, symbols_dir: Path, out: Path) -> Path:
    """Check the leg's downloaded symbols against the package that ships, and copy the one zip to out/symbols-<os>-<arch>-<BuildID>.zip. Any doubt is an error."""
    zips = sorted(Path(symbols_dir).glob("*.zip"))
    if len(zips) != 1:
        raise SymbolsError("%s: %d symbols archives in %s, exactly one is expected" % (leg, len(zips), symbols_dir))
    try:
        symbols_match.run(Path(package), zips[0])
    except symbols_match.MismatchError as exc:
        raise SymbolsError("%s: the symbols do not describe the package that ships: %s" % (leg, exc))
    build = build_id(package)
    named = re.match(r"^%s%s-(\d{14})\.zip$" % (PREFIX, re.escape(leg)), zips[0].name)
    if named and named.group(1) != build:
        raise SymbolsError("%s: %s is named for BuildID %s, the package that ships has %s" % (leg, zips[0].name, named.group(1), build))
    target = Path(out) / symbols_name(leg, build)
    Path(out).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(zips[0], target)
    return target


def seal(directory: Path) -> str:
    """Write symbols.sha256 in `directory`: the sha256 of every symbols-*.zip in it, and no other file. An empty directory is an error."""
    directory = Path(directory)
    zips = sorted(p for p in directory.glob(PREFIX + "*.zip") if p.is_file())
    if not zips:
        raise SymbolsError("no symbols-*.zip in %s" % directory)
    lines = ["%s  %s\n" % (_sha256(p), p.name) for p in zips]
    text = "".join(lines)
    (directory / SHA_FILE).write_text(text, encoding="utf-8", newline="\n")
    return text


def guard(names: list, checksums: str = "") -> None:
    """Refuse a symbols name that the engine's glob matches, and a checksums.txt (its text) that lists one."""
    clash = sorted(n for n in names if "symbols" in n and fnmatch.fnmatchcase(n, ENGINE_GLOB))
    if clash:
        raise SymbolsError("%s match %s: a client would take them for an engine archive" % (", ".join(clash), ENGINE_GLOB))
    listed = set()
    for line in checksums.splitlines():
        parts = line.split(None, 1)
        name = parts[1].strip().lstrip("*") if len(parts) == 2 else ""
        if name.startswith((PREFIX, SHA_FILE)):
            listed.add(name)
    listed = sorted(listed)
    if listed:
        raise SymbolsError("checksums.txt lists symbols files: %s" % ", ".join(listed))


# ---------------------------------------------------------------- where a release's symbols come from (publish.yml, also under republish.yml)

def _gh(args, binary=False):
    p = subprocess.run(["gh"] + list(args), capture_output=True, text=not binary)
    err = p.stderr.decode("utf-8", "replace") if binary else p.stderr
    return p.returncode, p.stdout, err


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def from_release(legs: list, tag: str, repo: str, dest: Path, gh=_gh):
    """The symbols a release already has as assets, verified against its symbols.sha256 and put in dest/<leg>/. None when there is no release or it has no
    symbols asset (a release published before they were kept); an error when it has some and they are not whole, or when GitHub cannot say."""
    code, out, err = gh(["release", "view", tag, "-R", repo, "--json", "assets"])
    if code != 0:
        if "release not found" in (err + out).lower():
            return None
        raise SymbolsError("could not read release %s (exit %d): %s" % (tag, code, (err or out).strip()))
    names = [a.get("name", "") for a in json.loads(out or "{}").get("assets", [])]
    if not any(n.startswith(PREFIX) or n == SHA_FILE for n in names):
        return None
    if SHA_FILE not in names:
        raise SymbolsError("release %s has symbols zips and no %s: they cannot be verified" % (tag, SHA_FILE))
    with tempfile.TemporaryDirectory() as tmp:
        code, out, err = gh(["release", "download", tag, "-R", repo, "--dir", tmp, "--pattern", PREFIX + "*.zip", "--pattern", SHA_FILE])
        if code != 0:
            raise SymbolsError("the symbols of release %s could not be downloaded (exit %d): %s" % (tag, code, (err or out).strip()))
        tmp = Path(tmp)
        if not (tmp / SHA_FILE).is_file():
            raise SymbolsError("release %s: %s was not downloaded" % (tag, SHA_FILE))
        listed = {}
        for line in (tmp / SHA_FILE).read_text(encoding="utf-8").splitlines():
            parts = line.split(None, 1)
            if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
                raise SymbolsError("release %s: %s has a line that is not `<sha256>  <name>`: %r" % (tag, SHA_FILE, line))
            listed[parts[1].strip().lstrip("*")] = parts[0]
        present = {p.name for p in tmp.glob(PREFIX + "*.zip")}
        if present != set(listed):
            raise SymbolsError("release %s: %s lists %s, the release has %s" % (tag, SHA_FILE, sorted(listed), sorted(present)))
        for name, want in sorted(listed.items()):
            got = _sha256(tmp / name)
            if got != want:
                raise SymbolsError("release %s: %s has sha256 %s, %s says %s" % (tag, name, got, SHA_FILE, want))
        used = set()
        for leg in legs:
            mine = sorted(n for n in present if re.fullmatch(r"%s%s-\d{14}\.zip" % (PREFIX, re.escape(leg)), n))
            if len(mine) != 1:
                raise SymbolsError("release %s: %d symbols zips for %s (%s), exactly one is expected" % (tag, len(mine), leg, ", ".join(mine)))
            (Path(dest) / leg).mkdir(parents=True, exist_ok=True)
            shutil.copyfile(tmp / mine[0], Path(dest) / leg / mine[0])
            used.add(mine[0])
        if present != used:
            raise SymbolsError("release %s has symbols zips for no leg of this tree: %s" % (tag, sorted(present - used)))
    return True


def from_artifacts(legs: list, tag: str, repo: str, build_run: str, dest: Path, gh=_gh):
    """symbols-<leg> of the build run, each by its name, put in dest/<leg>/. A missing or expired one is an error that says the release's symbols do not survive."""
    ids, gone = {}, []
    for leg in legs:
        code, out, err = gh(["api", "repos/%s/actions/runs/%s/artifacts?name=symbols-%s" % (repo, build_run, leg), "--jq",
                             "[.artifacts[] | select(.expired | not) | .id][0] // empty"])
        if code != 0:
            raise SymbolsError("could not list the artifacts of run %s (exit %d): %s" % (build_run, code, (err or out).strip()))
        if out.strip():
            ids[leg] = out.strip()
        else:
            gone.append("symbols-" + leg)
    if gone:
        raise SymbolsError("the crash symbols of %s do not survive: the release has no symbols assets, and run %s has no %s (expired, or the build did not keep it). "
                           "A release without its crash symbols is not published" % (tag, build_run, ", ".join(gone)))
    for leg, art in sorted(ids.items()):
        code, data, err = gh(["api", "repos/%s/actions/artifacts/%s/zip" % (repo, art)], binary=True)
        if code != 0 or not data:
            raise SymbolsError("symbols-%s (artifact %s) could not be downloaded (exit %d): %s" % (leg, art, code, err.strip()))
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if any(n.startswith(("/", "\\")) or ".." in n.split("/") for n in z.namelist()):
                raise SymbolsError("symbols-%s: an archive member leaves its folder" % leg)
            (Path(dest) / leg).mkdir(parents=True, exist_ok=True)
            z.extractall(Path(dest) / leg)
    return True


def fetch(legs: list, tag: str, repo: str, build_run: str, dest: Path, gh=_gh) -> str:
    """The symbols of every leg in dest/<leg>/, from the release's own assets when it has them (republish of a release that exists: no dependence on the
    artifact's retention), else from the build run's artifacts; neither is an error. Returns where they came from."""
    if from_release(legs, tag, repo, dest, gh):
        return "the assets of release %s" % tag
    from_artifacts(legs, tag, repo, build_run, dest, gh)
    return "the artifacts symbols-<leg> of run %s" % build_run
