"""The hook contract of the series: what a hooks.patch may add to a Mozilla file, and the debt list.

STRUCTURE (coord/portabilita-69/STRUCTURE.md, sections 3 and 4): a Mozilla file carries only
hooks, each ONE line with the marker `// STEALTH-HOOK(<folder>)` on it and nothing else in the
comment, in one of these forms:

    guard             if (StealthX(this, aArg, &rv)) return rv;      first statement of a function
    notice            StealthX(this, aArg);                          first statement of a function
    wrap-expression   Mozilla's expression, unchanged, inside our call (one Mozilla line rewritten)
    wrap-function     the signature `Foo` renamed `Foo_Mozilla` (one line rewritten) + one declaration
    declared-value    one Mozilla line rewritten with our value (a pref default)
    registration      `#include "StealthX.h"` in a block of ours after Mozilla's, a moz.build
                      `VAR += [...]` after the closing `]`, one line in .ipdl/.webidl/components.conf/jar.mn
    member            one line in a Mozilla class, after an existing member
    anchor            a call right after a named Mozilla statement, mid-function (last resort)
    unknown           anything else

Public API (stable: the HOOKS.json generator reads it):

    series_hooks(root)         -> list[Hook]        every added line / rewrite of every non-backport hooks.patch
    contract_violations(root)  -> list[Violation]   every rule the series breaks now, with a stable key
    analyse_patch(folder, text) -> (hooks, violations)   the same for one hooks.patch text
    load_debt(path) / write_debt(path, violations) / debt_problems(violations, debt, main_debt)
    debt_summary(entries)      -> text

Rules (the id is in the key): C1 a hook of more than one line; C2 marker missing; C3 the marker
comment carries more than the marker; C4 a comment line added; C5 logic in the hook (&&, ||,
ternary, arithmetic); C6 Mozilla lines removed or changed outside the three rewriting forms;
C7 a whole Mozilla file deleted or replaced; C8 an include of ours inside Mozilla's include block;
C9 inside a Mozilla list or the last line of a block; C10 the called function is not Stealth<What>;
C11 a value of ours in a numbered space (IDL const/enum).

The key of a violation is rule|folder|file|function|sha1(normalized text)[:12]: no line number, so a
hook that only moved keeps its key. Folders with a BACKPORT.json are exempt (upstream code).
The anchor form is classified here and not refused: the HOOKS.json step requires its declaration.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")
MARKER_RE = re.compile(r"STEALTH-HOOK\(([^)]*)\)")
FORMS = ("guard", "notice", "wrap-expression", "wrap-function", "declared-value", "registration",
         "member", "anchor", "unknown")
RULES = {
    "C1": "a hook of more than one line",
    "C2": "marker STEALTH-HOOK missing",
    "C3": "the marker comment carries more than the marker",
    "C4": "a comment line added",
    "C5": "logic in the hook (&&, ||, ternary, arithmetic)",
    "C6": "Mozilla lines removed or changed outside the three rewriting forms",
    "C7": "a whole Mozilla file deleted or replaced",
    "C8": "an include of ours inside Mozilla's include block",
    "C9": "inside a Mozilla list or the last line of a block",
    "C10": "the called function is not named Stealth<What>",
    "C11": "a value of ours in a numbered space of Mozilla",
}

HASH_COMMENT = {"py", "yaml", "yml", "toml", "build", "configure", "sh", "txt", "in", "ini",
                "cfg", "cmake", "gitignore", "mk", "conf", "lock"}
SLASH_COMMENT = {"cpp", "cc", "c", "h", "hpp", "mm", "m", "rs", "js", "mjs", "jsm", "jsx",
                 "ts", "java", "kt", "idl", "ipdl", "ipdlh", "webidl", "css", "glsl", "go",
                 "proto", "swift", "cs"}
CLIKE = {"cpp", "cc", "c", "h", "hpp", "mm", "m", "rs", "js", "mjs", "jsm", "jsx", "ts",
         "java", "kt", "idl", "ipdl", "ipdlh", "webidl", "go", "swift", "cs"}
BUILDISH = {"build", "toml", "configure"}
IDL = {"idl", "webidl", "ipdl", "ipdlh"}
HEADERS = {"h", "hpp", "idl"}


@dataclass(frozen=True)
class Hook:
    """One added line of a hooks.patch in a Mozilla file (or one rewrite pair, or a deletion).

    folder, file, function, form, line, removed are the stable part.
    function: the hunk's section header (git's host function); line: the added text without trailing
    whitespace ('' for a deletion); removed: the Mozilla line this one rewrites ('' for a pure addition;
    for a rewrite of unequal sizes the removed lines joined by a newline, on the first hook of the block).
    kind: add | rewrite | delete | file (a whole file deleted or replaced); placement: the position
    class (function_top, mid_function, before_return, end_of_block, list_entry, include_block,
    build_file, file_scope, other, unknown); run / run_index: the length of the run of consecutive
    added lines this line belongs to, and its place in it; marker: the folder named by the marker, or None."""
    folder: str
    file: str
    function: str
    form: str
    line: str
    removed: str = ""
    kind: str = "add"
    placement: str = "unknown"
    run: int = 1
    run_index: int = 0
    marker: str | None = None
    hunk: int = 0


@dataclass(frozen=True)
class Violation:
    rule: str
    folder: str
    file: str
    function: str
    text: str
    key: str
    detail: str = ""


# --------------------------------------------------------------------------- reading a hooks.patch
def file_type_of(path: str) -> str:
    base = path.rsplit("/", 1)[-1]
    if base == "moz.build" or base.endswith(".mozbuild"):
        return "build"
    if "." in base.lstrip("."):
        return base.rsplit(".", 1)[-1].lower()
    return base.lstrip(".").lower() or "none"


def _split_diff_header(s: str):
    if not s.startswith("a/"):
        return s, s
    rest = s[2:]
    for i in range(len(rest)):
        if rest.startswith(" b/", i) and rest[:i] == rest[i + 3:]:
            return rest[:i], rest[:i]
    i = rest.find(" b/")
    return rest[:i], rest[i + 3:]


def parse_patch(text: str) -> list:
    """-> [dict(file, status, hunks=[dict(old_start, old_len, new_start, new_len, section, lines)])];
    lines are (tag, text) with tag in ' ', '+', '-'; a trailing carriage return is dropped."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    files, cur, i, n = [], None, 0, len(lines)
    while i < n:
        ln = lines[i]
        if ln.startswith("diff --git "):
            _, b = _split_diff_header(ln[len("diff --git "):])
            cur = {"file": b, "status": "modified", "hunks": []}
            files.append(cur)
            i += 1
            continue
        if cur is not None and not cur["hunks"]:
            if ln.startswith("new file mode"):
                cur["status"] = "new"
            elif ln.startswith("deleted file mode"):
                cur["status"] = "deleted"
        m = HUNK_RE.match(ln) if cur is not None else None
        if not m:
            i += 1
            continue
        old_len = 1 if m.group(2) is None else int(m.group(2))
        new_len = 1 if m.group(4) is None else int(m.group(4))
        h = {"old_start": int(m.group(1)), "old_len": old_len, "new_start": int(m.group(3)),
             "new_len": new_len, "section": m.group(5).strip(), "lines": []}
        i += 1
        ro, rn = old_len, new_len
        while (ro > 0 or rn > 0) and i < n:
            l = lines[i]
            tag = l[:1]
            if tag == "\\":
                i += 1
                continue
            if tag == "+":
                rn -= 1
            elif tag == "-":
                ro -= 1
            elif tag == " " or l == "":
                ro -= 1
                rn -= 1
                tag = " "
            else:
                break
            h["lines"].append((tag, l[1:].rstrip("\r")))
            i += 1
        while i < n and lines[i].startswith("\\"):
            i += 1
        cur["hunks"].append(h)
    return files


