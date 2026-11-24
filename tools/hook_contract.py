"""The hook contract of the series: what a hooks.patch may add to a Mozilla file, and the debt list.

STRUCTURE (coord/portabilita-69/STRUCTURE.md, sections 3 and 4): a Mozilla file carries only
hooks, each ONE line with the marker `// STEALTH-HOOK(<folder>)` on it and nothing else in the
comment, in one of these forms:

    guard             if (StealthX(this, aArg, &rv)) return rv;      first statement of a function
    notice            StealthX(this, aArg);                          first statement of a function
    wrap-expression   Mozilla's expression, unchanged, inside our call (one Mozilla line rewritten): the whole
                      expression, or a sub-expression of the line, with our extra leading arguments (`this, `)
                      G53: or a multi-line expression: one line of ours added to open our call (marker on it), Mozilla's lines
                      in between unchanged, the closing line Mozilla's plus our `)` and the marker
    wrap-call         G29: the one called identifier `Foo` of Mozilla's line becomes `StealthFoo`, same arguments;
                      G9: or one argument of ours (a Stealth call) is added to a call of Mozilla's line
    wrap-function     G1/G2: the signature or macro `Foo` renamed `Foo_Mozilla` (or by another suffix, `FooAsDrawn`),
                      one line rewritten; the one-line declarations and the internal calls rewritten to the same new name
                      G29/G9: or the called function replaced and exactly one plain argument of ours added (`this`, a member),
                      or one plain argument added in front of the closing line of a call that spans lines
    declared-value    one Mozilla line rewritten with our value (a pref default: a literal in place of a literal, or one
                      STEALTH_ macro in place of one literal or one macro of Mozilla's)
    registration      `#include "StealthX.h"` in a block of ours after Mozilla's, a moz.build
                      `VAR += [...]` after the closing `]`, one line in .ipdl/.webidl/components.conf/jar.mn,
                      G40: a forward declaration `class X;` or a file-scope declaration of a function of ours
    member            one line in a Mozilla class, after an existing member
    shadow            G21: `const auto GetX = StealthGetX;` at the top of a function (our value for a Mozilla name)
    anchor            a call right after a named Mozilla statement, mid-function (last resort); G30/G33: it
                      may be the last line of a block or of a JS module, with its `anchor` and `why` in HOOKS.json
    unknown           anything else

Public API (stable: the HOOKS.json generator reads it):

    series_hooks(root)         -> list[Hook]        every added line / rewrite of every non-backport hooks.patch
    contract_violations(root)  -> list[Violation]   every rule the series breaks now, with a stable key
    analyse_patch(folder, text) -> (hooks, violations)   the same for one hooks.patch text
    load_debt(path) / write_debt(path, violations) / debt_problems(violations, debt, main_debt)
    debt_summary(entries)      -> text

Rules (the id is in the key; C12..C15 are port-06, below): C1 a hook of more than one line (two adjacent lines are two hooks when each is a complete statement or declaration
with its own marker: C1 is a line of ours without a marker in a run, or one statement over several lines); C2 marker missing; C3 the marker
comment carries more than the marker; C4 a comment line added; C5 logic in the hook (&&, ||,
ternary, arithmetic); C6 Mozilla lines removed or changed outside the three rewriting forms;
C7 a whole Mozilla file deleted or replaced; C8 an include of ours inside Mozilla's include block;
C9 inside a Mozilla list or the last line of a block (an anchor there is G30/G33: not C9, T2 asks for
its `anchor` and `why`); C10 the called function is not Stealth<What> and is not an existing function (G41: tools/hook-names.json, the
called names of the hooks that existed when the rule came; a new function takes a Stealth name); C11 a value of ours in a numbered
space (IDL const/enum); T1 a hook whose HOOKS.json entry has no `test`; T2 an anchor hook whose entry has
no `anchor` and `why`; T3 a hook whose `test` no round runs (tools/hooks_list.py: the debt list holds
every hook without a test until it has one).

G35, declared exception: a HOOKS.json entry with the hand fields `exception` (the reason) and `pm:
"approvato"` is a rewritten line no form can express; contract_violations leaves out every violation of
such a hook (C1..C11, T1, T2, T3), and `check` counts them: "declared exceptions: N". The rules C12..C15 (port-06) are the
opposite: they judge the exception itself, by its `reason_kind` (see the port-06 section below).
Port-06 (docs/decisions/port-06-hooks-only-add.md): a hunk that removes Mozilla lines passes only as one of the rewriting forms
(wrap-expression, wrap-call, wrap-function, declared-value, shadow) or as a declared exception with `reason_kind` expression,
declaration, macro or skip. C12: neither. C13: a skip whose removed lines are not all kept verbatim among the added lines. C14: the
rewrite fits wrap-expression (Mozilla's expression intact inside our line, or `||` `&&` `?:` added around it). C15: a parameter
added to a C++ signature or call (an IDL one is a declaration). C12..C15 are never in the debt list and a declared exception does
not leave them out.
Forms the pm ruled in (coord/portabilita-69/design/PM-DECISIONS.md): G1/G2 renames, G15 guards with a
value, G21 shadow, G29 call wrap, G30/G33 anchors at the end, G40 forward declarations. A multi-line Mozilla
expression wrapped (two Mozilla lines, the marker on the first) stays a violation: the pm decides case by case.

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
REWRITE_FORMS = ("wrap-expression", "wrap-call", "wrap-function", "declared-value", "shadow")
REASON_KINDS = ("expression", "declaration", "macro", "skip")
FORMS = ("guard", "notice", "wrap-expression", "wrap-call", "wrap-function", "declared-value", "registration",
         "member", "shadow", "anchor", "unknown")
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
    "C10": "the called function is not named Stealth<What> and is not an existing function (tools/hook-names.json)",
    "C11": "a value of ours in a numbered space of Mozilla",
    "C12": "a rewrite of Mozilla lines that is none of the rewriting forms and has no exception with an allowed reason_kind (port-06)",
    "C13": "a `skip` rewrite whose removed Mozilla lines are not all kept verbatim among the added lines (port-06)",
    "C14": "a rewrite that fits wrap-expression: Mozilla's expression survives intact in our line, or the change adds ||, && or ?: around it (port-06)",
    "C15": "a parameter threaded through a C++ signature or call: carry it by side state, or declare it with reason_kind declaration and say why no side state can (port-06)",
    "C16": "a hook passes a local of Mozilla's function as an argument outside an anchor (hook-02 point 3; read from the lines the hunks show)",
    "T1": "a hook with no test (the `test` of its HOOKS.json entry is empty)",
    "T2": "an anchor hook without its `anchor` and `why` in HOOKS.json",
    "T3": "a hook whose test no round runs (gtest filter of the candidate, node job, python step)",
}
# Rules added after main's debt list was written: main's list has no entry of them yet, so the entries
# they add to the list are not "entries main does not have" (tools/hooks_list.py; remove this once main has them).
INTRODUCED_RULES = {"T1", "T2", "T3"}
# port-06: these rules are fixed by the engine change and the HOOKS.json fields, never by the debt list (debt_problems refuses them)
PORT06_RULES = ("C12", "C13", "C14", "C15", "C16")      # C16 is hook-02 point 3: it is fixed by the hook, never by the debt

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
class Rewrite:
    """port-06: one block of a hunk that removes Mozilla lines (a rewrite, or a deletion when `add` is empty).
    rem / add: the removed lines and the non-blank added lines of the block; hunk_added: every added line of the git hunk
    (a `skip` keeps Mozilla's text among them); is_form: it is one of the rewriting forms (REWRITE_FORMS); hooks: the
    Hook of each added line (the one of a deletion)."""
    folder: str
    file: str
    hunk: int
    function: str
    rem: tuple
    add: tuple
    hunk_added: tuple
    is_form: bool
    hooks: tuple


@dataclass(frozen=True)
class Violation:
    rule: str
    folder: str
    file: str
    function: str
    text: str
    key: str
    detail: str = ""
    ids: tuple = ()        # the identity (hook_identity) of every hook the violation concerns: a declared exception looks here


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
DOC_TYPES = {"md", "rst", "txt"}
PP_FILE_TYPES = {"js", "json", "inc"}       # G50: preprocessed pref files and JSON, where a trailing comment is impossible
PP_DIRECTIVE = re.compile(r"^\s*#\s*(include|if|ifdef|ifndef|else|elif|endif|define|undef|filter|expand)\b")
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
BLOCK_CONTINUATION = re.compile(r"^\*(\s|$)")      # ` * text` inside a block comment; `*aSurface = x;` is code
STEALTH_CALL = re.compile(r"(?:[A-Za-z_]\w*::)*(?:nr_stealth_|Stealth|stealth_)\w*\s*\(")
STEALTH_CHAIN = re.compile(r"(?:[A-Za-z_]\w*::)*(?:nr_stealth_|Stealth|stealth_)\w*")
IDENT = re.compile(r"^[A-Za-z_]\w*$")
FORWARD_DECL = re.compile(r"^(?:class|struct)\s+\w+\s*;$")
OWN_DECL = re.compile(r"^(?:[\w:<>,\[\]]+[\s*&]+)+(?:[A-Za-z_]\w*::)*(?:nr_stealth_|Stealth|stealth_)\w*\s*\([^;{}]*\)\s*(?:const\s*)?;$")
SHADOW = re.compile(r"^(?:const\s+)?(?:auto|[\w:<>,*]+)\s*&?\s*[A-Za-z_]\w*\s*=\s*(?:[A-Za-z_]\w*::)*(?:nr_stealth_|Stealth|stealth_)\w*\s*;$")
CONST_LINE = re.compile(r"^\s*const\s")
NUMBERED = re.compile(r"(=\s*(0x[0-9a-fA-F]+|\d+)\s*;)|(1\s*<<\s*\d+)")


def norm(t: str) -> str:
    return re.sub(r"\s+", "", t)


def _squeeze(t: str) -> str:
    return re.sub(r"\s+", " ", t.strip())


def is_comment_line(t: str, ft: str) -> bool:
    s = t.strip()
    if not s:
        return False
    if s.startswith(("//", "/*", "*/")) or (ft in SLASH_COMMENT and BLOCK_CONTINUATION.match(s)):
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
    cont = re.fullmatch(r"(?:\*/)?\s*\\", post) if opener == "/*" else None
    if cont:       # G2: the marker as a block comment before the backslash of a macro line is the marker on the line
        return (code.strip() + " \\"), m.group(1), extra
    if post not in CLOSERS:
        extra = (extra + " " + post).strip()
    return code.strip(), m.group(1), extra


def calls(code: str) -> list:
    return [c for c in CALL.findall(code) if c.rsplit("::", 1)[-1] not in KEYWORDS and c not in KEYWORDS]


def is_stealth_chain(chain: str) -> bool:
    """`StealthX`, `Class::StealthX`, `ns::Class::StealthX`, `obj->StealthX`: some segment is Stealth-named."""
    return any(STEALTH_NAME.match(seg) for seg in re.split(r"::|\.|->", chain))


MOZILLA_CALLS = {"MOZ_RELEASE_ASSERT", "ABORT", "NS_ENSURE_SUCCESS", "Services.prefs.getBoolPref",
                 "ChromeUtils.importESModule"}
KNOWN_NAMES_FILE = Path(__file__).with_name("hook-names.json")
_known_names = None


def known_names() -> set:
    """G41: the called names of the hooks that existed when the rule came (tools/hook-names.json, written once by
    write_known_names): a function that exists keeps its name, only a new one must be Stealth-named. A name is known
    whole (`nsContentUtils::SessionSystemLocales`) or by its last segment."""
    global _known_names
    if _known_names is None:
        names = json.loads(KNOWN_NAMES_FILE.read_text(encoding="utf-8")) if KNOWN_NAMES_FILE.is_file() else []
        _known_names = set(names) | {re.split(r"::|\.|->", n)[-1] for n in names}
    return _known_names


def is_known_name(chain: str) -> bool:
    names = known_names()
    return chain in names or re.split(r"::|\.|->", chain)[-1] in names


_our_call_re = None


def our_calls(code: str):
    """G41: the calls of `code` to a function of ours, Stealth-named (G29) or an existing one listed in hook-names.json."""
    global _our_call_re
    if _our_call_re is None:
        names = sorted((re.escape(n) for n in known_names() if re.fullmatch(r"\w+", n)), key=len, reverse=True)
        known = (r"|(?:[A-Za-z_]\w*::)*(?<!\w)(?:%s)\s*\(" % "|".join(names)) if names else ""
        _our_call_re = re.compile(STEALTH_CALL.pattern + known)
    return _our_call_re.finditer(code)


def write_known_names(root) -> list:
    """Writes tools/hook-names.json: the non-Stealth names called by the hooks of the series now (the C10 details).
    Run once (G41); a new function is not added to it, it is named Stealth<What>."""
    global _known_names, _our_call_re
    _our_call_re = None
    names = sorted({v.detail for v in _analyse(root)[1] if v.rule == "C10"})
    KNOWN_NAMES_FILE.write_text(json.dumps(names, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="")
    _known_names = None
    return names


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
    at_end = (closing or eof) and ft not in DOC_TYPES      # a Markdown line is not the last line of a block
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


TOKEN = re.compile(r"""\s*("(?:\\.|[^"\\])*"(?:_\w+)?|'(?:\\.|[^'\\])*'|\w+|\S)""")
LITERAL = re.compile(r"""^("|'|\d|true$|false$|nullptr$|null$|None$|True$|False$)""")


