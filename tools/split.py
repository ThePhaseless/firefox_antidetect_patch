"""One Mozilla file, several folders: each folder holds exactly the lines its marker names (rule series-01).

Today export gives a modified Mozilla file whole to ONE folder, the folder of its inventory feature. Every line a hook adds carries
`STEALTH-HOOK(<folder>)`; this module gives every changed line of a file to the folder its marker names and builds one hooks.patch per
folder, in SERIES order, so that applying them one after the other on the tag gives the head byte for byte. Nothing here is wired into
tools/engine.py: export calls `make_plan`, `assign` and `folder_patches`.

    from split import assign, folder_patches, make_plan

assign(path, diff_blocks, folders_known, backport_folders)   pure: one file's change blocks -> an Assignment
    `diff_blocks` come from parse_blocks(git diff -U0 --no-renames <base> <head> -- <path>), the default algorithm export uses, one Block
    per change (the removed lines, then the added lines). The owner of every line:
      - an added line with a marker: the folder the marker names (marker_split of tools/hook_contract.py);
      - an added line without one (a blank line, a body line of a multi-line form whose marker sits on another line): the folder of the
        marked lines next to it in the same block of added lines: the nearest marked line above and the nearest below, if they name the
        same folder, or only one side exists. Two different folders: red, "a line between two folders' hooks". A block with no marker:
        red, "untagged change";
      - the removed lines of a block: the folder of the block's added lines (two folders: red, "a rewrite owned by two folders");
      - a block that only removes: the one folder the file's markers name; else the folder the marked lines of its hunk (blocks at most
        six lines apart in the tag, what a -U3 diff joins) agree on; else `file_folder` when the file has no marker at all (a Mozilla
        file we delete: the folder of its inventory feature); else red, "a removal owned by no folder".
    A marker naming a folder that is not in `folders_known` is red. `backport_folders` (the folders that have a BACKPORT.json) changes
    nothing: a backport folder may own lines of an ordinary Mozilla file by marker (the series has two, in gfx/wgpu_bindings/src/lib.rs
    and gfx/tests/gtest/moz.build), so a marker naming one is as good as any; the argument is the caller's list of the folders whose
    vendored files it gives whole, kept so the signature says which folders are not split by marker.
    Every red is a failure.fail(where, what, fix, rule) with where `<path>:<line>` (the line of the head; of the line after the cut for a
    block that only removes), and the file is not split until it is fixed.

Files whose inventory category is `backport` are NOT split. The vendored files of a backport folder (and upstream code of a Mozilla
commit) carry no markers: the caller gives them whole to their folder (a plan value that is the folder name), and assign is not called
for them (make_plan does that). The same holds for a file git calls binary: it has no lines to give.

folder_patches(source, base, head, plan, series_order)   {folder: hooks.patch bytes} (a dict with `.problems`: the reds, and the files
    it left out because of them). `plan` is {path: Assignment, or the folder name for a whole file}.
    Per file, S0 is the file at the tag; for every folder that owns lines of it, in SERIES order, S_f is S_prev with the lines of f
    applied (its added lines in, its removed lines out) and the folder's diff of the file is diff(S_prev, S_f). The lines are placed by the
    coordinates of the one diff of the file, so two folders that insert at the same place get their lines in the order of the head.
    The patch has the form of export's: `git diff --binary --full-index --no-renames` of two trees, a/<path> b/<path> headers and
    index lines; the trees are built in a scratch repository that borrows the objects of `source` (tools/backport_replay.py), with
    update-index --cacheinfo and write-tree, no working tree (no line-ending conversion) and nothing written to `source`.
    Last check: the last S of every file is the head blob byte for byte; otherwise red.
"""
from __future__ import annotations

import difflib
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backport_replay import Scratch  # noqa: E402
from failure import fail  # noqa: E402
from hook_contract import marker_split  # noqa: E402

RULE = "series-01-export-is-the-only-writer"
HUNK_GAP = 6          # blocks this close in the tag are one hunk of a -U3 diff
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


# ---------------------------------------------------------------------------------------------------- blocks

@dataclass
class Block:
    """One change of `git diff -U0`: `old` lines of the tag from index `old_at` (0-based; for a pure insertion the index the lines go
    before) replaced by `new` lines of the head from index `new_at`. Lines are the text without their line ending."""
    old_at: int
    old: list
    new_at: int
    new: list