# --------------------------------------------------------------------------- shapes of lines
INCLUDE_RES = [re.compile(p) for p in (
    r"^\s*#\s*(include|import)\b", r"^\s*import\b", r"^\s*from\s+\S+\s+import\b",
    r"^\s*use\s+[\w:{]", r"^\s*(extern\s+crate|mod)\s+\w",
    r"^\s*(const|let|var)\s+.*=\s*(ChromeUtils\.(importESModule|import)|require)\(")]
PP_COND = re.compile(r"^\s*#\s*(if|ifdef|ifndef|else|elif|endif)\b")
CONTROL = re.compile(r"^(\}\s*)?(if|else|for|while|switch|do|try|catch|namespace|struct|class|enum|union|extern|case|default)\b")
OPENERS = ("//", "/*", "<!--", "#", ";")
CLOSERS = ("", "*/", "-->")
STEALTH_NAME = re.compile(r"^(?:nr_)?(?:Stealth|stealth_)\w*")
CALL = re.compile(r"((?:[A-Za-z_]\w*(?:::|\.|->))*[A-Za-z_]\w*)\s*\(")
KEYWORDS = {"if", "while", "for", "switch", "return", "sizeof", "catch", "else", "do"}
BUILD_ADD = re.compile(r"^[A-Za-z_][\w.\[\]\"']*\s*\+=\s*\[.*\]$")
GUARD_C = re.compile(r"^if\s*\(.*\)\s*return\b[^;{}]*;$")        # a guard: a call in its condition
GUARD_PY = re.compile(r"^if\s+.*:\s*return\b.*$")
NOTICE = re.compile(r"^([\w:.\->]+)\s*\(.*\)\s*;?$")
NUMBERED = re.compile(r"(=\s*(0x[0-9a-fA-F]+|\d+)\s*;)|(1\s*<<\s*\d+)")