def _value_change(removed: str, code: str) -> bool:
    """True if `code` is `removed` with only literals (numbers, strings, true/false) changed."""
    def toks(t):
        return TOKEN.findall(re.sub(r"\s(//|#)\s.*$", "", t.strip()))
    r, c = toks(removed), toks(code)
    return len(r) == len(c) and any(x != y for x, y in zip(r, c)) and \
        all(x == y or (LITERAL.match(x) and LITERAL.match(y)) for x, y in zip(r, c))


def _toks(t: str) -> list:
    return TOKEN.findall(re.sub(r"\s(//|#)\s.*$", "", t.strip()))


LITERAL_AT = {'"': re.compile(r'"(?:\\.|[^"\\])*"'), "'": re.compile(r"'(?:\\.|[^'\\])*'")}


def _close_paren(code: str, o: int) -> int:
    """The index of the `)` that closes the `(` at code[o], or -1; string and character literals are skipped."""
    depth, i, n = 0, o, len(code)
    while i < n:
        ch = code[i]
        if ch in LITERAL_AT:
            m = LITERAL_AT[ch].match(code, i)
            if m:
                i = m.end()
                continue
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                return i if ch == ")" else -1
        i += 1
    return -1


def _arg_starts(code: str, lo: int, hi: int) -> list:
    """The start index of every top-level argument of code[lo:hi] (split at the commas outside brackets and literals)."""
    starts, depth, i = [lo], 0, lo
    while i < hi:
        ch = code[i]
        if ch in LITERAL_AT:
            m = LITERAL_AT[ch].match(code, i)
            if m:
                i = m.end()
                continue
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            starts.append(i + 1)
        i += 1
    return starts


def _wrapped_subexpression(removed: str, code: str):
    """Wrap-expression of a sub-expression: removing our call `StealthX(` / `Ns::StealthX(` / `nr_stealth_x(`, its
    matching `)` and the extra leading arguments inside it (`this, `, parameters) from `code` gives back Mozilla's
    removed line, token for token. -> our call with its extra arguments (what the logic and name rules look at), or None."""
    want = _toks(removed)
    if not want:
        return None
    for m in our_calls(code):
        o = m.end() - 1
        c = _close_paren(code, o)
        if c < 0:
            continue
        for start in _arg_starts(code, o + 1, c):
            if _toks(code[:m.start()] + " " + code[start:c] + " " + code[c + 1:]) == want:
                return code[m.start():o + 1] + code[o + 1:start].rstrip() + ")"
    return None