def parse_blocks(diff_text: str) -> list:
    """The Blocks of a `git diff -U0` of one file (the text of the diff, from its first line on)."""
    blocks = []
    for line in diff_text.split("\n"):
        m = HUNK.match(line)
        if m:
            a, b, c, d = int(m.group(1)), m.group(2), int(m.group(3)), m.group(4)
            b = 1 if b is None else int(b)
            d = 1 if d is None else int(d)
            blocks.append(Block(a - 1 if b else a, [], c - 1 if d else c, []))
        elif blocks and line[:1] == "-" and not line.startswith("---"):
            blocks[-1].old.append(line[1:].rstrip("\r"))
        elif blocks and line[:1] == "+" and not line.startswith("+++"):
            blocks[-1].new.append(line[1:].rstrip("\r"))
    return blocks


def diff_blocks(source: Path, base: str, head: str, path: str) -> list:
    """parse_blocks of `git diff -U0 --no-renames <base> <head> -- <path>` in the source repository (read only)."""
    out = subprocess.run(["git", "-C", str(source), "diff", "-U0", "--no-renames", "--no-color", base, head, "--", path],
                         check=True, capture_output=True).stdout
    return parse_blocks(out.decode("utf-8", errors="replace"))


# ---------------------------------------------------------------------------------------------------- assign

@dataclass
class Assignment:
    """The owner of every changed line of one file: `added[i][j]` the folder of line j of block i's added lines, `removed[i]` the folder
    of block i's removed lines (None when the block removes nothing or is red); `problems` the reds; `folders` the owners."""
    path: str
    blocks: list
    added: list
    removed: list
    problems: list = field(default_factory=list)

    @property
    def folders(self) -> list:
        found = {f for row in self.added for f in row if f} | {f for f in self.removed if f}
        return sorted(found)


def _where(path: str, block: Block, offset: int = 0) -> str:
    return "%s:%d" % (path, block.new_at + 1 + offset)


def _near(folders_known, name: str) -> str:
    close = difflib.get_close_matches(name, sorted(folders_known), n=1)
    return "did you mean %s? " % close[0] if close else ""


def assign(path: str, diff_blocks, folders_known, backport_folders, file_folder=None) -> Assignment:
    """The folder of every changed line of `path` (see the module text). `diff_blocks` is a list of Block. `file_folder` is only the
    last resort for a removal in a file with no marker at all. Pure: no git, no file."""
    known = set(folders_known)
    blocks = list(diff_blocks)
    problems = []
    marks = []          # per block, per added line: the folder its marker names or None
    for block in blocks:
        row = []
        for j, line in enumerate(block.new):
            _code, folder, _extra = marker_split(line)
            if folder is not None and folder not in known:
                problems.append(fail(
                    _where(path, block, j), "the marker names %s, which is not a folder of the series" % folder,
                    "write the marker with a folder of SERIES (%sthe folder is the path under the group, as in `STEALTH-HOOK(network/doh)`)"
                    % _near(known, folder), RULE))
            row.append(folder)
        marks.append(row)

    file_marks = {f for row in marks for f in row if f}
    added = []
    for block, row in zip(blocks, marks):
        owners = list(row)
        if block.new and any(row):
            above, last = [], None
            for folder in row:
                last = folder or last
                above.append(last)
            below, last = [], None
            for folder in reversed(row):
                last = folder or last
                below.append(last)
            below.reverse()
            for j in range(len(row)):
                if row[j]:
                    continue
                if above[j] and below[j] and above[j] != below[j]:
                    problems.append(fail(
                        _where(path, block, j), "a line between two folders' hooks: it follows a hook of %s and precedes one of %s"
                        % (above[j], below[j]),
                        "put the marker of the folder that owns the line on it, or move it next to that folder's hook "
                        "(a blank or body line of a form goes with the form's marker, not between two folders' hooks)", RULE))
                else:
                    owners[j] = above[j] or below[j]
        elif block.new:
            problems.append(fail(
                _where(path, block), "untagged change: %d added line%s, none with a marker" % (len(block.new), "" if len(block.new) == 1 else "s"),
                "end the hook line with its marker, `STEALTH-HOOK(<folder>)` in a comment of the file's type, naming the folder that owns "
                "the change", RULE))
        added.append(owners)

    removed = []
    for bi, (block, row) in enumerate(zip(blocks, marks)):
        if not block.old:
            removed.append(None)
            continue
        if block.new:
            named = {f for f in row if f}
            if len(named) > 1:
                problems.append(fail(
                    _where(path, block), "a rewrite owned by two folders: lines %d-%d of the tag are replaced by lines of %s"
                    % (block.old_at + 1, block.old_at + len(block.old), " and ".join(sorted(named))),
                    "write the rewrite as one folder's form: the rewriting line carries one marker, and the other folder's lines are a hook "
                    "of its own on separate lines that do not replace a Mozilla line", RULE))
            removed.append(next(iter(named)) if len(named) == 1 else None)
            continue
        owner = _removal_owner(bi, blocks, marks, file_marks, file_folder)
        if owner is None:
            problems.append(fail(
                _where(path, block), "a removal owned by no folder: lines %d-%d of the tag are removed with no added line to carry a marker, "
                "and the file's hooks name %s" % (block.old_at + 1, block.old_at + len(block.old), ", ".join(sorted(file_marks)) or "none"),
                "make the removal part of a rewrite: replace the line with a hook line carrying STEALTH-HOOK(<folder>) of the folder that "
                "owns the removal, so the removed line has an owner", RULE))
        removed.append(owner)
    return Assignment(path, blocks, added, removed, problems)