def norm(t: str) -> str:
    return re.sub(r"\s+", "", t)


def _squeeze(t: str) -> str:
    return re.sub(r"\s+", " ", t.strip())


def is_comment_line(t: str, ft: str) -> bool:
    s = t.strip()
    if not s:
        return False
    if s.startswith(("//", "/*", "*/")) or (s.startswith("*") and ft in SLASH_COMMENT):
        return True
    if ft in HASH_COMMENT and s.startswith("#"):
        return True
    if s.startswith("<!--"):
        return True
    if ft == "in" and s.startswith(";"):
        return True
    return False


def is_include(t: str) -> bool:
    return any(r.match(t) for r in INCLUDE_RES)


def indent_of(t: str) -> int:
    return len(t) - len(t.lstrip(" \t"))


def list_item(s: str) -> bool:
    return bool(re.match(r"""^["'][^"']*["'],?\s*(#.*)?$""", s)) or s.endswith(",")


def marker_split(line: str):
    """-> (code, marker_folder or None, extra): the line without its marker comment, the folder the
    marker names, and the text of the comment beyond the marker (before or after it)."""
    m = MARKER_RE.search(line)
    if not m:
        return line.strip(), None, ""
    pre, post = line[:m.start()].rstrip(), line[m.end():].strip()
    extra = ""
    opener = next((o for o in OPENERS if pre.endswith(o)), None)
    if opener:
        code = pre[:-len(opener)].rstrip()
    else:
        # text between the comment opener and the marker: `// note STEALTH-HOOK(x)`
        k = max((pre.rfind(o) for o in OPENERS), default=-1)
        if k >= 0:
            code, extra = pre[:k].rstrip(), pre[k:]
        else:
            code, extra = pre, pre
    if post not in CLOSERS:
        extra = (extra + " " + post).strip()
    return code.strip(), m.group(1), extra


def calls(code: str) -> list:
    return [c for c in CALL.findall(code) if c.rsplit("::", 1)[-1] not in KEYWORDS and c not in KEYWORDS]


def is_stealth_chain(chain: str) -> bool:
    return any(STEALTH_NAME.match(seg) for seg in re.split(r"::|\.|->", chain))


def _strip_literals(code: str) -> str:
    code = re.sub(r'"(?:\\.|[^"\\])*"', '""', code)
    return re.sub(r"'(?:\\.|[^'\\])*'", "''", code)


def has_logic(code: str, ft: str) -> bool:
    s = _strip_literals(code).replace("->", ".")
    if "&&" in s or "||" in s or "?" in s.replace("?.", "."):
        return True
    if re.search(r"\s[-+*/%]\s", s) or "<<" in s:
        return True
    if ft == "py" and re.search(r"\b(and|or)\b", s):
        return True
    return False