def _one_identifier_differs(removed: str, code: str):
    """(index, old, new, code tokens) if the two lines have the same tokens but for one identifier, else None."""
    r, c = _toks(removed), _toks(code)
    if len(r) != len(c):
        return None
    diff = [i for i, (x, y) in enumerate(zip(r, c)) if x != y]
    if len(diff) != 1:
        return None
    i = diff[0]
    return (i, r[i], c[i], c) if IDENT.match(r[i]) and IDENT.match(c[i]) else None


def _added_argument(removed: str, code: str):
    """G9: the Stealth name if our line is Mozilla's with exactly one argument of ours, a Stealth call, added to one of
    its calls (first, last or only argument), else None."""
    want = _toks(removed)
    if not want:
        return None
    for m in our_calls(code):
        o = m.end() - 1
        c = _close_paren(code, o)
        if c < 0 or has_logic(code[m.start():c + 1], "cpp"):
            continue
        before, after = code[:m.start()].rstrip(), code[c + 1:].lstrip()
        options = []
        if before.endswith(","):
            options.append((before[:-1], after))              # ..., Stealth(...))
        if after.startswith(","):
            options.append((before, after[1:]))               # (Stealth(...), ...
        if before.endswith("(") and after.startswith(")"):
            options.append((before, after))                   # (Stealth(...))
        for left, right in options:
            if _toks(left + " " + right) == want:
                return m.group(0)[:-1].rstrip()
    return None


def renamed_identifier(removed: str, code: str):
    """G1/G2: the new name if the only token difference between Mozilla's line and ours is one identifier extended by
    a suffix and it is a function or macro (a `(` follows it, or the suffix is `_Mozilla`/`_MOZILLA`), else None."""
    removed = re.sub(r"^(?:(?:static|inline)\s+)+", "", removed.strip())     # a definition made visible to our file
    code = re.sub(r"^(?:(?:static|inline)\s+)+", "", code.strip())
    got = _one_identifier_differs(removed, code)
    if not got:
        return None
    i, old, new, c = got
    if not (new.startswith(old) and len(new) > len(old)):
        return None
    if (i + 1 < len(c) and c[i + 1] == "(") or new.endswith(("_Mozilla", "_MOZILLA")):
        return new
    return None


def called_replacement(removed: str, code: str):
    """G29: the Stealth name if our line is Mozilla's with exactly one called identifier `Foo` replaced by a Stealth-named
    one (`StealthFoo`, `Ns::StealthFoo`, `nr_stealth_foo`), same arguments, else None."""
    r, c = _toks(removed), _toks(code)
    i = 0
    while i < min(len(r), len(c)) and r[i] == c[i]:
        i += 1
    j = 0
    while j < min(len(r), len(c)) - i and r[len(r) - 1 - j] == c[len(c) - 1 - j]:
        j += 1
    mr, mc = r[i:len(r) - j], c[i:len(c) - j]
    if len(mr) != 1 or not IDENT.match(mr[0]) or not mc or not IDENT.match(mc[-1]):
        return None
    if i + 1 >= len(r) or r[i + 1] != "(" or i + len(mc) >= len(c) or c[i + len(mc)] != "(":
        return None
    name = "".join(mc)
    return name if (STEALTH_CHAIN.fullmatch(name) or is_known_name(name)) else None


def called_with_plain_arguments(removed: str, code: str):
    """G29 + G9: the Stealth chain if our line is Mozilla's with the called function replaced by a Stealth-named one of the
    same qualifier and exactly one plain argument of ours (`this`, a member or a parameter) added before or after
    Mozilla's arguments, which stay as they are and in order; the rest of the line identical. Else None."""
    want = removed.strip()
    for rm in CALL.finditer(want):
        r_chain = rm.group(1)
        r_name = re.split(r"::|\.|->", r_chain)[-1]
        ro = rm.end() - 1
        rc = _close_paren(want, ro)
        if rc < 0 or r_name in KEYWORDS or STEALTH_NAME.match(r_name):
            continue
        r_args = _args(want, ro + 1, rc)
        r_prefix = r_chain[:len(r_chain) - len(r_name)]
        for cm in CALL.finditer(code):
            c_chain = cm.group(1)
            c_name = re.split(r"::|\.|->", c_chain)[-1]
            co = cm.end() - 1
            cc = _close_paren(code, co)
            if cc < 0 or not (STEALTH_NAME.match(c_name) or is_known_name(c_name)) or c_chain[:len(c_chain) - len(c_name)] != r_prefix:
                continue
            if _toks(code[:cm.start()]) != _toks(want[:rm.start()]) or _toks(code[cc + 1:]) != _toks(want[rc + 1:]):
                continue
            c_args = _args(code, co + 1, cc)
            m = len(r_args)
            for k in range(0, len(c_args) - m + 1):
                if [_toks(a) for a in c_args[k:k + m]] != [_toks(a) for a in r_args]:
                    continue
                extra = c_args[:k] + c_args[k + m:]
                if len(extra) == 1 and SIMPLE_ARG.match(extra[0]):
                    return c_chain
    return None


SIMPLE_ARG = re.compile(r"^(?:this|[A-Za-z_]\w*(?:(?:->|\.|::)[A-Za-z_]\w*)*)$")


def _args(code: str, lo: int, hi: int) -> list:
    """The top-level arguments of code[lo:hi], stripped ([] for an empty list)."""
    if not code[lo:hi].strip():
        return []
    starts = _arg_starts(code, lo, hi) + [hi + 1]
    return [code[a:b - 1].strip() for a, b in zip(starts, starts[1:])]


def added_leading_argument(removed: str, code: str) -> bool:
    """G9 on one physical line of a call that spans several: Mozilla's line closes or continues the argument list
    (`aLastModified);`), ours is the same with one plain argument of ours in front (`this, aLastModified);`)."""
    r = removed.strip()
    if not r or (r.count(")") <= r.count("(") and not r.endswith(",")):
        return False
    m = re.match(r"^(this|[A-Za-z_]\w*)\s*,\s*(.+)$", code.strip())
    return bool(m) and _toks(m.group(2)) == _toks(r)


MACRO_VALUE = re.compile(r"^[A-Z][A-Z0-9_]*$")
OUR_MACRO = re.compile(r"^STEALTH_[A-Z0-9_]+$")


def declared_by_macro(removed: str, code: str) -> bool:
    """A value of Mozilla's given by a macro of ours: one token of the line, a macro of Mozilla's or a literal, replaced
    one for one by a STEALTH_ macro, the rest of the line identical."""
    r, c = _toks(removed), _toks(code)
    diff = [(x, y) for x, y in zip(r, c) if x != y]
    return len(r) == len(c) and len(diff) == 1 and bool(MACRO_VALUE.match(diff[0][0]) or LITERAL.match(diff[0][0])) and bool(OUR_MACRO.match(diff[0][1]))


