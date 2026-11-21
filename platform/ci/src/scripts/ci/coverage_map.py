#!/usr/bin/env python3
"""Which hook of the series does any suite execute? The map of diagnostics.yml, from per-suite coverage exports.

    python3 scripts/ci/coverage_map.py map --profiles DIR --source-root DIR --series-root DIR --out DIR
                [--run-id N] [--source-commit S] [--series-commit S] [--toolchain T] [--strip-prefix P]
                [--compiled FILE] [--expect SUITE ...]
    python3 scripts/ci/coverage_map.py legs-check --required ci/required-suites.json --workflow .github/workflows/diagnostics.yml
    python3 scripts/ci/coverage_map.py suites --workflow .github/workflows/diagnostics.yml     (the suites a run expects a profile of, one line)
    python3 scripts/ci/coverage_map.py suites --workflow .github/workflows/diagnostics.yml      (the suites a run expects a profile of)

Inputs of `map`
  --profiles     per-suite lcov exports (`<suite>.info`, anywhere under DIR; scripts/ci/gcov_export.py makes them), each with an
                 optional `<suite>.meta.json` beside it (the suite's result: rc, tests, failures);
  --source-root  the sources at the built commit (the build job keeps the files the map reads: its `notes/sources`);
  --series-root  the series: `*/*/HOOKS.json` (every hook: file, function, kind, form, line = the exact text of the hook line, no number)
                 and `*/*/MANIFEST.json` (the Mozilla files a folder modifies, the files of its own it adds);
  --compiled     the files the build's notes name (`notes/compiled.json`), when the exports alone cannot say a file was compiled.

What a hook's line number is: the text of the hook line is searched in its file after the line of its `function` (the signature line the
hook sits in), and after the previous hook of that function, so a text that repeats (`  }`, `return;`) is told apart by where it is. A text
that cannot be found in its file is a tool failure, not a result.

Status of a hook
  yes            a suite counted the line (the suites are named);
  no             the line carries a counter and no suite counted it;
  not-compiled   the file is not in the Linux build, or the line is in a #if region whose code no suite has a counter for;
  no-counter     a comment, a brace or a declaration: no counter on the line and none on a hook line beside it;
  not-instrumented  the file is not C or C++ (Rust, JavaScript, build files, IDL, Markdown): this build measures C and C++ only;
  removed        the hook deletes lines (its text is empty, the lines it removed are in HOOKS.json's `removed`): nothing to execute.
A line without a counter takes the status of the hook lines that touch it (a run of hook lines within two lines of each other): the
closing brace of an `if` whose condition was counted is executed when the condition is.

Output (--out): hooks.csv, functions.csv, uncovered.txt (hooks with status no), not_compiled.txt (with the reason), not_instrumented.txt,
meta.json, index.csv (one row for the study repository's INDEX).

Exit 0, or 1 only when the tool broke: no profile, no line mapped in any of them, a hook text that is not in its file.

Its cases: scripts/ci/test_coverage_map.py.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

C_EXT = (".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx")
GAP = 2  # hook lines this close are one run (a brace and the condition that opened it)
REASON_FILE = "file not compiled on Linux"
REASON_IFDEF = "line in an #ifdef region not compiled"


class MapError(Exception):
    """The tool broke: its inputs are not what it reads."""


# ----------------------------------------------------------------------------------------------------------------------- lcov

def parse_lcov(text: str, strip_prefix: str = "") -> dict:
    """{file: {"lines": {n: count}, "functions": {name: (line, count)}}} from an lcov .info (SF, FN, FNDA, DA)."""
    files: dict = {}
    current = None
    names: dict = {}
    prefix = strip_prefix.rstrip("/") + "/" if strip_prefix else ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("SF:"):
            path = line[3:].replace("\\", "/")
            if prefix and path.startswith(prefix):
                path = path[len(prefix):]
            current = files.setdefault(path, {"lines": {}, "functions": {}})
            names = {}
        elif current is None:
            continue
        elif line.startswith("DA:"):
            fields = line[3:].split(",")
            try:
                n, count = int(fields[0]), int(fields[1])
            except (ValueError, IndexError):
                continue
            current["lines"][n] = current["lines"].get(n, 0) + count
        elif line.startswith("FN:"):
            start, _, name = line[3:].partition(",")
            try:
                names[name] = int(start)
            except ValueError:
                continue
            current["functions"].setdefault(name, (int(start), 0))
        elif line.startswith("FNDA:"):
            count, _, name = line[5:].partition(",")
            try:
                n = int(count)
            except ValueError:
                continue
            start = names.get(name, current["functions"].get(name, (0, 0))[0])
            old = current["functions"].get(name, (start, 0))
            current["functions"][name] = (start, old[1] + n)
        elif line == "end_of_record":
            current = None
    return files


def load_profiles(directory: Path, strip_prefix: str = "") -> dict:
    """{suite: {"files": parsed lcov, "meta": dict}} for every `<suite>.info` under `directory`."""
    suites: dict = {}
    for info in sorted(Path(directory).rglob("*.info")):
        suite = info.stem
        meta_path = info.with_name(suite + ".meta.json")
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
        except ValueError as exc:
            raise MapError("%s is not JSON: %s" % (meta_path, exc))
        data = suites.setdefault(suite, {"files": {}, "meta": meta})
        for path, rec in parse_lcov(info.read_text(encoding="utf-8", errors="replace"), strip_prefix).items():
            into = data["files"].setdefault(path, {"lines": {}, "functions": {}})
            for n, count in rec["lines"].items():
                into["lines"][n] = into["lines"].get(n, 0) + count
            for name, (start, count) in rec["functions"].items():
                old = into["functions"].get(name, (start, 0))
                into["functions"][name] = (old[0] or start, old[1] + count)
    return suites


# ---------------------------------------------------------------------------------------------------------------------- series

def load_hooks(series_root: Path) -> list:
    """Every hook of every folder's HOOKS.json, in the order of the lists, with its folder."""
    hooks = []
    for path in sorted(Path(series_root).glob("*/*/HOOKS.json")):
        folder = path.parent.relative_to(series_root).as_posix()
        for entry in json.loads(path.read_text(encoding="utf-8")):
            hooks.append(dict(entry, folder=folder, function=entry.get("function") or "", form=entry.get("form") or "",
                              kind=entry.get("kind") or ""))
    return hooks