def _removal_owner(bi: int, blocks: list, marks: list, file_marks: set, file_folder):
    """The folder of a block that only removes, or None."""
    if len(file_marks) == 1:
        return next(iter(file_marks))
    if not file_marks:
        return file_folder
    lo = hi = bi
    while lo > 0 and blocks[lo].old_at - (blocks[lo - 1].old_at + len(blocks[lo - 1].old)) <= HUNK_GAP:
        lo -= 1
    while hi + 1 < len(blocks) and blocks[hi + 1].old_at - (blocks[hi].old_at + len(blocks[hi].old)) <= HUNK_GAP:
        hi += 1
    named = {f for row in marks[lo:hi + 1] for f in row if f}
    return next(iter(named)) if len(named) == 1 else None


# ---------------------------------------------------------------------------------------------------- the plan

def make_plan(source: Path, base: str, head: str, files: dict, folders_known, backport_folders) -> dict:
    """{path: Assignment or folder name} for `files`, {path: (folder of its inventory feature, category)}: a file of category backport,
    or one git calls binary, goes whole to that folder; every other one is split by assign."""
    plan = {}
    binary = _binary_paths(source, base, head, [p for p, (_f, cat) in files.items() if cat != "backport"])
    for path, (folder, category) in sorted(files.items()):
        if category == "backport" or path in binary:
            plan[path] = folder
        else:
            plan[path] = assign(path, diff_blocks(source, base, head, path), folders_known, backport_folders, file_folder=folder)
    return plan


def _binary_paths(source: Path, base: str, head: str, paths: list) -> set:
    if not paths:
        return set()
    out = subprocess.run(["git", "-C", str(source), "diff", "--numstat", "-z", "--no-renames", base, head, "--", *paths],
                         check=True, capture_output=True).stdout
    return {rec.split(b"\t", 2)[2].decode() for rec in out.split(b"\0") if rec.startswith(b"-\t-\t")}


# ---------------------------------------------------------------------------------------------------- patches

class Patches(dict):
    """{folder: hooks.patch bytes}, plus `problems` (reds) and `skipped` (the files a red kept out of the patches)."""

    def __init__(self):
        super().__init__()
        self.problems = []
        self.skipped = []


def _lines(data: bytes) -> list:
    """The lines of a blob, each with its line ending: cut at line feeds only, as git counts them."""
    return re.findall(rb"[^\n]*\n|[^\n]+", data)


def _state(base_lines: list, head_lines: list, assignment: Assignment, order: dict, upto: int) -> bytes:
    """The file with the lines of every folder up to series position `upto` applied: the tag's lines, a block's removed lines gone and its
    added lines in when its owner is at or before `upto`."""
    out, pos = [], 0
    for bi, block in enumerate(assignment.blocks):
        out += base_lines[pos:block.old_at]
        old_owner = assignment.removed[bi]
        if block.old and (old_owner is None or order[old_owner] > upto):
            out += base_lines[block.old_at:block.old_at + len(block.old)]
        for j, owner in enumerate(assignment.added[bi]):
            if owner is not None and order[owner] <= upto:
                out.append(head_lines[block.new_at + j])
        pos = block.old_at + len(block.old)
    out += base_lines[pos:]
    return b"".join(out)