def line_form(ft: str, base: str, code: str, removed: str, kind: str, placement: str, pair: bool, renames=()):
    """-> (form, remainder): the form of one added code line. remainder: for wrap-expression, the
    line without Mozilla's expression (what the logic and name rules look at), else the code.
    renames: the new names of the renames of the whole patch (G1): a one-line declaration of one is part of the wrap."""
    if not code or is_comment_line(code, ft):
        return "unknown", code
    if kind == "rewrite":
        if "_Mozilla" in code and re.sub(r"_Mozilla\b", "", norm(code)) == norm(removed or ""):
            return "wrap-function", code
        if removed and renamed_identifier(removed, code):
            return "wrap-function", code
        if pair and removed:
            call = (called_replacement(removed, code) or _added_argument(removed, code)
                    or called_with_plain_arguments(removed, code))
            if call:
                return "wrap-call", call + "()"
            if added_leading_argument(removed, code):
                return "wrap-call", ""
            if declared_by_macro(removed, code):
                return "declared-value", ""
            got = _mozilla_expression(removed, code)
            if got and got[1].strip() not in ("", ";") and calls(got[1]):
                return "wrap-expression", got[1]
            sub = _wrapped_subexpression(removed, code)
            if sub:
                return "wrap-expression", sub
            if _value_change(removed, code):
                # logic is judged in the part that is ours: the values that changed, not Mozilla's own text around them
                r, c = _toks(removed), _toks(code)
                return "declared-value", " ".join(y for x, y in zip(r, c) if x != y)
        return "unknown", code
    if is_include(code) or (ft in PP_FILE_TYPES and PP_DIRECTIVE.match(code)):
        return "registration", code
    if ft in ("ipdl", "ipdlh", "webidl") or base in ("components.conf", "jar.mn"):
        return "registration", code
    if ft == "build":
        return ("registration" if BUILD_ADD.match(code) else "unknown"), code
    if ft in CLIKE and (FORWARD_DECL.match(code) or (placement == "file_scope" and OWN_DECL.match(code))):
        return "registration", code
    if "_Mozilla" in code and ft in HEADERS and code.rstrip().endswith(";"):
        return "wrap-function", code
    if ft in HEADERS and code.rstrip().endswith(";") and any(re.search(r"\b%s\s*\(" % re.escape(n), code) for n in renames):
        return "wrap-function", code
    if ft in CLIKE and placement == "function_top" and SHADOW.match(code):
        return "shadow", code
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


INCOMPLETE_CONTROL = re.compile(r"^(?:\}\s*)?(?:else(?:\s+if\s*\(.*\))?|if\s*\(.*\)|for\s*\(.*\)|while\s*\(.*\)|do|try)$")


def _balanced(code: str) -> bool:
    depth = 0
    for ch in _strip_literals(code):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _complete(ft: str, code: str) -> bool:
    """A complete statement or declaration on one line: brackets closed, not ending on an operator, a comma or an
    opening, not a bare `if (...)` / `else` that waits for its statement."""
    c = code.strip()
    if not c or not _balanced(c) or c[-1] in ",(+-*/&|=?:\\.<":
        return False
    return not INCOMPLETE_CONTROL.match(c)


def _marker_before_directive(ft: str, run: list, codes: list) -> bool:
    """G50: in a preprocessed pref file or a JSON file a marker comment alone on the line immediately before a
    preprocessor directive line (`#include init/StealthPrefs.js`) forms one hook with it."""
    return (ft in PP_FILE_TYPES and len(run) == 2 and codes[0][0] == "" and codes[0][1] is not None and not codes[0][2]
            and bool(PP_DIRECTIVE.match(codes[1][0])) and codes[1][1] is None and run[1][0] == run[0][0] + 1)


def _own_line(ft: str, code: str, marker) -> bool:
    """A line of a run that is a hook by itself: an include / moz.build addition, or a marked complete statement."""
    return _is_multi_ok(ft, code) or (marker is not None and _complete(ft, code))


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


def _closes_wrap(removed: str, code: str) -> bool:
    """Our line is Mozilla's closing line with exactly one more `)` (the one that closes our opened call), nothing else."""
    r, c = _toks(removed), _toks(code)
    return len(c) == len(r) + 1 and any(t == ")" and c[:k] + c[k + 1:] == r for k, t in enumerate(c))


def _wrap_roles(ft: str, hunks_blocks: list) -> dict:
    """G53: a multi-line expression wrap. One line of ours is ADDED to open our call (`StealthX(a,  // STEALTH-HOOK(f)`,
    marker on it), Mozilla's expression lines in between stay as they are (context), and only the closing line is
    rewritten: Mozilla's closing text plus our `)` and the marker. `hunks_blocks` is the list of blocks of every hunk of
    one file: the two ends may fall in two hunks (git cuts a hunk when the lines between are far apart), and they are
    paired only when they are consecutive changes of the file, so every line between them is Mozilla's, unchanged.
    -> {(hunk index, block index): "open" | "close"}. A wrap where a middle line changes (another block between the
    two, in this hunk or in one between) or where a line lacks the marker is not recognised."""
    roles = {}
    if ft not in CLIKE:
        return roles
    flat = [(hi, bi, b) for hi, blocks in enumerate(hunks_blocks) for bi, b in enumerate(blocks)]
    for i in range(len(flat) - 1):
        (ha, ba, a), (hz, bz, z) = flat[i], flat[i + 1]
        if a["rem"] or len(a["add"]) != 1 or len(z["rem"]) != 1 or len(z["add"]) != 1 or (ha, ba) in roles:
            continue
        o_code, o_mk, o_extra = marker_split(a["add"][0].rstrip())
        c_code, c_mk, c_extra = marker_split(z["add"][0].rstrip())
        if o_mk is None or c_mk is None or o_extra or c_extra or is_comment_line(a["add"][0], ft):
            continue
        m = STEALTH_CALL.match(o_code)
        if not m or _close_paren(o_code, m.end() - 1) >= 0 or not _balanced_open_one(o_code):
            continue
        if _closes_wrap(z["rem"][0], c_code):
            roles[(ha, ba)], roles[(hz, bz)] = "open", "close"
    return roles


def _balanced_open_one(code: str) -> bool:
    """The brackets of `code` leave exactly one `(` open."""
    depth = 0
    for ch in _strip_literals(code):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
    return depth == 1


def hook_identity(h: Hook) -> tuple:
    """The identity of a hook (the one of its HOOKS.json entry): file, function, kind, line, removed line."""
    return (h.file, _squeeze(h.function), h.kind, norm(h.line), norm(h.removed))


def _renames(files: list) -> set:
    """G1: the new names of every rewrite pair of the patch that is a rename (`Foo` -> `Foo_Mozilla`, `GetX` ->
    `GetXAsDrawn`): the one-line declarations of these names, added in a header, are part of the same wrap."""
    names = set()
    for f in files:
        for h in f["hunks"]:
            for b in _blocks(h["lines"]):
                add = [marker_split(x.rstrip())[0] for x in b["add"] if x.strip()]
                if b["rem"] and len(b["rem"]) == len(add):
                    for r, a in zip(b["rem"], add):
                        n = renamed_identifier(r, a)
                        if n:
                            names.add(n)
    return names


def analyse_patch(folder: str, text: str):
    """-> (hooks, violations) of one hooks.patch (folder: its series folder). Does not look at
    BACKPORT.json: series_hooks skips those folders."""
    hooks, found, _ = _analyse_patch(folder, text)
    return hooks, found