def own_files(series_root: Path) -> list:
    """The files of our own that the folders add (MANIFEST.json), sorted."""
    found = set()
    for path in Path(series_root).glob("*/*/MANIFEST.json"):
        found |= set(json.loads(path.read_text(encoding="utf-8")).get("added") or {})
    return sorted(found)


def is_c(path: str) -> bool:
    return path.lower().endswith(C_EXT)


# -------------------------------------------------------------------------------------------------------------------- locating

def _same(a: str, b: str) -> bool:
    return a.strip() == b.strip()


def locate(lines: list, hooks: list) -> None:
    """Sets hook["lineno"] (1-based) on each hook of ONE file, given in the order of their lists. MapError when a text is not in the file."""
    exact: dict = defaultdict(list)
    loose: dict = defaultdict(list)
    for i, line in enumerate(lines):
        exact[line.rstrip("\r\n")].append(i)
        loose[line.strip()].append(i)
    cursor: dict = {}
    last_in_file = -1
    for hook in hooks:
        text, func = hook["line"].rstrip("\r\n"), hook["function"]
        cands = exact.get(text) or loose.get(text.strip()) or []
        if not cands:
            raise MapError("%s: the text of a hook of %s is not in the file: %r" % (hook["file"], hook["folder"], text.strip()[:100]))
        func_lines = [i for i, line in enumerate(lines) if _same(line, func)] if func.strip() else []
        tries = []
        if func in cursor:
            tries.append(cursor[func] + 1)
        tries += func_lines
        tries += [last_in_file + 1, 0]
        found = next((c for start in tries for c in cands if c >= start), None)
        hook["lineno"] = found + 1
        hook["located_by"] = "function" if func_lines and any(c >= f for f in func_lines for c in [found]) else "text"
        hook["ambiguous"] = len(cands) > 1 and hook["located_by"] == "text"
        cursor[func] = found
        last_in_file = found


_DIRECTIVE = re.compile(r"^\s*#\s*(if|ifdef|ifndef|elif|else|endif)\b")