# --------------------------------------------------------------------------- position of a change
def classify(ft: str, section: str, lines: list):
    """-> (placement, at_block_end) for the changed lines of `lines` (a block with its context)."""
    tags = [t for t, _ in lines]
    idx = [k for k, t in enumerate(tags) if t != " "]
    first, last = idx[0], idx[-1]
    prev = ""
    for k in range(first - 1, -1, -1):
        if lines[k][1].strip():
            prev = lines[k][1].strip()
            break
    nxt = ""
    for k in range(last + 1, len(lines)):
        if lines[k][1].strip():
            nxt = lines[k][1].strip()
            break
    eof = len(lines) - 1 - last < 3
    added = [x for t, x in lines if t == "+"]
    removed = [x for t, x in lines if t == "-"]
    code = [x for x in added if x.strip() and not is_comment_line(x, ft)]
    if not code:
        code = [x for x in added if x.strip()]
    if not code:
        code = [x for x in removed if x.strip() and not is_comment_line(x, ft)] or [x for x in removed if x.strip()]
    if not code:
        return "unknown", False
    cs = [x.strip() for x in code]
    closing = nxt.startswith(("}", "]", ")"))
    at_end = closing or eof
    if ft in BUILDISH:
        if (list_item(cs[-1]) and (list_item(prev) or list_item(nxt) or prev.endswith(("[", "(")))) or \
           (list_item(prev) and nxt.startswith(("]", ")"))):
            return "list_entry", at_end
        return "build_file", at_end
    if any(is_include(x) for x in code) and all(is_include(x) or PP_COND.match(x) for x in code):
        return "include_block", at_end
    if ft in ("yaml", "yml"):
        if cs[0].startswith("-") or prev.startswith("-"):
            return "list_entry", at_end
        return "other", at_end
    if ft not in CLIKE and ft != "py":
        return "other", at_end
    ends_comma = cs[-1].endswith(",")
    pc, nc = prev.endswith(","), nxt.endswith(",")
    opener_list = prev.endswith(("{", "[", "(")) and (("=" in prev) or prev.startswith(("enum", "static", "const")) or prev.endswith(("[", "(")))
    if ft != "py" and ((ends_comma and (pc or nc or opener_list)) or (pc and closing)):
        return "list_entry", at_end
    if ft == "py":
        if re.match(r"^(async\s+)?def\s.*:$", prev):
            return "function_top", at_end
    elif prev.endswith("{") and not CONTROL.match(prev) and ")" in prev and "= {" not in prev and "={" not in prev:
        return "function_top", at_end
    if re.match(r"^return\b", nxt):
        return "before_return", at_end
    if at_end:
        return "end_of_block", at_end
    mind = min(indent_of(x) for x in code)
    if mind == 0:
        return "file_scope", at_end
    if ft in IDL:
        return "other", at_end
    if ft in ("h", "hpp"):
        return ("mid_function" if mind >= 4 else "other"), at_end
    if ft in ("cpp", "cc", "mm", "c", "m"):
        return "mid_function", at_end
    if "(" in section or (mind >= 2 and re.search(r"[;)]$", prev)):
        return "mid_function", at_end
    return "unknown", at_end


# --------------------------------------------------------------------------- form of a line
def _mozilla_expression(removed: str, code: str):
    """The part of `code` that is Mozilla's removed line (whitespace-insensitive) and what is left of
    `code` without it, or None if Mozilla's expression is not in `code` unchanged."""
    r = removed.strip()
    variants = [r, r.rstrip(";").strip()]
    if r.startswith("return "):
        variants.append(r[len("return "):].rstrip(";").strip())
    for v in variants:
        if not v:
            continue
        pat = r"\s*".join(re.escape(tok) for tok in v.split())
        m = re.search(pat, code)
        if m:
            return v, code[:m.start()] + " " + code[m.end():]
    return None


TOKEN = re.compile(r"""\s*("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\w+|\S)""")
LITERAL = re.compile(r"""^("|'|\d|true$|false$|nullptr$|null$|None$|True$|False$)""")


def _value_change(removed: str, code: str) -> bool:
    """True if `code` is `removed` with only literals (numbers, strings, true/false) changed."""
    def toks(t):
        return TOKEN.findall(re.sub(r"\s(//|#)\s.*$", "", t.strip()))
    r, c = toks(removed), toks(code)
    return len(r) == len(c) and any(x != y for x, y in zip(r, c)) and \
        all(x == y or (LITERAL.match(x) and LITERAL.match(y)) for x, y in zip(r, c))


