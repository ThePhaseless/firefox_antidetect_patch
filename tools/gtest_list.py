"""repo-06: the list of gtest suites the hooks name, written from the series (`python tools/engine.py gtest-list --write`, and the export).

Every HOOKS.json entry whose `test` is `gtest:<Suite>.<Name>` names a suite. tools/gtest-suites.json lists those suites, sorted, one record each:

    {"suite": "StealthGLMultisample", "windows_only": false, "linux_only": false}

`windows_only` is true when none of the suite's tests is built on Linux, `linux_only` when none is built on Windows. A test is built on a platform
unless one of two things keeps it out, both read from the series (nothing else is looked at, and a condition this file cannot read keeps the
test on both platforms):

  * the preprocessor: the test sits between `#ifdef XP_WIN` (or `#if defined(XP_LINUX) && ...`) and its `#endif`, in the file of ours that
    holds it under a folder's src/;
  * moz.build: the file that holds the test is listed under `if CONFIG["OS_TARGET"] == "WINNT":` (or OS_ARCH, or MOZ_WIDGET_TOOLKIT, `==`
    or `!=`), in a moz.build, a `*.mozbuild` or a `*.build` of ours under src/ or in the lines a hooks.patch adds to a Mozilla moz.build.

A suite is judged by every test of it that the series defines, not only by the ones a hook names. The consumers (the candidate workflow's
filter, the release plan, the gtest runner) read the file; they do not list suites by hand.

    suites(root)        -> list[dict]       the records, from the series at `root`
    render(rows)        -> str              the bytes of the file
    write(root)         -> str              writes tools/gtest-suites.json, returns one line saying what it holds
    problems(root)      -> list[Failure]    what `check` reports: the file is missing or is not what `write` would write
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hooks_list  # noqa: E402
from failure import fail  # noqa: E402

RULE = "repo-06-what-a-tool-can-write-a-tool-writes"
FILE = "tools/gtest-suites.json"
PLATFORMS = ("windows", "linux")

# What the two platforms define (1) and do not (0); a macro that is in neither table is unknown, and unknown keeps a test on both.
DEFINED = {
    "windows": {"XP_WIN": 1, "_WIN32": 1, "WIN32": 1},
    "linux": {"XP_LINUX": 1, "XP_UNIX": 1, "__linux__": 1, "MOZ_WIDGET_GTK": 1, "__x86_64__": 1},
}
UNDEFINED = {
    "windows": {"XP_LINUX", "XP_UNIX", "__linux__", "MOZ_WIDGET_GTK", "ANDROID", "XP_MACOSX", "XP_DARWIN", "XP_IOS"},
    "linux": {"XP_WIN", "_WIN32", "WIN32", "ANDROID", "XP_MACOSX", "XP_DARWIN", "XP_IOS"},
}
CONFIG_VALUES = {   # moz.build: CONFIG key -> value per platform
    "OS_TARGET": {"windows": "WINNT", "linux": "Linux"},
    "OS_ARCH": {"windows": "WINNT", "linux": "Linux"},
    "MOZ_WIDGET_TOOLKIT": {"windows": "windows", "linux": "gtk"},
}
CONFIG_IF = re.compile(r"""^if\s+CONFIG\[["'](\w+)["']\]\s*(==|!=)\s*["']([^"']*)["']\s*:""")
TOKEN = re.compile(r"\s*(defined|&&|\|\||!|\(|\)|[A-Za-z_]\w*|\d+)")
BUILD_FILES = ("moz.build", "*.mozbuild", "*.build")      # the build files of ours under src/: moz.build, and the files a moz.build includes
PATCH_FILE = re.compile(r"^diff --git a/(\S+) b/")


def _not(v):
    return None if v is None else not v


def _and(a, b):
    return False if a is False or b is False else (None if a is None or b is None else True)


def _or(a, b):
    return True if a is True or b is True else (None if a is None or b is None else False)


def evaluate(condition: str, platform: str):
    """True, False or None (cannot say) for the condition of an #if on `platform`: defined(X), defined X, a bare macro, numbers, !, && and ||,
    parentheses. Anything else (a comparison, a function-like macro) is None."""
    text = re.sub(r"/\*.*?\*/|//.*", "", condition).strip()
    tokens, pos = [], 0
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if not m:
            return None
        tokens.append(m.group(1))
        pos = m.end()
    i = 0

    def macro(name):
        if name in DEFINED[platform]:
            return True
        return False if name in UNDEFINED[platform] else None

    def primary():
        nonlocal i
        if i >= len(tokens):
            raise ValueError
        tok = tokens[i]
        i += 1
        if tok == "!":
            return _not(primary())
        if tok == "(":
            v = disjunction()
            if i >= len(tokens) or tokens[i] != ")":
                raise ValueError
            i += 1
            return v
        if tok == "defined":
            paren = i < len(tokens) and tokens[i] == "("
            i += paren
            if i >= len(tokens):
                raise ValueError
            name = tokens[i]
            i += 1
            if paren:
                if i >= len(tokens) or tokens[i] != ")":
                    raise ValueError
                i += 1
            return macro(name)
        if tok.isdigit():
            return int(tok) != 0
        if tok in ("&&", "||", ")"):
            raise ValueError
        v = macro(tok)         # a bare macro: defined to 1 or not at all
        return v

    def conjunction():
        nonlocal i
        v = primary()
        while i < len(tokens) and tokens[i] == "&&":
            i += 1
            v = _and(v, primary())
        return v

    def disjunction():
        nonlocal i
        v = conjunction()
        while i < len(tokens) and tokens[i] == "||":
            i += 1
            v = _or(v, conjunction())
        return v

    try:
        v = disjunction()
    except ValueError:
        return None
    return v if i == len(tokens) else None


def guarded_lines(text: str) -> list:
    """For every line of a C++ file, the set of platforms that compile it: the #if stack read with `evaluate`, the line numbers 0-based."""
    lines = text.splitlines()
    stack, out, k = [], [], 0
    while k < len(lines):
        line = lines[k]
        directive = line.strip()
        if directive.startswith("#"):
            while directive.endswith("\\") and k + 1 < len(lines):      # a continued directive is one line
                k += 1
                directive = directive[:-1] + " " + lines[k].strip()
            m = re.match(r"#\s*(ifdef|ifndef|if|elif|else|endif)\b(.*)", directive)
        else:
            m = None
        if m:
            word, rest = m.group(1), m.group(2).strip()
            if word in ("if", "ifdef", "ifndef"):
                values = {}
                for p in PLATFORMS:
                    if word == "if":
                        v = evaluate(rest, p)
                    else:
                        v = evaluate("defined(%s)" % rest.split()[0] if rest.split() else "", p)
                        v = _not(v) if word == "ifndef" else v
                    values[p] = v
                stack.append({"now": dict(values), "true": {p: values[p] is True for p in PLATFORMS},
                              "maybe": {p: values[p] is None for p in PLATFORMS}})
            elif word == "elif" and stack:
                frame = stack[-1]
                for p in PLATFORMS:
                    v = evaluate(rest, p)
                    now = False if frame["true"][p] else (_and(None, v) if frame["maybe"][p] else v)
                    frame["now"][p] = now
                    frame["true"][p] = frame["true"][p] or now is True
                    frame["maybe"][p] = frame["maybe"][p] or now is None
            elif word == "else" and stack:
                frame = stack[-1]
                for p in PLATFORMS:
                    frame["now"][p] = False if frame["true"][p] else (None if frame["maybe"][p] else True)
            elif word == "endif" and stack:
                stack.pop()
        out.append({p for p in PLATFORMS if all(f["now"][p] is not False for f in stack)})
        k += 1
        while len(out) < k:                  # the lines a continued directive swallowed
            out.append(out[-1])
    return out


def build_listings(root: Path) -> dict:
    """File name (as moz.build writes it) -> list of sets of platforms: one per place a moz.build lists it, read from the moz.build, *.mozbuild
    and *.build files of ours under src/ and from the lines a hooks.patch adds to a Mozilla moz.build (its context lines come with them)."""
    texts = []
    for folder in hooks_list.series_names(root):
        d = Path(root) / folder
        src = d / "src"
        if src.is_dir():
            found = {p for pattern in BUILD_FILES for p in src.rglob(pattern) if p.is_file()}
            texts += [p.read_text(encoding="utf-8", errors="replace") for p in sorted(found)]
        patch = d / "hooks.patch"
        if patch.is_file():
            current = None
            for line in patch.read_text(encoding="utf-8", errors="replace").splitlines():
                m = PATCH_FILE.match(line)
                if m:
                    current = [] if m.group(1).endswith("moz.build") else None
                    if current is not None:
                        texts.append(current)
                elif current is not None and line[:1] in (" ", "+") and not line.startswith(("+++", "---")):
                    current.append(line[1:])
    listings = {}
    for text in texts:
        lines = text if isinstance(text, list) else text.splitlines()
        for n, line in enumerate(lines):
            for name in re.findall(r"""["']([\w.\-]+\.(?:cpp|cc|cxx))["']""", line):
                listings.setdefault(name, []).append(_moz_platforms(lines, n))
    return listings


def _moz_platforms(lines: list, n: int) -> set:
    """The platforms whose `if CONFIG[...]` blocks (the enclosing ones, by indentation) keep line `n` of a moz.build."""
    allowed = set(PLATFORMS)
    need = len(lines[n]) - len(lines[n].lstrip())
    for j in range(n - 1, -1, -1):
        if need == 0:
            break
        line = lines[j]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent < need:
            need = indent
            m = CONFIG_IF.match(line.strip())
            if m and m.group(1) in CONFIG_VALUES:
                key, op, value = m.groups()
                for p in PLATFORMS:
                    if (CONFIG_VALUES[key][p] == value) == (op == "!="):
                        allowed.discard(p)
    return allowed


def definitions(root: Path) -> dict:
    """(suite, name) -> list of (file name, platforms that compile the test): every TEST and TEST_F under a folder's src/."""
    found = {}
    for folder in hooks_list.series_names(root):
        src = Path(root) / folder / "src"
        if not src.is_dir():
            continue
        for p in sorted(src.rglob("*")):
            if p.suffix in hooks_list.GTEST_SUFFIXES and p.is_file():
                text = p.read_text(encoding="utf-8", errors="replace")
                if "TEST" not in text:
                    continue
                active = guarded_lines(text)
                for m in hooks_list.GTEST_RE.finditer(text):
                    line = text.count("\n", 0, m.start())
                    found.setdefault((m.group(1), m.group(2)), []).append((p.name, active[line] if line < len(active) else set(PLATFORMS)))
    return found


def referenced(root: Path) -> set:
    """The suites the HOOKS.json files name: every `test` of the form gtest:<Suite>.<Name>."""
    names = set()
    for folder in hooks_list.folders(root):
        for e in hooks_list.load(root, folder) or []:
            test = e.get("test", "") if isinstance(e, dict) else ""
            if isinstance(test, str) and test.startswith("gtest:"):
                suite = test[len("gtest:"):].partition(".")[0]
                if suite:
                    names.add(suite)
    return names


def suites(root: Path) -> list:
    """The records of tools/gtest-suites.json: one per suite a hook names, sorted by suite name."""
    root = Path(root)
    defined, listings = definitions(root), build_listings(root)
    built = {}                    # suite -> platforms where some test of it is built
    for (suite, _), places in defined.items():
        for filename, compiled in places:
            keeps = set(PLATFORMS)
            if filename in listings:
                keeps = set().union(*listings[filename])
            built.setdefault(suite, set()).update(compiled & keeps)
    rows = []
    for suite in sorted(referenced(root)):
        where = built.get(suite, set(PLATFORMS)) if suite in built else set(PLATFORMS)
        rows.append({"suite": suite, "windows_only": where == {"windows"}, "linux_only": where == {"linux"}})
    return rows


def render(rows: list) -> str:
    return json.dumps(rows, indent=1, ensure_ascii=False) + "\n"


def write(root: Path) -> str:
    rows = suites(root)
    path = Path(root) / FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(render(rows).encode("utf-8"))
    return "%s: %d suites (%d windows only, %d linux only)" % (FILE, len(rows), sum(r["windows_only"] for r in rows), sum(r["linux_only"] for r in rows))


def problems(root: Path) -> list:
    """The file is there and is exactly what `write` would write from the HOOKS.json files and the sources of the series."""
    path = Path(root) / FILE
    again = "python tools/engine.py gtest-list --write"
    if not path.is_file():
        return [fail(FILE, "it does not exist", "write it: `%s`" % again, RULE)]
    if path.read_bytes() != render(suites(root)).encode("utf-8"):
        return [fail(FILE, "it is not the list of gtest suites the HOOKS.json files name now (a hook was added or retested, a suite moved to another "
                           "platform, or the file was edited by hand)", "do not edit it: `%s` writes it" % again, RULE)]
    return []