def _analyse_patch(folder: str, text: str):
    """-> (hooks, violations, rewrites): the same, and every block that removes Mozilla lines (port-06)."""
    hooks, found, rewrites = [], [], []

    def violate(rule, file, function, txt, detail="", hs=()):
        found.append(Violation(rule, folder, file, function, txt, _key(rule, folder, file, function, txt), detail,
                               tuple(hook_identity(h) for h in hs)))

    parsed = parse_patch(text)
    renames = _renames(parsed)
    for f in parsed:
        path, ft = f["file"], file_type_of(f["file"])
        base = path.rsplit("/", 1)[-1]
        whole = _whole_file(f)
        if whole:
            hooks.append(Hook(folder, path, "", "unknown", "", "<%s file>" % whole, "file", "unknown"))
            violate("C7", path, "", "<%s>" % whole, whole, hooks[-1:])
            continue
        file_blocks = [_blocks(h["lines"]) for h in f["hunks"]]
        file_roles = _wrap_roles(ft, file_blocks)
        for hno, h in enumerate(f["hunks"], 1):
            lines, section = h["lines"], h["section"]
            new_side = [(t, x) for t, x in lines if t != "-"]
            blocks = file_blocks[hno - 1]
            for bi, b in enumerate(blocks):
                role = file_roles.get((hno - 1, bi))
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
                            "%d Mozilla lines removed" % len(rem), hooks[-1:])
                    rewrites.append(Rewrite(folder, path, hno, section, tuple(rem), (), tuple(x for t, x in lines if t == "+"),
                                            False, tuple(hooks[-1:])))
                    continue
                nonblank = [(i, x.rstrip()) for i, x in enumerate(add) if x.strip()]
                paired = bool(rem) and len(rem) == len(nonblank)       # a rewrite line for line
                single_pair = paired and len(rem) == 1
                forms, nb, block_hooks = [], 0, []
                for run in _runs(nonblank):
                    codes = [marker_split(x) for _, x in run]
                    if _marker_before_directive(ft, run, codes):
                        # G50: the marker alone on the line before the directive is the marker of the directive: one hook
                        run, codes = [run[1]], [(codes[1][0], codes[0][1], codes[1][2])]
                    run_text = "\n".join(x for _, x in run)
                    # one hook = one line, but two adjacent lines are two hooks when each has its marker and is complete
                    multi_ok = all(_own_line(ft, c, mk) for c, mk, _ in codes)
                    run_forms, run_hooks = [], []
                    for j, (i, x) in enumerate(run):
                        code, mk, extra = codes[j]
                        rm = ""
                        if kind == "rewrite":
                            rm = rem[nb] if paired else ("\n".join(rem) if nb == 0 else "")
                        nb += 1
                        form, remainder = line_form(ft, base, code, rm, kind, placement, single_pair, renames)
                        if role:            # G53: the two ends of a multi-line wrap of Mozilla's expression
                            form, remainder = "wrap-expression", (code if role == "open" else ")")
                        if len(run) > 1 and not multi_ok:        # a form is the form of a one-line hook
                            form, remainder = "unknown", code
                        run_forms.append((form, remainder))
                        hk = Hook(folder, path, section, form, x, rm, kind, placement, len(run), j, mk, hno)
                        hooks.append(hk)
                        run_hooks.append(hk)
                        block_hooks.append(hk)
                        if mk is not None and extra:
                            violate("C3", path, section, x, extra, [hk])
                        if is_comment_line(x, ft):
                            violate("C4", path, section, x, "", [hk])
                        if ft in IDL and NUMBERED.search(x) and not is_comment_line(x, ft) and not (
                                ft == "webidl" and not CONST_LINE.match(x)):   # a dictionary member's default is no numbered space
                            violate("C11", path, section, x, "", [hk])
                        if kind == "add" and is_include(code):
                            at = b["ns"] + i
                            before = new_side[at - 1] if at >= 1 else None
                            after = new_side[at + 1] if at + 1 < len(new_side) else None
                            if (before and before[0] == " " and is_include(before[1])) or                                (after and after[0] == " " and is_include(after[1])):
                                violate("C8", path, section, x, "", [hk])
                    forms += [f_ for f_, _ in run_forms]
                    if len(run) > 1 and not multi_ok:
                        violate("C1", path, section, run_text, "%d lines" % len(run), run_hooks)
                    if not any(mk is not None for _, mk, _ in codes) and not all(is_include(c) for c, _, _ in codes):
                        violate("C2", path, section, run_text, "", run_hooks)
                    for (form, remainder), hk, (_, x) in zip(run_forms, run_hooks, run) if multi_ok else ():
                        if (form in ("guard", "notice", "anchor", "wrap-expression", "declared-value")
                                or (form == "unknown" and any(is_stealth_chain(c) for c in calls(remainder))))                                 and has_logic(remainder, ft):
                            violate("C5", path, section, x, "", [hk])
                        if form in ("guard", "notice", "anchor", "wrap-expression"):
                            # C10 is about the function of ours a hook calls: Mozilla's own macros and APIs are not read as it
                            cs = [c for c in calls(remainder) if c not in MOZILLA_CALLS]
                            if cs and not is_stealth_chain(cs[0]) and not is_known_name(cs[0]):
                                violate("C10", path, section, x, cs[0], [hk])
                add_text = "\n".join(x for _, x in nonblank)
                if rem:
                    is_form = bool(single_pair and forms and forms[0] in REWRITE_FORMS)
                    rewrites.append(Rewrite(folder, path, hno, section, tuple(rem), tuple(x for _, x in nonblank),
                                            tuple(x for t, x in lines if t == "+"), is_form, tuple(block_hooks)))
                    if not is_form:
                        violate("C6", path, section, "-" + "\n-".join(x.strip() for x in rem) + "\n" + add_text,
                                "%d Mozilla lines removed, %d added" % (len(rem), len(nonblank)), block_hooks)
                elif nonblank:
                    all_inc = all(is_include(marker_split(x)[0]) for _, x in nonblank)
                    # G30/G33: an anchor on the last line of a block or of a JS module is allowed (T2 asks for its why)
                    end_anchor = placement == "end_of_block" and bool(forms) and all(f_ == "anchor" for f_ in forms)
                    if not role and not all_inc and not end_anchor and not all(f_ == "wrap-function" for f_ in forms) and (
                            placement in ("list_entry", "end_of_block")
                            or (at_end and placement not in ("include_block", "build_file"))):
                        violate("C9", path, section, add_text, "placement=%s at_block_end=%s" % (placement, at_end), block_hooks)
    return hooks, _unique(found), rewrites


def _unique(found: list) -> list:
    """Two identical hooks in one function share a key: the second gets `#2`, and so on."""
    seen, out = {}, []
    for v in found:
        n = seen.get(v.key, 0) + 1
        seen[v.key] = n
        out.append(v if n == 1 else Violation(v.rule, v.folder, v.file, v.function, v.text, "%s#%d" % (v.key, n), v.detail, v.ids))
    return out


# --------------------------------------------------------------------------- port-06: a rewrite needs a reason that holds
# A hunk adds lines in one of the fixed forms. A rewrite of Mozilla text outside the rewriting forms (REWRITE_FORMS) is allowed
# only as a declared exception (G35) whose `reason_kind` is one of REASON_KINDS, and only where no form can carry the value:
#   expression   a value inside an expression Mozilla builds
#   declaration  a signature or declaration (an IDL parameter); a C++ one only when the exception says why no side state can carry it
#   macro        a preprocessor condition or macro (an `#if` rewrite)
#   skip         Mozilla's statements must not run; every removed line stays verbatim among the added ones
# C12 no allowed exception; C13 a skip that does not keep Mozilla's lines verbatim; C14 the rewrite fits wrap-expression;
# C15 a parameter threaded through a C++ signature or call (a thread-local or a member of our side object carries it instead).
C_FAMILY = {"cpp", "cc", "c", "h", "hpp", "mm", "m"}
SIDE_STATE = re.compile(r"side[\s-]+state", re.I)
DIRECTIVE_LINE = re.compile(r"^\s*#")


def _is_exception_entry(e) -> bool:
    """G35: an entry with the reason (`exception`) and the pm's approval (tools/hooks_list.py is_declared_exception)."""
    return bool(e) and isinstance(e.get("exception"), str) and bool(e["exception"].strip()) and e.get("pm") == "approvato"


def _code_of(line: str) -> str:
    return marker_split(line.rstrip())[0]


def _preprocessor_only(rem: tuple) -> bool:
    lines = [x for x in rem if x.strip()]
    return bool(lines) and all(DIRECTIVE_LINE.match(x) for x in lines)


def _significant(t: list) -> list:
    """The tokens of a removed text without its closing `;`, `{`, `,`: what Mozilla's expression is."""
    t = list(t)
    while t and t[-1] in (";", "{", ","):
        t.pop()
    return t


