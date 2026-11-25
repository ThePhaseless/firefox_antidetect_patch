"""series-02: every folder of the series states its relation to Mozilla.

    python tools/folders.py          the check alone (`engine.py check` runs it too)

Every SERIES folder without a BACKPORT.json has exactly one FOLDER.json, written by hand, in one of these shapes:

    {"relation": "product"}                                   ours for good: Mozilla would not make the change
    {"relation": "defect", "upstream": "not-filed"}           a defect of Mozilla's that nobody has reported
    {"relation": "defect", "upstream": "https://bugzilla.mozilla.org/show_bug.cgi?id=<N>"}
    ... and, for a defect only, "fixed_in": "FIREFOX_<N>_<M>[_<P>]_RELEASE", the release that ships Mozilla's fix.

No other key and no other value: the file never points outside the repository (no local path, no other URL). "backport" is not
a value: it is derived from BACKPORT.json, and a backport folder has no FOLDER.json. A `fixed_in` at or before UPSTREAM.json's
`mozilla_tag` is red (Mozilla ships the fix); `engine.py port --to <tag>` stops for the same reason before it merges (`fixed_in_stops`).
A FOLDER.json anywhere but directly in a SERIES folder is red.

Messages say where, what, fix and rule (docs/decisions/series-02-every-folder-states-its-relation-to-mozilla.md).
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILE = "FOLDER.json"
BACKPORT = "BACKPORT.json"
RULE = "docs/decisions/series-02-every-folder-states-its-relation-to-mozilla.md"
RELATIONS = ("product", "defect")
KEYS = {"relation", "upstream", "fixed_in"}
NOT_FILED = "not-filed"
BUGZILLA = re.compile(r"https://bugzilla\.mozilla\.org/show_bug\.cgi\?id=[1-9][0-9]*")
TAG = re.compile(r"FIREFOX_([0-9]+)_([0-9]+)(?:_([0-9]+))?_RELEASE")
SHAPES = ('{"relation": "product"}, {"relation": "defect", "upstream": "not-filed"} or {"relation": "defect", "upstream": '
          '"https://bugzilla.mozilla.org/show_bug.cgi?id=<N>"}, and for a defect only "fixed_in": "FIREFOX_<N>_<M>_RELEASE"')


def say(where: str, what: str, fix: str) -> str:
    """One problem as where / what / fix / rule."""
    return "%s: %s\nfix: %s\nrule: %s" % (where, what, fix, RULE)


def release_version(tag) -> tuple | None:
    """FIREFOX_159_0_RELEASE -> (159, 0, 0); FIREFOX_160_0_1_RELEASE -> (160, 0, 1); anything else None. Tags compare by version,
    never by name (FIREFOX_99_0_RELEASE is before FIREFOX_159_0_RELEASE)."""
    m = TAG.fullmatch(tag) if isinstance(tag, str) else None
    return tuple(int(p or 0) for p in m.groups()) if m else None


def series_folders(root) -> list:
    return (Path(root) / "SERIES").read_text(encoding="utf-8").split()


def mozilla_tag(root) -> str | None:
    try:
        return json.loads((Path(root) / "UPSTREAM.json").read_text(encoding="utf-8")).get("mozilla_tag")
    except (OSError, ValueError, AttributeError):
        return None


def is_backport(root, folder: str) -> bool:
    return (Path(root) / folder / BACKPORT).is_file()


def load(root, folder: str):
    """(data, None) for a FOLDER.json that is a JSON object, (None, sentence) otherwise; (None, None) when the file is not there."""
    path = Path(root) / folder / FILE
    if not path.is_file():
        return None, None
    where = "%s/%s" % (folder, FILE)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, say(where, "it is not JSON (%s)" % exc, "write one of: " + SHAPES)
    if not isinstance(data, dict):
        return None, say(where, "it is not a JSON object", "write one of: " + SHAPES)
    return data, None


def shape_problems(folder: str, data: dict, tag: str | None) -> list:
    """What is wrong with the content of one FOLDER.json (a dict); `tag` is UPSTREAM.json's mozilla_tag."""
    where = "%s/%s" % (folder, FILE)
    found = []
    extra = sorted(set(data) - KEYS)
    if extra:
        found.append(say(where, "the key(s) %s are not allowed (only relation, upstream, fixed_in)" % ", ".join(map(repr, extra)),
                         "delete them: " + SHAPES))
    relation = data.get("relation")
    if relation == "backport":
        found.append(say(where, 'relation "backport" is written by hand',
                         "backport is derived from BACKPORT.json: a backport folder has a BACKPORT.json and no %s; a folder "
                         "that is not one is a product or a defect" % FILE))
        return found
    if relation not in RELATIONS:
        found.append(say(where, "relation %r is not product or defect" % (relation,), "write one of: " + SHAPES))
        return found
    if relation == "product":
        for key in ("upstream", "fixed_in"):
            if key in data:
                found.append(say(where, 'a product has no "%s"' % key,
                                 'delete "%s": only a defect names what Mozilla did about it (or make the relation defect)' % key))
        return found
    if "upstream" not in data:
        found.append(say(where, 'a defect has no "upstream"',
                         'add "upstream": "not-filed", or the bug Mozilla has: "https://bugzilla.mozilla.org/show_bug.cgi?id=<N>"'))
    else:
        up = data["upstream"]
        if not (isinstance(up, str) and (up == NOT_FILED or BUGZILLA.fullmatch(up))):
            found.append(say(where, "upstream %r is neither not-filed nor a Mozilla bug URL" % (up,),
                             'write "not-filed" or exactly https://bugzilla.mozilla.org/show_bug.cgi?id=<N>: the file never '
                             "points outside the repository (no local path, no other URL, no text)"))
    if "fixed_in" in data:
        fixed = data["fixed_in"]
        version = release_version(fixed)
        if version is None:
            found.append(say(where, 'fixed_in %r is not a release tag' % (fixed,),
                             'write the tag that ships the fix, digits only: "FIREFOX_<N>_<M>_RELEASE" or "FIREFOX_<N>_<M>_<P>_RELEASE"'))
        elif fixed_in_stop(version, tag):
            found.append(say(where, "fixed_in %s is at or before the series' tag %s: Mozilla ships the fix" % (fixed, tag),
                             "drop the folder (its change in the source branch, then export) or rebase it onto Mozilla's fix; "
                             "then delete or move fixed_in"))
    return found