def line_form(ft: str, base: str, code: str, removed: str, kind: str, placement: str, pair: bool):
    """-> (form, remainder): the form of one added code line. remainder: for wrap-expression, the
    line without Mozilla's expression (what the logic and name rules look at), else the code."""
    if not code or is_comment_line(code, ft):
        return "unknown", code
    if kind == "rewrite":
        if "_Mozilla" in code and re.sub(r"_Mozilla\b", "", norm(code)) == norm(removed or ""):
            return "wrap-function", code
        if pair and removed:
            got = _mozilla_expression(removed, code)
            if got and got[1].strip() not in ("", ";") and calls(got[1]):
                return "wrap-expression", got[1]
            if _value_change(removed, code):
                return "declared-value", code
        return "unknown", code
    if is_include(code):
        return "registration", code
    if ft in ("ipdl", "ipdlh", "webidl") or base in ("components.conf", "jar.mn"):
        return "registration", code
    if ft == "build":
        return ("registration" if BUILD_ADD.match(code) else "unknown"), code
    if "_Mozilla" in code and ft in HEADERS and code.rstrip().endswith(";"):
        return "wrap-function", code
    guard = GUARD_PY.match(code) if ft == "py" else GUARD_C.match(code)
    if guard and calls(code):
        return ("guard" if placement == "function_top" else "anchor"), code
    if NOTICE.match(code) and not re.match(r"^(return|else|do|goto|delete|throw|co_return)\b", code):
        return ("notice" if placement == "function_top" else "anchor"), code
    if ft in HEADERS and re.search(r"[;,]$", code) and not NOTICE.match(code):
        return "member", code
    return "unknown", code


def _is_multi_ok(ft: str, code: str) -> bool:
    return is_include(code) or (ft == "build" and bool(BUILD_ADD.match(code)))


# --------------------------------------------------------------------------- the analysis
def _key(rule: str, folder: str, file: str, function: str, text: str) -> str:
    return "%s|%s|%s|%s|%s" % (rule, folder, file, _squeeze(function),
                               hashlib.sha1(_squeeze(text).encode("utf-8")).hexdigest()[:12])


def _whole_file(f: dict) -> str:
    """'deleted' or 'replaced' if the file's diff takes the Mozilla file away: its status says so,
    or one hunk from the first line with no context that removes at least 20 lines."""
    if f["status"] == "deleted":
        return "deleted"
    for h in f["hunks"]:
        lines = h["lines"]
        if (h["old_start"] <= 1 and len(f["hunks"]) == 1 and lines and all(t != " " for t, _ in lines)
                and sum(1 for t, _ in lines if t == "-") >= 20):
            return "replaced"
    return ""


def _blocks(lines: list) -> list:
    """The blocks of changed lines of a hunk: dict(rem, add, lo, hi, ns); ns: how many lines of the new
    side come before the block, so add[i] is new_side[ns + i]."""
    blocks, k, ns = [], 0, 0
    while k < len(lines):
        if lines[k][0] == " ":
            ns += 1
            k += 1
            continue
        b = {"rem": [], "add": [], "lo": k, "ns": ns}
        while k < len(lines) and lines[k][0] != " ":
            if lines[k][0] == "-":
                b["rem"].append(lines[k][1])
            else:
                b["add"].append(lines[k][1])
                ns += 1
            k += 1
        b["hi"] = k
        blocks.append(b)
    return blocks


def _runs(nonblank: list) -> list:
    """Runs of consecutive added lines: nonblank is [(index in the block's added lines, text)]."""
    runs, cur, last = [], [], None
    for i, x in nonblank:
        if cur and i != last + 1:
            runs.append(cur)
            cur = []
        cur.append((i, x))
        last = i
    if cur:
        runs.append(cur)
    return runs