def _find_run(needle: list, hay: list) -> int:
    """The index where `needle` occurs as a contiguous run of `hay`, or -1."""
    n = len(needle)
    for k in range(len(hay) - n + 1):
        if hay[k:k + n] == needle:
            return k
    return -1


def _insertions(rem_t: list, add_t: list):
    """Matches the tokens of the removed text as a subsequence of the added ones (leftmost). -> None if it is not one, else
    the list of insertions (previous matched token or None, tokens inserted, next matched token or None)."""
    i, matched = 0, []
    for k, t in enumerate(add_t):
        if i < len(rem_t) and t == rem_t[i]:
            matched.append(k)
            i += 1
    if i < len(rem_t):
        return None
    out, prev = [], -1
    for m in matched + [len(add_t)]:
        if m - prev > 1:
            out.append((add_t[prev] if prev >= 0 else None, add_t[prev + 1:m], add_t[m] if m < len(add_t) else None))
        prev = m
    return out


QUALIFIERS = {"const", "volatile", "noexcept", "override", "final", "operator"}


def _logic_ops(seg: list, prev=None, nxt=None) -> set:
    """The `&&`, `||` and `?` of a token segment (the tokenizer cuts operators into single characters). An `&&` after a type
    qualifier or in front of `=` is an rvalue reference (`const&& = delete`), not a logical and."""
    ops = {"?"} if "?" in seg else set()
    ctx = [prev] + list(seg) + [nxt]
    for i in range(1, len(ctx) - 2):
        if ctx[i] == ctx[i + 1] and ctx[i] in ("&", "|"):
            before, after = ctx[i - 1], ctx[i + 2]
            operand_end = before is not None and (before in (")", "]") or (re.match(r"\w", before) and before not in QUALIFIERS))
            operand_start = after is not None and (re.match(r"[\w!(~*\-+]", after) is not None)
            if operand_end and operand_start:
                ops.add(ctx[i] * 2)
    return ops


def _depth0_comma(seg: list) -> bool:
    """A comma of the segment outside every bracket: it separates the arguments or parameters the segment adds."""
    depth = 0
    for t in seg:
        if t in ("(", "[", "{", "<"):
            depth += 1
        elif t in (")", "]", "}", ">"):
            depth -= 1
        elif t == "," and depth == 0:
            return True
    return False


def _is_parameter(prev, seg: list, nxt) -> bool:
    """An inserted segment between two matched tokens that adds an argument or a parameter to a list."""
    if prev is None or nxt is None or any(t in (";", "{", "}") for t in seg):
        return False
    ops = _logic_ops(seg, prev, nxt)
    if _depth0_comma(seg):
        return not (ops & {"?", "||"})
    return prev in ("(", ",") and nxt in (")", ",") and not ops


def _rewrite_tokens(r: Rewrite):
    rem_t = _toks(" ".join(x.strip() for x in r.rem))
    add_t = _toks(" ".join(_code_of(x).strip() for x in r.add))
    return rem_t, add_t


def _verbatim_lines(r: Rewrite) -> set:
    return {norm(_code_of(x)) for x in r.hunk_added if x.strip()}


def _own_line_kept(r: Rewrite) -> bool:
    """Every removed line is kept as a whole added line (a skip's shape, not a wrap)."""
    kept = _verbatim_lines(r)
    real = [x for x in r.rem if len(_toks(x)) >= 3]
    return bool(real) and all(norm(x) in kept for x in real)


def rule_c12(r: Rewrite, entry, problem: str = ""):
    """C12: the rewrite is none of the forms and no declared exception with an allowed reason_kind covers it. -> detail or None."""
    if r.is_form or entry is not None:
        return None
    return problem or ("a rewrite of Mozilla lines with no exception: write it as one of the forms, or declare it in HOOKS.json "
                       "(`exception`, `reason_kind` in %s, `pm`)" % "/".join(REASON_KINDS))


def rule_c13(r: Rewrite, entry):
    """C13: a `skip` keeps every removed Mozilla line verbatim (whitespace aside) among the lines of its hunk. -> detail or None."""
    if r.is_form or entry is None or entry.get("reason_kind") != "skip":
        return None
    kept = _verbatim_lines(r)
    lost = [x.strip() for x in r.rem if x.strip() and norm(x) not in kept]
    if lost:
        return "skip: the Mozilla line `%s` is not kept verbatim among the added lines: keep it, inside our guard" % _squeeze(lost[0])[:100]
    return None


def rule_c14(r: Rewrite, entry):
    """C14: the rewrite fits wrap-expression: (i) Mozilla's expression survives intact inside one of our lines, so it is a wrap
    and is declared as one; (ii) the change adds `||`, `&&` or `?:` around Mozilla's expression. A skip is neither (it keeps
    Mozilla's text as whole lines, not evaluated), and a preprocessor line cannot be wrapped. -> detail or None."""
    if (r.is_form or (entry or {}).get("reason_kind") == "skip" or not r.add or _preprocessor_only(r.rem)
            or file_type_of(r.file) in IDL):         # `Foo?` and `[A, B]` of an IDL are not expressions
        return None
    rem_t, add_t = _rewrite_tokens(r)
    sig = _significant(rem_t)
    if len(sig) < 3 or len(add_t) <= len(sig):
        return None
    # the lines of the block read as one: the recogniser of the one-line forms, on a block that spans several lines
    form, _ = line_form(file_type_of(r.file), r.file.rsplit("/", 1)[-1], " ".join(_code_of(x).strip() for x in r.add),
                        " ".join(x.strip() for x in r.rem), "rewrite", "mid_function", True)
    if form in ("wrap-expression", "wrap-call") and not _own_line_kept(r):
        return ("(i) Mozilla's expression `%s` survives intact inside our line: it is a %s, declare it as one (the "
                "extra leading arguments and our call go around it)" % (_squeeze(" ".join(r.rem))[:90], form))
    k = _find_run(sig, add_t)
    if k >= 0 and not _own_line_kept(r) and calls(" ".join(add_t[:k] + add_t[k + len(sig):])):
        return ("(i) Mozilla's expression `%s` survives intact inside our line: it is a wrap-expression, declare it as one (the "
                "extra leading arguments and our call go around it)" % _squeeze(" ".join(r.rem))[:90])
    ins = _insertions(sig, add_t)
    if ins is not None:
        ops = sorted({o for prev, seg, nxt in ins if not _depth0_comma(seg) for o in _logic_ops(seg, prev, nxt)})
        if ops:
            return ("(ii) the change adds `%s` around Mozilla's expression: wrap-expression fits, our call decides inside the "
                    "expression" % "`, `".join(ops))
    return None


def rule_c15(r: Rewrite, entry):
    """C15: (iii) a parameter added to a C++ signature or call that is not IDL, IPDL or WebIDL: parameter threading. It is
    refused unless reason_kind is `declaration` and the exception names why no side state can carry it. -> detail or None."""
    if r.is_form or (entry or {}).get("reason_kind") == "skip" or not r.add or _preprocessor_only(r.rem):
        return None
    if file_type_of(r.file) not in C_FAMILY:
        return None
    rem_t, add_t = _rewrite_tokens(r)
    sig = _significant(rem_t)
    if len(sig) < 2:
        return None
    ins = _insertions(sig, add_t)
    if not ins:
        return None
    if not any(_is_parameter(prev, seg, nxt) for prev, seg, nxt in ins):
        return None
    if (entry or {}).get("reason_kind") == "declaration" and SIDE_STATE.search(entry.get("exception", "")):
        return None
    return ("(iii) a parameter is added to a C++ signature or call: carry it by our own state set by a guard at the entry "
            "(a thread-local, or a member of our side object); otherwise declare it with reason_kind declaration and an "
            "exception that says why no side state can carry it")