def conditional_regions(lines: list) -> list:
    """(first, last) 0-based line indexes of each branch of each #if block, the directive lines left out."""
    regions, stack = [], []
    for i, line in enumerate(lines):
        m = _DIRECTIVE.match(line)
        if not m:
            continue
        word = m.group(1)
        if word in ("if", "ifdef", "ifndef"):
            stack.append(i)
        elif word in ("elif", "else") and stack:
            regions.append((stack[-1] + 1, i - 1))
            stack[-1] = i
        elif word == "endif" and stack:
            regions.append((stack.pop() + 1, i - 1))
    return regions


def _code_like(line: str) -> bool:
    s = line.strip()
    return bool(s) and not s.startswith(("//", "/*", "*", "#")) and (";" in s or "(" in s)


# --------------------------------------------------------------------------------------------------------------------- the map

def counters_of(suites: dict, path: str) -> dict:
    """{line: {suite: count}} for one file, over every suite that has a record of it."""
    by_line: dict = defaultdict(dict)
    for suite, data in suites.items():
        rec = data["files"].get(path)
        if rec:
            for n, count in rec["lines"].items():
                by_line[n][suite] = count
    return by_line


def build(profiles: dict, hooks: list, source_root: Path, own: list, compiled: set = frozenset(), expect=()) -> dict:
    """The rows of hooks.csv and functions.csv, and the counts. `profiles` is load_profiles()'s answer."""
    seen_files = {path for data in profiles.values() for path in data["files"]}
    compiled_files = set(seen_files) | set(compiled)
    by_file: dict = defaultdict(list)
    for hook in hooks:
        by_file[hook["file"]].append(hook)

    rows = []
    for path in sorted(by_file):
        group = by_file[path]
        # a hook that removes lines has no line of its own: nothing is there to execute
        for hook in [h for h in group if h["kind"] == "delete" or not h["line"].strip()]:
            hook.update(lineno=0, status="removed", reason="lines removed by the hook: nothing to execute", suites=[])
        group = [h for h in group if h["kind"] != "delete" and h["line"].strip()]
        if not group:
            continue
        if not is_c(path):
            for hook in group:
                hook.update(lineno=0, status="not-instrumented", reason="%s: this build measures C and C++" % (Path(path).suffix or "no extension"),
                            suites=[])
            continue
        source = Path(source_root) / path
        try:
            lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            raise MapError("%s: the source of the built commit is not readable: %s" % (path, exc))
        # one list per folder: each folder's HOOKS.json is in the order of its own diff
        for folder in sorted({h["folder"] for h in group}):
            locate(lines, [h for h in group if h["folder"] == folder])
        group.sort(key=lambda h: h["lineno"])
        if path not in compiled_files:
            for hook in group:
                hook.update(status="not-compiled", reason=REASON_FILE, suites=[])
            continue
        counters = counters_of(profiles, path)
        regions = conditional_regions(lines)
        for hook in group:
            own_counter = counters.get(hook["lineno"])
            hook["counter"] = own_counter is not None
            hook["suites"] = sorted(s for s, c in (own_counter or {}).items() if c > 0)
            hook["status"] = ("yes" if hook["suites"] else "no") if own_counter is not None else ""
            hook["reason"] = ""
        # a line with no counter takes the status of the run of hook lines it touches
        run: list = []
        runs: list = []
        for hook in group:
            if run and hook["lineno"] - run[-1]["lineno"] > GAP:
                runs.append(run)
                run = []
            run.append(hook)
        if run:
            runs.append(run)
        for members in runs:
            counted = [h for h in members if h["counter"]]
            suites = sorted({s for h in counted for s in h["suites"]})
            for hook in members:
                if hook["status"]:
                    continue
                if counted:
                    hook["status"] = "yes" if suites else "no"
                    hook["suites"] = suites
                    hook["reason"] = "no counter on the line: the hook lines beside it say"
                    continue
                inside = [r for r in regions if r[0] <= hook["lineno"] - 1 <= r[1]]
                region = min(inside, key=lambda r: r[1] - r[0]) if inside else None
                if region and any(_code_like(lines[i]) for i in range(region[0], region[1] + 1)) \
                        and not any((i + 1) in counters for i in range(region[0], region[1] + 1)):
                    hook["status"], hook["reason"] = "not-compiled", REASON_IFDEF
                else:
                    hook["status"] = "no-counter"
                    hook["reason"] = "a comment, a brace or a declaration: no counter on the line, none beside it"
                hook["suites"] = []
    for hook in hooks:
        hook.setdefault("lineno", 0)
    rows = sorted(hooks, key=lambda h: (h["folder"], h["file"], h["lineno"], h["line"]))

    functions = []
    for path in own:
        if not is_c(path):
            continue
        names: dict = {}
        for suite, data in profiles.items():
            rec = data["files"].get(path)
            for name, (start, count) in ((rec or {}).get("functions") or {}).items():
                known = names.setdefault(name, {"line": start, "suites": set()})
                if count > 0:
                    known["suites"].add(suite)
        for name in sorted(names, key=lambda n: (names[n]["line"], n)):
            functions.append({"file": path, "function": name, "line": names[name]["line"],
                              "executed": "yes" if names[name]["suites"] else "no", "suites": sorted(names[name]["suites"])})
    mapped = sum(len(rec["lines"]) for data in profiles.values() for rec in data["files"].values())
    statuses: dict = defaultdict(int)
    for hook in rows:
        statuses[hook["status"]] += 1
    return {"hooks": rows, "functions": functions, "mapped_lines": mapped, "statuses": dict(statuses),
            "missing_suites": sorted(set(expect) - set(profiles))}