def analyse_patch(folder: str, text: str):
    """-> (hooks, violations) of one hooks.patch (folder: its series folder). Does not look at
    BACKPORT.json: series_hooks skips those folders."""
    hooks, found = [], []

    def violate(rule, file, function, txt, detail=""):
        found.append(Violation(rule, folder, file, function, txt, _key(rule, folder, file, function, txt), detail))

    for f in parse_patch(text):
        path, ft = f["file"], file_type_of(f["file"])
        base = path.rsplit("/", 1)[-1]
        whole = _whole_file(f)
        if whole:
            hooks.append(Hook(folder, path, "", "unknown", "", "<%s file>" % whole, "file", "unknown"))
            violate("C7", path, "", "<%s>" % whole, whole)
            continue
        for hno, h in enumerate(f["hunks"], 1):
            lines, section = h["lines"], h["section"]
            new_side = [(t, x) for t, x in lines if t != "-"]
            for b in _blocks(lines):
                rem, add = b["rem"], b["add"]
                kind = "rewrite" if add and rem else ("add" if add else "delete")
                # the block with its context: the changes of other blocks as the new side has them
                sub = []
                for i, (t, x) in enumerate(lines):
                    if b["lo"] <= i < b["hi"]:
                        sub.append((t, x))
                    elif t != "-":
                        sub.append((" ", x))
                placement, at_end = classify(ft, section, sub)
                if kind == "delete":
                    hooks.append(Hook(folder, path, section, "unknown", "", "\n".join(rem), "delete", placement, 0, 0, None, hno))
                    violate("C6", path, section, "-" + "\n-".join(x.strip() for x in rem),
                            "%d Mozilla lines removed" % len(rem))
                    continue
                nonblank = [(i, x.rstrip()) for i, x in enumerate(add) if x.strip()]
                paired = bool(rem) and len(rem) == len(nonblank)       # a rewrite line for line
                single_pair = paired and len(rem) == 1
                forms, nb = [], 0
                for run in _runs(nonblank):
                    codes = [marker_split(x) for _, x in run]
                    run_text = "\n".join(x for _, x in run)
                    multi_ok = all(_is_multi_ok(ft, c) for c, _, _ in codes)
                    run_forms = []
                    for j, (i, x) in enumerate(run):
                        code, mk, extra = codes[j]
                        rm = ""
                        if kind == "rewrite":
                            rm = rem[nb] if paired else ("\n".join(rem) if nb == 0 else "")
                        nb += 1
                        form, remainder = line_form(ft, base, code, rm, kind, placement, single_pair)
                        if len(run) > 1 and not multi_ok:        # a form is the form of a one-line hook
                            form, remainder = "unknown", code
                        run_forms.append((form, remainder))
                        hooks.append(Hook(folder, path, section, form, x, rm, kind, placement, len(run), j, mk, hno))
                        if mk is not None and extra:
                            violate("C3", path, section, x, extra)
                        if is_comment_line(x, ft):
                            violate("C4", path, section, x)
                        if ft in IDL and NUMBERED.search(x) and not is_comment_line(x, ft):
                            violate("C11", path, section, x)
                        if kind == "add" and is_include(code):
                            at = b["ns"] + i
                            before = new_side[at - 1] if at >= 1 else None
                            after = new_side[at + 1] if at + 1 < len(new_side) else None
                            if (before and before[0] == " " and is_include(before[1])) or                                (after and after[0] == " " and is_include(after[1])):
                                violate("C8", path, section, x)
                    forms += [f_ for f_, _ in run_forms]
                    if len(run) > 1 and not multi_ok:
                        violate("C1", path, section, run_text, "%d lines" % len(run))
                    if not any(mk is not None for _, mk, _ in codes) and not all(is_include(c) for c, _, _ in codes):
                        violate("C2", path, section, run_text)
                    if len(run) == 1:
                        form, remainder = run_forms[0]
                        if (form in ("guard", "notice", "anchor", "wrap-expression", "declared-value")
                                or (form == "unknown" and any(is_stealth_chain(c) for c in calls(remainder))))                                 and has_logic(remainder, ft):
                            violate("C5", path, section, run_text)
                        if form in ("guard", "notice", "anchor", "wrap-expression"):
                            cs = calls(remainder)
                            if cs and not is_stealth_chain(cs[0]):
                                violate("C10", path, section, run_text, cs[0])
                add_text = "\n".join(x for _, x in nonblank)
                if rem:
                    if not (single_pair and forms and forms[0] in ("wrap-expression", "wrap-function", "declared-value")):
                        violate("C6", path, section, "-" + "\n-".join(x.strip() for x in rem) + "\n" + add_text,
                                "%d Mozilla lines removed, %d added" % (len(rem), len(nonblank)))
                elif nonblank:
                    all_inc = all(is_include(marker_split(x)[0]) for _, x in nonblank)
                    if not all_inc and not all(f_ == "wrap-function" for f_ in forms) and (
                            placement in ("list_entry", "end_of_block")
                            or (at_end and placement not in ("include_block", "build_file"))):
                        violate("C9", path, section, add_text, "placement=%s at_block_end=%s" % (placement, at_end))
    return hooks, _unique(found)