def _exception_of(r: Rewrite, by_identity: dict):
    """-> (entry or None, problem): the declared exception of the hooks of the block with an allowed reason_kind."""
    declared = []
    for hk in r.hooks:
        for e in by_identity.get(hook_identity(hk), ()):
            if _is_exception_entry(e):
                declared.append(e)
    if not declared:
        return None, ""
    for e in declared:
        if e.get("reason_kind") in REASON_KINDS:
            if e["reason_kind"] == "macro" and not (_preprocessor_only(r.rem) or any(x.rstrip().endswith("\\") for x in r.rem)):
                return None, ("reason_kind macro, but no removed line is a preprocessor line or a macro line: a value inside an "
                              "expression is `expression`")
            return e, ""
    return None, ("the exception has no `reason_kind`, or not one of %s (got %r)"
                  % ("/".join(REASON_KINDS), declared[0].get("reason_kind")))


def analyse_rewrites(folder: str, text: str, entries=()) -> list:
    """port-06: the C12..C15 violations of one hooks.patch; `entries` are the HOOKS.json entries of the folder (their hand fields
    `exception`, `reason_kind`, `pm` are what a rewrite is judged by). Each rule is a function of the block and its exception."""
    by_identity = {}
    for e in entries:
        if isinstance(e, dict) and all(k in e for k in ("file", "function", "kind", "line")):
            key = (e["file"], _squeeze(e["function"]), e["kind"], norm(e["line"]), norm(e.get("removed", "")))
            by_identity.setdefault(key, []).append(e)
    found = []
    for r in _analyse_patch(folder, text)[2]:
        if r.is_form:
            continue
        entry, problem = _exception_of(r, by_identity)
        txt = "-" + "\n-".join(x.strip() for x in r.rem) + "\n" + "\n".join(x for x in r.add)
        for rule, detail in (("C12", rule_c12(r, entry, problem)), ("C13", rule_c13(r, entry)),
                             ("C14", rule_c14(r, entry)), ("C15", rule_c15(r, entry))):
            if detail:
                found.append(Violation(rule, folder, r.file, r.function, txt, _key(rule, folder, r.file, r.function, txt), detail,
                                       tuple(hook_identity(h) for h in r.hooks)))
    return _unique(found)


def rewrite_violations(root) -> list:
    """port-06: the C12..C15 violations of every non-backport folder, judged with the committed HOOKS.json hand fields."""
    import hooks_list
    root, found = Path(root), []
    for folder in _folders(root):
        found += analyse_rewrites(folder, (root / folder / "hooks.patch").read_text(encoding="utf-8", errors="replace"),
                                  hooks_list.expected(root, folder))
    return found


# --------------------------------------------------------------------------- hook-02 point 3: no local of Mozilla's function as an argument
# A hook passes `this`, the function's parameters or the wrapped expression, never a local of Mozilla's function (a local
# names a statement Mozilla may move or rename at the next tag); only an anchor may. C16 reads the declaration of a local
# from the lines the hunks show of the function (context, removed and added lines of every hunk with the same host function);
# what it cannot see is a local declared in lines the diff does not show (a hunk's 3 lines of context are all it has), a
# parameter hidden behind a macro, and a local declared by a statement the declaration patterns do not read.
NOT_A_DECLARATION = {"return", "else", "delete", "throw", "goto", "case", "new", "co_return", "using", "typedef", "namespace",
                     "class", "struct", "enum", "union", "public", "private", "protected", "template", "default", "do"}
NOT_AN_ARGUMENT = KEYWORDS | NOT_A_DECLARATION | {"this", "true", "false", "nullptr", "null", "NULL", "None", "True", "False",
                                                  "const", "auto", "bool", "int", "void", "char", "unsigned", "static"}
_TYPE = r"(?:[A-Za-z_][\w:]*(?:<[^;=()]*>)?(?:\s*[*&]+\s*|\s+))+"
LOCAL_DECL_C = (
    re.compile(r"^(?:(?:const|static|constexpr|volatile|mutable|thread_local)\s+)*" + _TYPE + r"([A-Za-z_]\w*)\s*(?:=|\(|\{|;|\[)"),
    re.compile(r"\bfor\s*\(\s*(?:const\s+)?" + _TYPE + r"([A-Za-z_]\w*)\s*[:=]"),
    re.compile(r"\b(?:if|while|switch)\s*\(\s*(?:const\s+)?" + _TYPE + r"([A-Za-z_]\w*)\s*="),
)
LOCAL_DECL_JS = re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)")
LOCALS_FILES = {"cpp", "cc", "c", "mm", "m", "js", "mjs", "jsm", "jsx", "ts"}        # not headers (members and parameters), not rust
TYPE_WORDS = {"bool", "int", "auto", "void", "char", "unsigned", "const"}
EXEMPT_FOR_LOCALS = ("anchor", "registration", "member", "shadow")


def declared_locals(ft: str, lines) -> set:
    """The names a function's visible lines declare as locals (C++: `Type name = ..;`, `Type name(..);`, a range-for, an
    `if (Type name = ..)`; js: const/let/var; rust: let). Signature lines and lines at column 0 are not declarations."""
    names = set()
    for raw in lines:
        if not raw.strip() or is_comment_line(raw, ft) or indent_of(raw) == 0 or raw.lstrip().startswith("#"):
            continue
        s = _strip_literals(marker_split(raw)[0]).strip()
        if ft in ("js", "mjs", "jsm", "jsx", "ts"):
            m = LOCAL_DECL_JS.search(s)
            if m:
                names.add(m.group(1))
            continue
        if ft not in C_FAMILY:
            continue
        first = re.match(r"[A-Za-z_]\w*", s)
        for k, rx in enumerate(LOCAL_DECL_C):
            m = rx.search(s) if k else rx.match(s)
            if not m or (k == 0 and (first is None or first.group(0) in NOT_A_DECLARATION)):
                continue
            if k == 0 and s.endswith("{") and "=" not in s:        # a signature or a block opener, not a declaration
                continue
            names.add(m.group(1))
    return names


def _ours(rem_t: list, add_t: list) -> list:
    """The indexes of `add_t` that are ours: every token of an added line, and for a rewrite the tokens Mozilla's removed
    text does not have (the inserted and the replaced ones)."""
    if not rem_t:
        return list(range(len(add_t)))
    import difflib
    out = []
    for tag, _, _, j1, j2 in difflib.SequenceMatcher(None, rem_t, add_t, autojunk=False).get_opcodes():
        if tag in ("insert", "replace"):
            out += list(range(j1, j2))
    return out


def _passed_identifiers(add_t: list, ours: list) -> list:
    """The names among our tokens that read as a value passed or used by the hook: not a called name, a member, a qualified
    name, a keyword, a literal, nor the name a declaration of the hook itself introduces."""
    found = []
    for k in ours:
        t = add_t[k]
        if not IDENT.match(t) or t in NOT_AN_ARGUMENT:
            continue
        prev, prev2 = (add_t[k - 1] if k >= 1 else ""), (add_t[k - 2] if k >= 2 else "")
        if prev == "." or (prev == ">" and prev2 == "-") or (prev == ":" and prev2 == ":"):
            continue
        nxt, nxt2 = (add_t[k + 1] if k + 1 < len(add_t) else ""), (add_t[k + 2] if k + 2 < len(add_t) else "")
        if nxt == "(" or nxt == "." or (nxt == "-" and nxt2 == ">") or (nxt == "=" and nxt2 != "="):
            continue                                # a called name, a receiver, the target of an assignment: not passed
        declares = (IDENT.match(prev) and (prev not in NOT_AN_ARGUMENT or prev in TYPE_WORDS)) or (
            prev in ("*", "&") and IDENT.match(prev2) and k + 1 < len(add_t) and add_t[k + 1] in ("=", ";"))
        if declares:
            continue                                # `bool stealthPlaced = ..`: the hook declares it
        if t not in found:
            found.append(t)
    return found


MOZILLA_NOT_LOCAL = re.compile(r"^(?:m|s|g|k|a)[A-Z]")        # member, static, global, constant, parameter: Mozilla's naming