def folder_patches(source: Path, base: str, head: str, plan: dict, series_order: list) -> Patches:
    """{folder: hooks.patch bytes} for `plan` (the module text says how). A file with a red assignment is left out and its reds are in
    `.problems`; so is a file whose last state is not the head blob."""
    order = {f: i for i, f in enumerate(series_order)}
    result = Patches()
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Scratch(Path(source), Path(tmp))
        steps = {}          # folder -> {path: (mode, oid) after the folder}
        current = {}        # path -> (mode, oid) now (None: the file is absent)
        for path, owned in sorted(plan.items()):
            if isinstance(owned, Assignment) and owned.problems:
                result.problems += owned.problems
                result.skipped.append(path)
                continue
            start, end = _entry(scratch, base, path), _entry(scratch, head, path)
            names = [owned] if isinstance(owned, str) else owned.folders
            outside = [f for f in names if f not in order]
            if outside:
                result.problems.append(fail(
                    path, "the folder %s owns lines of the file and is not in the series order" % ", ".join(outside),
                    "add the folder to SERIES (the export writes SERIES from the folders that own something)", RULE))
                result.skipped.append(path)
                continue
            if isinstance(owned, str):
                chain = [(owned, end)]
            else:
                chain = _chain(scratch, path, owned, start, end, order, result)
                if chain is None:
                    result.skipped.append(path)
                    continue
            current[path] = start
            for folder, entry in chain:
                steps.setdefault(folder, {})[path] = entry
        for folder in sorted(steps, key=lambda f: order[f]):
            paths = sorted(steps[folder])
            result[folder] = _diff(scratch, [(p, current[p]) for p in paths], [(p, steps[folder][p]) for p in paths], paths)
            current.update(steps[folder])
    return result


def _entry(scratch: Scratch, rev: str, path: str):
    """(mode, oid) of `path` at `rev`, or None when the revision does not have it."""
    out = scratch.run("ls-tree", "-z", rev, "--", path, source=True).stdout.split(b"\0")[0].decode()
    if not out:
        return None
    meta, _name = out.split("	", 1)
    mode, _kind, oid = meta.split()
    return mode, oid


def _chain(scratch: Scratch, path: str, owned: Assignment, start, end, order: dict, result: Patches):
    """[(folder, (mode, oid) after it)] for a split file, in series order; None (and a red) when the last state is not the head."""
    folders = sorted(owned.folders, key=lambda f: order[f])
    if not folders:
        return []
    base_lines = _lines(scratch.blob(start[1])) if start else []
    head_lines = _lines(scratch.blob(end[1])) if end else []
    chain, last = [], b""
    for folder in folders:
        last = _state(base_lines, head_lines, owned, order, order[folder])
        chain.append((folder, end if folder == folders[-1] else (start[0], scratch.hash(last))))
    if last != (scratch.blob(end[1]) if end else b""):
        taken = _lines(last)
        left = _untaken(taken, head_lines)
        result.problems.append(fail(
            path, "the folders' lines do not add up to the head: %d line%s of the head taken by no folder (head lines %s)"
            % (len(left), "" if len(left) == 1 else "s", ", ".join(map(str, left)) or "none found by content"),
            "give every changed line a marker naming its folder, then export again", RULE))
        return None
    return chain


def _untaken(taken: list, head_lines: list) -> list:
    """The 1-based numbers of the head lines that the folders' last state does not have (by content, in order)."""
    found = []
    for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(None, taken, head_lines, autojunk=False).get_opcodes():
        if tag in ("replace", "insert"):
            found += range(j1 + 1, j2 + 1)
    return found


def _diff(scratch: Scratch, old: list, new: list, paths: list) -> bytes:
    """`git diff --binary --full-index --no-renames` of two trees holding `paths` as in `old` and as in `new` ([(path, (mode, oid) or None)])."""
    trees = []
    for rows in (old, new):
        scratch.index.unlink(missing_ok=True)
        info = [("%s %s	%s" % (entry[0], entry[1], path)).encode() for path, entry in rows if entry]
        if info:
            scratch.run("update-index", "--add", "-z", "--index-info", input=b"\0".join(info) + b"\0")
        trees.append(scratch.out("write-tree"))
    return scratch.run("diff", "--binary", "--full-index", "--no-renames", trees[0], trees[1], "--", *paths).stdout