def fixed_in_stop(version: tuple, tag) -> bool:
    """Is a fixed_in (as a version) at or before the release `tag`? An unreadable tag stops nothing: UPSTREAM.json is judged elsewhere."""
    current = release_version(tag)
    return current is not None and version <= current


def fixed_in_stops(root, new_tag: str) -> list:
    """[(folder, fixed_in)] of the folders whose FOLDER.json says Mozilla ships the fix at `new_tag` or before: a port to `new_tag` has to
    look at each (`engine.py port` stops on a non-empty list, before it merges). A file that is not readable is `problems`'."""
    found = []
    for folder in series_folders(root):
        data, _ = load(root, folder)
        version = release_version((data or {}).get("fixed_in"))
        if version is not None and data.get("relation") == "defect" and fixed_in_stop(version, new_tag):
            found.append((folder, data["fixed_in"]))
    return found


def stray_files(root, listed: set) -> list:
    """Every FOLDER.json of the repository that is not directly in a SERIES folder (the files under a folder's src/ are Mozilla-tree
    files of ours, not a record of the folder, and are not looked at)."""
    root = Path(root)
    found = []
    for here, dirs, files in os.walk(root):
        rel = Path(here).relative_to(root).as_posix()
        dirs[:] = sorted(d for d in dirs if d != ".git" and not (d == "src" and rel in listed))
        if FILE in files and rel not in listed:
            found.append("." if rel == "." else rel)
    return sorted(found)


def problems(root=ROOT) -> list:
    """Every rule of series-02 that is broken now, as sentences (where / what / fix / rule)."""
    root = Path(root)
    if not (root / "SERIES").is_file():
        return []
    listed = series_folders(root)
    tag = mozilla_tag(root)
    found = []
    if release_version(tag) is None:
        found.append(say("UPSTREAM.json", "mozilla_tag %r is not a release tag, so no fixed_in can be judged" % (tag,),
                         "set mozilla_tag to the stable release the series is on (FIREFOX_<N>_<M>_RELEASE)"))
    for folder in listed:
        data, bad = load(root, folder)
        where = "%s/%s" % (folder, FILE)
        if bad:
            found.append(bad)
        elif is_backport(root, folder):
            if data is not None:
                found.append(say(where, "this folder has a %s: it is a backport, and its relation is derived from that file" % BACKPORT,
                                 "delete %s" % FILE))
        elif data is None:
            found.append(say(where, "the folder does not state its relation to Mozilla",
                             "write it by hand, once: " + SHAPES))
        else:
            found += shape_problems(folder, data, tag)
    for stray in stray_files(root, set(listed)):
        found.append(say("%s/%s" % (stray, FILE) if stray != "." else FILE,
                         "a %s outside a folder of SERIES" % FILE,
                         "delete it: the relation is stated by the folder that makes the change, directly in it"))
    return found


def main(argv=None) -> int:
    found = problems(Path(argv[0]) if argv else ROOT)
    for p in found:
        print("FAIL", p)
    if not found:
        print("ok: every folder states its relation to Mozilla")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