def _function_lines(base: list, old_start: int):
    """(signature names, body lines) of the function of the base file that holds old line `old_start`, or None: the nearest
    column-0 line above is the header (a column-0 `}` first means the line is not inside a function), the body runs to the
    next column-0 `}`."""
    i = min(old_start, len(base)) - 1
    while i >= 0:
        ln = base[i]
        if ln.strip() and indent_of(ln) == 0 and not ln.lstrip().startswith(("#", "//", "/*", "*")):
            if ln.startswith("}"):
                return None
            break
        i -= 1
    else:
        return None
    head, j = [], i
    while j < len(base) and not base[j].rstrip().endswith("{") and j < i + 12:
        head.append(base[j])
        j += 1
    head.append(base[j] if j < len(base) else "")
    end = j + 1
    while end < len(base) and not base[end].startswith("}"):
        end += 1
    return set(re.findall(r"[A-Za-z_]\w*", " ".join(head))), base[j + 1:end]


def git_base_reader(source, tag: str):
    """A `base` for analyse_locals: the lines of a Mozilla file at `tag` in the repository `source` (None when it has none)."""
    import subprocess
    cache = {}

    def read(path: str):
        if path not in cache:
            got = subprocess.run(["git", "-C", str(source), "show", "%s:%s" % (tag, path)], capture_output=True)
            cache[path] = got.stdout.decode("utf-8", errors="replace").split(chr(10)) if got.returncode == 0 else None
        return cache[path]
    return read


def analyse_locals(folder: str, text: str, base=None) -> list:
    """C16 of one hooks.patch: every hook that is not an anchor (nor a registration, member or shadow) and passes a local of
    Mozilla's function. The locals are read from the lines the hunks show of the function; with `base` (a function from a
    Mozilla path to the lines of the file at the tag, see git_base_reader) from the whole function in the base file too.
    Header files and rust are not read (their indented lines are members and parameters; rust declares with `let`)."""
    hooks, _, rewrites = _analyse_patch(folder, text)
    out = []
    for f in parse_patch(text):
        path, ft = f["file"], file_type_of(f["file"])
        if ft not in LOCALS_FILES or _whole_file(f):
            continue
        base_lines = base(path) if base else None
        by_fn = {}
        for h in f["hunks"]:
            by_fn.setdefault(h["section"], []).append(h)
        # new-file line number of each added line: (hunk number, text) -> [numbers]
        at = {}
        for hno, h in enumerate(f["hunks"], 1):
            n = h["new_start"]
            for tag, x in h["lines"]:
                if tag != "-":
                    if tag == "+":
                        at.setdefault((hno, norm(x)), []).append(n)
                    n += 1
        locals_of = {}
        for section, hs in by_fn.items():
            names = declared_locals(ft, [x for h in hs for _, x in h["lines"]])
            names -= set(re.findall(r"[A-Za-z_]\w*", section))          # a parameter named in the host function
            locals_of[section] = names
        units = [(r.hunk, r.function, r.rem, r.add, r.hooks) for r in rewrites if r.file == path and r.add]
        units += [(h.hunk, h.function, (), (h.line,), (h,)) for h in hooks if h.file == path and h.kind == "add" and h.line]
        for hno, section, rem, add, hks in units:
            live = [h for h in hks if h.form not in EXEMPT_FOR_LOCALS]
            if not live:
                continue
            visible, params = set(locals_of.get(section, ())), set()
            fn = _function_lines(base_lines, f["hunks"][hno - 1]["old_start"]) if base_lines else None
            if fn:
                params, body = fn
                visible |= declared_locals(ft, body)
            visible = {n for n in visible if n not in params and not MOZILLA_NOT_LOCAL.match(n)}
            visible -= declared_locals(ft, list(add))            # a name the hook itself declares is its own
            add_t = _toks(" ".join(_code_of(x).strip() for x in add))
            rem_t = _toks(" ".join(x.strip() for x in rem)) if rem else []
            names = [n for n in _passed_identifiers(add_t, _ours(rem_t, add_t)) if n in visible]
            if not names:
                continue
            head = live[0]
            line = (at.get((hno, norm(head.line))) or [0])[0]
            txt = "\n".join(x for x in add) if rem else head.line
            out.append(Violation("C16", folder, path, section, txt, _key("C16", folder, path, section, txt),
                                 "line %d: %s" % (line, ", ".join(names)), tuple(hook_identity(h) for h in hks)))
    return _unique(out)


def locals_violations(root, base=None) -> list:
    """C16 of every non-backport folder (`base`: see analyse_locals)."""
    root, found = Path(root), []
    for folder in _folders(root):
        found += analyse_locals(folder, (root / folder / "hooks.patch").read_text(encoding="utf-8", errors="replace"), base)
    return found


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
    """Every rule the series breaks now, ordered by key. See the module's rules C1..C11, T1..T3. The violations of a
    declared exception (G35: HOOKS.json entry with `exception` and `pm: "approvato"`) are left out: a violation is
    left out when every hook it concerns is one."""
    import hooks_list      # imports this module: loaded here, not at the top
    excepted = {(folder, hooks_list.identity(e)) for folder, e in hooks_list.declared_exceptions(Path(root))}
    anchored = {(folder, hooks_list.identity(e)) for folder in hooks_list.folders(Path(root))
                for e in hooks_list.expected(Path(root), folder) if e.get("anchor") and e.get("why")}

    def end_anchor(v):      # G23/G30/G33: the last statement of a block, declared with its `anchor` and `why`
        return (v.rule == "C9" and bool(v.ids) and re.search(r"placement=(end_of_block|function_top)", v.detail) is not None
                and all((v.folder, i) in anchored for i in v.ids))

    kept = [v for v in _analyse(root)[1]
            if not (v.ids and all((v.folder, i) in excepted for i in v.ids)) and not end_anchor(v)]
    # port-06: a declared exception does not leave these out; they judge the exception itself
    return sorted(kept + hooks_list.missing_test_violations(root) + rewrite_violations(root)
                  + locals_violations(root), key=lambda v: v.key)


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
        return [entry_of(v) for v in violations if v.rule not in PORT06_RULES]
    now = {v.key for v in violations}
    return [e for e in entries if e["key"] in now]


def debt_problems(violations: list, debt: list, main_debt: list | None) -> list:
    """The check: a violation not in the debt, an entry that no longer occurs, an entry main does not
    have (the list only shrinks against main; main_debt None: main has no list yet)."""
    found = []
    now = {v.key: v for v in violations}
    listed = {e["key"] for e in debt}
    for key in sorted(k for k in listed if k.split("|", 1)[0] in PORT06_RULES):
        found.append("tools/hook-debt.json lists %s: the rules %s are never debt (port-06): fix the rewrite by an engine change or "
                     "by its HOOKS.json exception" % (key, "/".join(PORT06_RULES)))
    for key in sorted(set(now) - listed):
        v = now[key]
        if v.rule in PORT06_RULES:
            found.append("%s/hooks.patch, %s: %s (%s): %s" % (v.folder, v.file, v.rule, RULES[v.rule], v.detail or _squeeze(v.text)[:100]))
            continue
        found.append("%s/hooks.patch, %s: %s (%s): a hook breaks the contract and is not in the debt list "
                     "(tools/hook-debt.json): %s" % (v.folder, v.file, v.rule, RULES[v.rule], _squeeze(v.text)[:100]))
    for key in sorted(listed - set(now)):
        found.append("tools/hook-debt.json lists %s, which no longer occurs: remove it: python tools/engine.py hook-debt" % key)
    if main_debt is not None:
        main_keys = {e["key"] for e in main_debt}
        main_rules = {e["rule"] for e in main_debt}
        for key in sorted(k for k in listed - main_keys
                          if not (k.split("|", 1)[0] in INTRODUCED_RULES and k.split("|", 1)[0] not in main_rules)):
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