# -------------------------------------------------------------------------------------------------------------------- writing

def write_outputs(result: dict, out: Path, meta: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)

    def table(name, header, rows):
        with open(out / name, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(header)
            w.writerows(rows)

    hooks = result["hooks"]
    table("hooks.csv", ["folder", "file", "line", "kind", "form", "function", "executed", "reason", "suites"],
          [[h["folder"], h["file"], h["lineno"] or "", h["kind"], h["form"], h["function"].strip(), h["status"], h.get("reason", ""),
            ";".join(h["suites"])] for h in hooks])
    table("functions.csv", ["file", "function", "line", "executed", "suites"],
          [[f["file"], f["function"], f["line"], f["executed"], ";".join(f["suites"])] for f in result["functions"]])

    def lines_of(status):
        return [h for h in hooks if h["status"] == status]

    def write(name, text):
        with open(out / name, "w", encoding="utf-8", newline="") as f:
            f.write(text)

    write("uncovered.txt", "".join("%s: %s:%d  %s\n" % (h["folder"], h["file"], h["lineno"], h["line"].strip()) for h in lines_of("no")))
    write("not_compiled.txt", "".join("%s: %s:%s  [%s]  %s\n" % (h["folder"], h["file"], h["lineno"] or "?", h["reason"], h["line"].strip())
                                      for h in lines_of("not-compiled")))
    write("not_instrumented.txt", "".join("%s: %s  [%s]\n" % (h["folder"], h["file"], h["reason"]) for h in lines_of("not-instrumented")))
    meta = dict(meta, counts=dict(sorted(result["statuses"].items()), hooks=len(hooks), functions=len(result["functions"]),
                                  mapped_lines=result["mapped_lines"]))
    write("meta.json", json.dumps(meta, indent=1, sort_keys=True) + "\n")
    suites = meta.get("suites") or {}
    passed = sorted(s for s, m in suites.items() if m.get("passed") is True)
    index = ["run_id", "date", "source_commit", "series_commit", "toolchain", "suites", "suites_passed", "hooks", "yes", "no",
             "not_compiled", "no_counter", "not_instrumented", "removed", "functions", "mapped_lines"]
    c = meta["counts"]
    table("index.csv", index, [[meta.get("run_id", ""), meta.get("date", ""), meta.get("source_commit", ""), meta.get("series_commit", ""),
                                meta.get("toolchain", ""), len(suites), len(passed), c["hooks"], c.get("yes", 0), c.get("no", 0),
                                c.get("not-compiled", 0), c.get("no-counter", 0), c.get("not-instrumented", 0), c.get("removed", 0), c["functions"], c["mapped_lines"]]])


def run_map(args) -> int:
    series, out = Path(args.series_root), Path(args.out)
    profiles = load_profiles(Path(args.profiles), args.strip_prefix)
    if not profiles:
        print("ERROR: no profile under %s: nothing ran, or nothing was exported" % args.profiles, file=sys.stderr)
        return 1
    compiled = set()
    if args.compiled:
        compiled = set(json.loads(Path(args.compiled).read_text(encoding="utf-8")))
    try:
        result = build(profiles, load_hooks(series), Path(args.source_root), own_files(series), compiled, args.expect or ())
    except MapError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 1
    if result["mapped_lines"] == 0:
        print("ERROR: no line of any file was mapped: the exports are empty (the counters did not reach the profiles, or the paths do not match "
              "the sources)", file=sys.stderr)
        return 1
    import datetime
    suites = {name: dict(data["meta"], lines=sum(len(r["lines"]) for r in data["files"].values())) for name, data in sorted(profiles.items())}
    meta = {"source_commit": args.source_commit, "series_commit": args.series_commit, "run_id": args.run_id, "toolchain": args.toolchain,
            "date": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"), "suites": suites,
            "suites_without_profile": result["missing_suites"], "flavour": "gcov (--enable-coverage), C and C++ only"}
    write_outputs(result, out, meta)
    c = json.loads((out / "meta.json").read_text(encoding="utf-8"))["counts"]
    print("hooks: %d | yes %d | no %d | not-compiled %d | no-counter %d | not-instrumented %d | removed %d | suites with a profile: %d | without: %s"
          % (c["hooks"], c.get("yes", 0), c.get("no", 0), c.get("not-compiled", 0), c.get("no-counter", 0), c.get("not-instrumented", 0),
             c.get("removed", 0), len(profiles), ", ".join(result["missing_suites"]) or "none"))
    return 0


# ------------------------------------------------------------------------------------------------------------------ legs-check

def linux_suites(required: list) -> list:
    return [s["id"] for s in required if "linux" in (s.get("os") or [])]


def legs_missing(required: list, workflow: dict, job: str = "wrapper-e2e") -> list:
    """The Linux suites of the wrapper's list that have no row in this workflow's matrix of `job`."""
    rows = ((((workflow.get("jobs") or {}).get(job) or {}).get("strategy") or {}).get("matrix") or {}).get("include") or []
    have = {str(r.get("suite")) for r in rows}
    return ["%s has no leg in the %s matrix" % (suite, job) for suite in linux_suites(required) if suite not in have]


def suites_of(workflow: dict, job: str = "wrapper-e2e") -> list:
    """The suites a run expects a profile of: the gtests, and every leg of `job`."""
    rows = ((((workflow.get("jobs") or {}).get(job) or {}).get("strategy") or {}).get("matrix") or {}).get("include") or []
    return ["gtest"] + [str(r["suite"]) for r in rows]


def run_legs_check(args) -> int:
    import yaml
    required = json.loads(Path(args.required).read_text(encoding="utf-8"))
    workflow = yaml.safe_load(Path(args.workflow).read_text(encoding="utf-8"))
    problems = legs_missing(required, workflow)
    for line in problems:
        print("RED: " + line)
    if not problems:
        print("ok: the %d Linux suites of the wrapper's list all have a leg" % len(linux_suites(required)))
    return 1 if problems else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("map", help="merge the per-suite exports and write the CSVs")
    m.add_argument("--profiles", required=True)
    m.add_argument("--source-root", required=True)
    m.add_argument("--series-root", required=True)
    m.add_argument("--out", required=True)
    m.add_argument("--run-id", default="")
    m.add_argument("--source-commit", default="")
    m.add_argument("--series-commit", default="")
    m.add_argument("--toolchain", default="")
    m.add_argument("--strip-prefix", default="", help="the build machine's source directory, stripped from absolute paths of the exports")
    m.add_argument("--compiled", default="", help="a JSON list of the files the build's notes name")
    m.add_argument("--expect", nargs="*", default=[], help="the suites that should have a profile")
    c = sub.add_parser("legs-check", help="every Linux suite of the wrapper's list has a leg in the workflow")
    c.add_argument("--required", required=True)
    c.add_argument("--workflow", required=True)
    s = sub.add_parser("suites", help="the suites of the workflow, one line, for --expect")
    s.add_argument("--workflow", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "suites":
        import yaml
        print(" ".join(suites_of(yaml.safe_load(Path(args.workflow).read_text(encoding="utf-8")))))
        return 0
    return run_map(args) if args.cmd == "map" else run_legs_check(args)


if __name__ == "__main__":
    sys.exit(main())