def _unique(found: list) -> list:
    """Two identical hooks in one function share a key: the second gets `#2`, and so on."""
    seen, out = {}, []
    for v in found:
        n = seen.get(v.key, 0) + 1
        seen[v.key] = n
        out.append(v if n == 1 else Violation(v.rule, v.folder, v.file, v.function, v.text, "%s#%d" % (v.key, n), v.detail))
    return out


def _folders(root: Path) -> list:
    names = (root / "SERIES").read_text(encoding="utf-8").split()
    return [f for f in names if (root / f / "hooks.patch").is_file() and not (root / f / "BACKPORT.json").exists()]


def _analyse(root: Path):
    root = Path(root)
    hooks, found = [], []
    for folder in _folders(root):
        h, v = analyse_patch(folder, (root / folder / "hooks.patch").read_text(encoding="utf-8", errors="replace"))
        hooks += h
        found += v
    return hooks, found


def series_hooks(root) -> list:
    """Every hook of the series: one Hook per added line (one per rewrite pair, one for a deletion) in a
    Mozilla file of the hooks.patch of every folder of SERIES that is not a backport."""
    return _analyse(root)[0]


def contract_violations(root) -> list:
    """Every rule the series breaks now, ordered by key. See the module's rules C1..C11."""
    return sorted(_analyse(root)[1], key=lambda v: v.key)


# --------------------------------------------------------------------------- the debt list
def entry_of(v: Violation) -> dict:
    return {"key": v.key, "rule": v.rule, "folder": v.folder, "file": v.file,
            "text": _squeeze(v.text)[:120]}


def load_debt(path: Path) -> list:
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []


def debt_text(entries: list) -> str:
    return json.dumps(sorted(entries, key=lambda e: e["key"]), indent=1, ensure_ascii=False) + "\n"


def write_debt(path: Path, entries: list) -> None:
    Path(path).write_text(debt_text(entries), encoding="utf-8", newline="")


def update_debt(entries: list, violations: list, init: bool = False) -> list:
    """The debt after `hook-debt`: with init, every violation of now; without, only the entries that
    still occur (a list never grows by itself)."""
    if init:
        return [entry_of(v) for v in violations]
    now = {v.key for v in violations}
    return [e for e in entries if e["key"] in now]


def debt_problems(violations: list, debt: list, main_debt: list | None) -> list:
    """The check: a violation not in the debt, an entry that no longer occurs, an entry main does not
    have (the list only shrinks against main; main_debt None: main has no list yet)."""
    found = []
    now = {v.key: v for v in violations}
    listed = {e["key"] for e in debt}
    for key in sorted(set(now) - listed):
        v = now[key]
        found.append("%s/hooks.patch, %s: %s (%s): a hook breaks the contract and is not in the debt list "
                     "(tools/hook-debt.json): %s" % (v.folder, v.file, v.rule, RULES[v.rule], _squeeze(v.text)[:100]))
    for key in sorted(listed - set(now)):
        found.append("tools/hook-debt.json lists %s, which no longer occurs: remove it: python tools/engine.py hook-debt" % key)
    if main_debt is not None:
        main_keys = {e["key"] for e in main_debt}
        for key in sorted(listed - main_keys):
            found.append("tools/hook-debt.json has %s, which main's list does not have: the debt only shrinks" % key)
    return found


def debt_summary(entries: list, top: int = 15) -> str:
    by_rule, by_folder = {}, {}
    for e in entries:
        by_rule[e["rule"]] = by_rule.get(e["rule"], 0) + 1
        by_folder[e["folder"]] = by_folder.get(e["folder"], 0) + 1
    out = ["%d violations in the debt list" % len(entries), "per rule:"]
    for r in sorted(by_rule):
        out.append("  %-4s %4d  %s" % (r, by_rule[r], RULES[r]))
    out.append("per folder (%d of %d):" % (min(top, len(by_folder)), len(by_folder)))
    for f, n in sorted(by_folder.items(), key=lambda x: (-x[1], x[0]))[:top]:
        out.append("  %4d  %s" % (n, f))
    return "\n".join(out)
