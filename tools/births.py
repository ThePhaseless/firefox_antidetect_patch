"""The birth points of a request: where the tree lets a network request get its context, and the ledger that says each one was looked at.

    python tools/births.py --tree <dir>                 the scan of a Firefox tree against tools/birth-ledger.json
    python tools/births.py --repo <repo> --rev <ref>    the same on a commit of a repository (no checkout: the end of `engine.py port`)
    python tools/births.py --tree <dir> --skeleton      the ledger entries a NEW site needs, verdict "review", to be decided by hand
    python tools/births.py --tree <dir> --accept-changed   rewrite the signature of every CHANGED entry (after reading each: the diff is the review)
    python tools/births.py --tree <dir> --prune         drop the GONE entries
    python tools/births.py --tree <dir> --tsv out.tsv   every site and what the judge says, one row each

THE CLASS. A browser context has its own proxy and resolver, chosen from the userContextId in the origin attributes of a request. A request that a
page causes but that is made with the default attributes, the system principal or a plain socket leaves OUTSIDE the proxy of its context: the TCP
socket of a TURN server's name, the OCSP request. Each was fixed at its call site. This file closes the CLASS: every place the tree creates a channel,
a socket transport, a UDP or TCP socket, a lookup or a speculative connection (the BIRTH POINTS) must be in the ledger with a reviewed verdict, so a
Mozilla tag that adds one, or changes the arguments or the context handling around one, is red until somebody looks.

THE KEY of a site is file + function + kind + call + ordinal, never the line: a port moves lines. With it the ledger holds a statement hash (the call
with its arguments) and a context signature (how many times each token that carries or drops a context appears in the whole function: OriginAttributes,
SetOriginAttributes, GetSystemPrincipal, NullPrincipal, CreateWithoutOriginAttributes, loadInfo, Stealth*...). A moved line changes neither.

THE VERDICTS (tools/birth-ledger.json, field `verdict`):
  ok        the context is carried (carries yes); `reason` names the argument that carries it
  hooked    carried through a hook of ours; `hook` is a folder of SERIES and STEALTH-HOOK(<hook>) must be in the function, or in `hook_at`
            ({"file": ..., "contains": ...}), so a port that loses the hook turns the entry red
  accepted  carries no context and is either not caused by a page or is the browser's own by design; `reason` says which (20+ characters)
  dead      never runs in the product; `proof` says why: pref-off:<pref>, platform:<name>, no-caller:<symbol>, unreachable:<why>
  fix       a known hole; needs `open` ({"since": "YYYY-MM-DD", "item": ..., "owner": ...}): the judge prints it, counts it, and exits 2 for it
The rule behind them: a site with carries != yes and reach != no is red unless its verdict is accepted, hooked or dead (or an open fix).

EXIT STATUS. 0 clean. 1 a problem: a NEW, CHANGED or MOVED site, an invalid entry, a lost hook, a chrome-JS HTTP client count above the ledger.
2 only the open items remain (red by design: the gate is not green while a known hole is undecided, and it hides nothing new).

The scanner reads text: comments are blanked, declarations skipped, the enclosing function is the nearest definition above. It cannot see a callee that
stops honouring its argument or a wrapper in a directory no kind matches: the behavioural gate of the wrapper (tests/test_nothing_of_a_context_...)
holds those.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "tools" / "birth-ledger.json"
VERDICTS = ("ok", "hooked", "accepted", "dead", "fix")
YES_NO = ("yes", "no", "unknown")
HOOK_TAG = "STEALTH-HOOK(%s)"

# ------------------------------------------------------------------------------------------------------------ what is scanned
CXX = (".cpp", ".h", ".cc", ".mm", ".c", ".hpp")
JS = (".js", ".mjs", ".jsm")
RS = (".rs",)

#: (regex on the path, why it is not scanned). The first match decides.
EXCLUDED = [
    (r"(^|/)third_party/", "third-party code"),
    (r"(^|/)(test|tests|gtest|gtests|testing|mochitest|xpcshell|crashtests|reftests|unit|fuzz|fuzzing|fuzztest|harness)/", "tests"),
    (r"^(testing|tools|docs|python|build|js/src|media|gfx/wr)/", "not the product, or an engine that makes no request"),
    (r"(^|/)(tools|test-helpers)/|^devtools/shared/loader/", "developer tools, screenshot and reftest harnesses, test helpers"),
    (r"^nsprpub/", "the portable runtime: its definitions are not call sites (callers are scanned)"),
    (r"^security/nss/(cmd|gtests|fuzz|lib/libpkix|lib/ssl|lib/softoken|lib/pk11wrap)/", "NSS tools and libraries with no network of their own"),
    (r"^toolkit/(crashreporter/client|components/bitsdownload)/", "crash reporter client and BITS: separate programs"),
    (r"^netwerk/dns/nsDNSService2\.cpp$", "implements nsIDNSService: it hands the attributes it was given to the resolver; its callers are the birth points"),
    (r"^netwerk/base/(nsServerSocket|TLSServerSocket)\.cpp$", "listening sockets: no request leaves from them"),
    (r"^netwerk/protocol/http/(HttpConnectionMgrShell\.h|nsHttpConnectionMgr\.cpp)$", "the connection manager's own queue: its callers (nsHttpHandler, the channels) are the birth points"),
    (r"(^|/)(test_[^/]*|browser_[^/]*|head[^/]*\.js|Test[A-Z][^/]*\.cpp|[^/]*_test\.[a-z]+)$", "test files"),
]
_EXCLUDED = [(re.compile(p), why) for p, why in EXCLUDED]

#: The kinds. `rx` is applied to a line with its comments blanked; group 0 is the call, `name` the call as the ledger spells it.
KINDS = [
    ("socket_transport", CXX, r"\b(CreateTransport|CreateRoutedTransport|OpenWithoutHttpProxy)\("),
    ("socket_transport_js", JS, r"\b(createTransport|createRoutedTransport)\("),
    ("dns_async", CXX, r"\b(AsyncResolveNative|AsyncResolveByTypeNative|ResolveNative|AsyncResolveByType)\("),
    ("dns_async_js", JS, r"\b(?:dns|DNS|Dns)\.(asyncResolve|resolve|asyncResolveNative|asyncResolveByType)\b"),
    ("dns_resolve_host", CXX, r"\b(ResolveHost)\("),
    ("dns_native_lookup", CXX, r"\b(getaddrinfo|GetAddrInfo|PR_GetAddrInfoByName|PR_GetHostByName|gethostbyname|DnsQuery_A|DnsQueryEx|res_nquery|res_query)\("),
    ("channel", CXX, r"\b(NS_NewChannel|NS_NewChannelInternal|NS_NewChannelWithTriggeringPrincipal|NS_NewChannelWithoutTriggeringPrincipal)\(|"
                     r"(?:->|\.|::)(NewChannel(?:FromURI|FromURIWithProxyFlags|2|FromURIWithLoadInfo|FromURI2)?)\("),
    ("channel_js", JS, r"\b(NetUtil\.newChannel|newChannel(?:FromURI)?(?:WithLoadInfo|WithProxyFlags)?)\("),
    ("proxy_resolve", CXX, r"\b(AsyncResolve|AsyncResolve2|Resolve2)\("),
    ("speculative", CXX, r"\b(SpeculativeConnect(?:Internal|WithOriginAttributes(?:Native)?|2)?)\("),
    ("speculative_js", JS, r"\b(?:Services\.io|connector|specService|speculator)\.(speculativeConnect\w*)\("),
    ("udp_socket", CXX + JS, r"\b(PR_OpenUDPSocket|PR_NewUDPSocket|NS_NewUDPSocket|CreateUDPSocket)\b|new (nsUDPSocket)\b|(udp-socket;1)|"
                             r"\bnew\s+(UDPSocketParent|UDPSocketChild|NrUdpSocketIpc|NrSocketIpc)\b"),
    ("tcp_socket", CXX + JS, r"\b(PR_OpenTCPSocket|PR_NewTCPSocket|PR_Connect|PR_ConnectContinue|PR_SendTo)\(|new (nsSocketTransport)\b|::(connect)\(|"
                             r"(?<![.>:\w])(sendto|WSAConnect)\(|\bnew\s+(TCPSocket)\b|(tcp-socket;1)"),
    ("rust_net", RS, r"\b(UdpSocket::bind|UdpSocket::from|TcpStream::connect|TcpStream::connect_timeout|tokio::net|UdpSocket|TcpStream)\b"),
]
_KINDS = [(name, exts, re.compile(rx)) for name, exts, rx in KINDS]

#: Lines that name a kind without being a call: declarations, logs, string messages, definitions of the call itself.
_NOT_A_CALL = re.compile(
    r"^\s*(?:#\s*(?:include|define|undef)\b|using\b)|\bLOG[A-Z0-9_]*\(|\br_log\(|NS_WARNING|\bMOZ_LOG\(|\bPR_LOG\(|\bLOG_[A-Z]+\(")
_DEFINITION = re.compile(r"^(?:\[\[nodiscard\]\]\s+)?(?:[\w:<>*&, ]+\s+)?(?:\w+::)+\w+\(|"
                         r"^(?:\[\[nodiscard\]\]\s+)?(?:nsresult|void|bool|int|NS_IMETHODIMP|static|virtual|inline)\b[^;=]*\(")

#: How many HTTP clients (fetch, XMLHttpRequest, new Request) chrome JS may have, per two-level directory: they are context 0 by construction.
JS_HTTP = re.compile(r"(new XMLHttpRequest|\bfetch\(|new Request\()")
JS_HTTP_EXCLUDED = re.compile(r"^(third_party|js/src|devtools|mobile|remote|docs|tools|testing)/|(^|/)(test|tests|mochitest|xpcshell|unit)/|"
                              r"(^|/)(test_|browser_|head)[^/]*$|^services/sync/tps/|^browser/extensions/newtab/|^toolkit/components/pdfjs/content/(web|build)/")

#: The tokens whose number in a function says how the context is handled there.
TOKENS = [
    ("OriginAttributes", r"(?<![A-Za-z])OriginAttributes\b"),
    ("SetOriginAttributes", r"\bSetOriginAttributes\b"),
    ("GetOriginAttributes", r"\b(?:Get|get)OriginAttributes\b|\boriginAttributes\b|\bOriginAttributesRef\b"),
    ("SystemPrincipal", r"\bGetSystemPrincipal\b|\bgetSystemPrincipal\b|\bloadUsingSystemPrincipal\b|\bsystemPrincipal\b"),
    ("NullPrincipal", r"\bNullPrincipal\b|\bnullPrincipal\b|\bcreateNullPrincipal\b"),
    ("WithoutAttributes", r"\bCreateWithoutOriginAttributes\b"),
    ("loadInfo", r"\b(?:aLoadInfo|loadInfo|LoadInfo|mLoadInfo)\b"),
    ("triggeringPrincipal", r"\b[a-zA-Z]*riggeringPrincipal\b"),
    ("userContextId", r"\buserContextId\b|\bmUserContextId\b"),
    ("Stealth", r"\bStealth\w+"),
]
_TOKENS = [(n, re.compile(rx)) for n, rx in TOKENS]


# ------------------------------------------------------------------------------------------------------------------ the text
def blank_comments(text: str, js: bool = False) -> str:
    """The text with every comment replaced by spaces (newlines kept, so line numbers hold). Strings and character literals are walked, not blanked."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        two = text[i:i + 2]
        if two == "//":
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif two == "/*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("".join(ch if ch == "\n" else " " for ch in text[i:j]))
            i = j
        elif c == "\\":              # an escape outside a string: `\/*` in a JS regex literal is not a comment
            out.append(text[i:i + 2])
            i += 2
        elif c in "\"'" or (js and c == "`"):
            j = i + 1
            while j < n and text[j] != c:
                if text[j] == "\\":
                    j += 1
                if j < n and text[j] == "\n" and c != "`":
                    break
                j += 1
            out.append(text[i:j + 1])
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


_C_FUNC = re.compile(r"((?:[\w~]+::)*[\w~]+|operator\s*\S+)\s*\(")
_C_INDENTED_FUNC = re.compile(r"^ {1,4}(?:[\w:<>~*&, ]+\s+)?(~?\w+)\([^;]*\)\s*(?:const\s*)?(?:override\s*)?\{\s*$")
_JS_FUNC = [re.compile(r"^\s*(?:async\s+)?(?:static\s+)?(?:get\s+|set\s+)?#?([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{\s*$"),
            re.compile(r"\bfunction\s*\*?\s*([A-Za-z_$][\w$]*)\s*\("),
            re.compile(r"^\s*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?(?:function|\([^)]*\)\s*=>)"),
            re.compile(r"^\s*([A-Za-z_$][\w$]*)\s*[:=]\s*(?:async\s+)?(?:function\b|\([^)]*\)\s*=>)")]
_RS_FUNC = re.compile(r"\bfn\s+(\w+)")
_NOT_A_FUNCTION = {"if", "for", "while", "switch", "catch", "return", "else", "do", "sizeof", "MOZ_TRY", "NS_ENSURE_SUCCESS"}


def _function_of(lines: list, index: int, ext: str):
    """(name, first line index, last line index) of the definition that holds line `index`; name is the file when none is found."""
    if ext in CXX:
        for i in range(index, -1, -1):
            line = lines[i]
            if not line.strip():
                continue
            if line[0] not in " \t#}/" and "(" in line and not line.rstrip().endswith(";") and not line.startswith(("namespace", "using", "typedef")):
                found = _C_FUNC.search(line)
                if found and found.group(1) not in _NOT_A_FUNCTION:
                    name, start = found.group(1), i
                    for k in range(i, len(lines)):
                        if lines[k].startswith("}"):
                            return name, start, k
                    return name, start, min(len(lines) - 1, i + 200)
            found = _C_INDENTED_FUNC.match(line)
            if found and found.group(1) not in _NOT_A_FUNCTION and i != index:
                indent = len(line) - len(line.lstrip())
                for k in range(i + 1, len(lines)):
                    if lines[k].startswith(" " * indent + "}") and not lines[k].startswith(" " * (indent + 1)):
                        return found.group(1), i, k
                return found.group(1), i, min(len(lines) - 1, i + 120)
        return None, max(0, index - 40), min(len(lines) - 1, index + 40)
    patterns = _JS_FUNC if ext in JS else [_RS_FUNC]
    for i in range(index, -1, -1):
        for rx in patterns:
            found = rx.search(lines[i])
            if found and found.group(1) not in _NOT_A_FUNCTION:
                indent = len(lines[i]) - len(lines[i].lstrip())
                for k in range(i + 1, len(lines)):
                    stripped = lines[k].lstrip()
                    if stripped.startswith("}") and len(lines[k]) - len(stripped) <= indent:
                        return found.group(1), i, k
                return found.group(1), i, min(len(lines) - 1, i + 120)
    return None, max(0, index - 40), min(len(lines) - 1, index + 40)


def _statement(lines: list, index: int) -> str:
    """The statement that starts on line `index`, whitespace normalized: up to the point its parentheses and braces close (at most 12 lines)."""
    depth, seen, parts = 0, False, []
    for k in range(index, min(len(lines), index + 12)):
        parts.append(lines[k].strip())
        for ch in lines[k]:
            if ch in "([{":
                depth += 1
                seen = True
            elif ch in ")]}":
                depth -= 1
        if (seen and depth <= 0) or lines[k].rstrip().endswith(";"):
            break
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def _signature(window: str) -> str:
    found = []
    for name, rx in _TOKENS:
        count = len(rx.findall(window))
        if count:
            found.append("%s=%d" % (name, count))
    return ";".join(found)


@dataclass
class Site:
    file: str
    function: str
    kind: str
    call: str
    n: int
    line: int
    stmt_sha: str
    ctx_sig: str
    stmt: str = ""
    window: str = field(default="", repr=False)

    @property
    def key(self) -> tuple:
        return (self.file, self.function, self.kind, self.call, self.n)


def excluded_why(path: str):
    for rx, why in _EXCLUDED:
        if rx.search(path):
            return why
    return None


def scan_text(path: str, text: str) -> list:
    """Every birth point of one file. `path` is the posix path from the root of the tree."""
    ext = "." + path.rsplit(".", 1)[-1] if "." in path.rsplit("/", 1)[-1] else ""
    kinds = [(name, rx) for name, exts, rx in _KINDS if ext in exts]
    if not kinds or excluded_why(path):
        return []
    blanked = blank_comments(text, js=ext in JS)
    lines = blanked.split("\n")
    sites, ordinals = [], Counter()
    for index, line in enumerate(lines):
        if not line.strip() or _NOT_A_CALL.search(line):
            continue
        for name, rx in kinds:
            found = rx.search(line)
            if not found:
                continue
            call = next((g for g in found.groups() if g), found.group(0).rstrip("("))
            stmt = _statement(lines, index)
            if _is_definition(line, call, stmt, ext):
                continue
            function, first, last = _function_of(lines, index, ext)
            window = "\n".join(lines[first:last + 1])
            label = function or path
            ordinals[(label, name, call)] += 1
            sites.append(Site(path, label, name, call, ordinals[(label, name, call)], index + 1,
                              hashlib.sha1(stmt.encode("utf-8")).hexdigest()[:12], _signature(window), stmt, window))
            break
    return sites


def _is_definition(line: str, call: str, stmt: str, ext: str) -> bool:
    """A definition or a declaration of the call itself (`nsresult nsDNSService::AsyncResolveNative(`, `virtual ... CreateTransport(`, a JS method
    `newChannel(uri, loadInfo) {`), as opposed to a call of it."""
    s = line.strip()
    if ext in JS:
        return bool(re.match(r"^(?:async\s+|static\s+|get\s+|set\s+)*#?[\w$]+\s*\([^)]*\)\s*\{", stmt)) and not re.match(r"^(?:return|if|for|while)\b", s)
    if re.search(r"(?:->|\.)\s*" + re.escape(call) + r"\(", s) or re.search(r"=\s*[\w:]*" + re.escape(call) + r"\(", s):
        return False
    if re.match(r"^(?:return\s|if\s|\(void\))", s):
        return False
    if ext == ".h" and s.startswith(call + "("):      # a declaration or an inline definition of the call itself: `NS_NewChannel...(` at the start of a header line
        return True
    if re.match(r"^explicit\s", s) or re.search(r"\)\s*=\s*(default|delete)\s*;", s):
        return True
    return bool(_DEFINITION.match(s)) and (s.endswith("{") or s.endswith(";") or s.endswith(",") or s.endswith("("))


# ---------------------------------------------------------------------------------------------------------------- the source
class Source:
    """A tree on disk (a working tree or a materialized one) or a commit of a repository: the files that may hold a birth point, and their text."""

    def __init__(self, repo: Path, rev: str | None = None):
        self.repo, self.rev = Path(repo), rev

    def _git(self, *args: str) -> str:
        done = subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True)
        if done.returncode not in (0, 1):
            raise SystemExit("git %s failed in %s: %s" % (" ".join(args[:2]), self.repo, done.stderr.decode(errors="replace")[:300]))
        return done.stdout.decode("utf-8", errors="replace")

    def candidates(self) -> list:
        """The files whose text names a kind: one `git grep -l` over every kind, then the scanner's own rules decide."""
        globs = ["*" + e for e in sorted(set(CXX + JS + RS))]
        args = ["grep", "-lIE", *([] if self.rev else ["--untracked"]), "-e", self._ere(), *([self.rev] if self.rev else []), "--", *globs]
        out = self._git(*args).split(chr(10))
        prefix = (self.rev + ":") if self.rev else ""
        return sorted(p[len(prefix):] if p.startswith(prefix) else p for p in out if p and not excluded_why(p[len(prefix):] if p.startswith(prefix) else p))

    @staticmethod
    def _ere() -> str:
        words = ["CreateTransport", "CreateRoutedTransport", "createTransport", "createRoutedTransport", "AsyncResolve", "ResolveNative", "asyncResolve",
                 "Dns\\.resolve", "ResolveHost", "getaddrinfo", "GetAddrInfo", "PR_GetAddrInfoByName", "PR_GetHostByName", "gethostbyname", "DnsQuery",
                 "res_nquery", "res_query", "NS_NewChannel", "NewChannel", "newChannel", "Resolve2", "peculativeConnect", "PR_OpenUDPSocket",
                 "PR_NewUDPSocket", "NS_NewUDPSocket", "CreateUDPSocket", "nsUDPSocket", "udp-socket;1", "UDPSocketParent", "UDPSocketChild",
                 "NrUdpSocketIpc", "NrSocketIpc", "PR_OpenTCPSocket", "PR_NewTCPSocket", "PR_Connect", "PR_SendTo", "nsSocketTransport", "connect\\(",
                 "sendto", "WSAConnect", "TCPSocket", "tcp-socket;1", "UdpSocket", "TcpStream", "tokio::net"]
        return "|".join(words)

    def is_firefox_tree(self) -> bool:
        """Whether the source holds the network stack of Firefox (a toy repository of a test does not: it has no birth points to judge)."""
        marker = "netwerk/base/nsSocketTransportService2.cpp"
        if not self.rev:
            return (self.repo / marker).is_file()
        return subprocess.run(["git", "-C", str(self.repo), "cat-file", "-e", "%s:%s" % (self.rev, marker)], capture_output=True).returncode == 0

    def read(self, path: str) -> str:
        if self.rev:
            return self._git("show", "%s:%s" % (self.rev, path))
        try:
            return (self.repo / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def js_http_counts(self) -> dict:
        args = ["grep", "-nIE", *([] if self.rev else ["--untracked"]), "-e", JS_HTTP.pattern, *([self.rev] if self.rev else []), "--", *("*" + e for e in JS)]
        counts, prefix = Counter(), (self.rev + ":") if self.rev else ""
        for line in self._git(*args).split(chr(10)):
            if not line:
                continue
            path = line.split(":", 2 if not self.rev else 3)[1 if self.rev else 0]
            if JS_HTTP_EXCLUDED.search(path) or excluded_why(path):
                continue
            parts = path.split("/")
            counts["/".join(parts[:2])] += 1
        return dict(sorted(counts.items()))


def scan(source: Source) -> list:
    sites = []
    for path in source.candidates():
        sites.extend(scan_text(path, source.read(path)))
    return sorted(sites, key=lambda s: (s.file, s.line))


def suggest(site: Site) -> tuple:
    """(carries, why): what the text of a NEW site suggests, to start the review (never a verdict). The principal VARIABLE is followed, not the name of the
    call: `NullPrincipal::Create(attrs)` carries the attributes `attrs` was made from, `NullPrincipal::CreateWithoutOriginAttributes()` and the system
    principal carry none."""
    stmt, window = site.stmt, site.window
    if re.search(r"(?<![A-Za-z])OriginAttributes\(\)|OriginAttributes\{\}", stmt):
        return "no", "default OriginAttributes in the call"
    if re.search(r"\b(?:GetSystemPrincipal|getSystemPrincipal|loadUsingSystemPrincipal|systemPrincipal)\b", stmt):
        if re.search(r"\bSetOriginAttributes\b|\bStealth\w+|\.originAttributes\s*=", window):
            return "unknown", "system principal, and the function sets attributes afterwards: read what it copies"
        return "no", "system principal in the call"
    if "CreateWithoutOriginAttributes" in stmt:
        return "no", "null principal without attributes in the call"
    for var in set(re.findall(r"\b([A-Za-z_]\w*)\b", stmt)):
        made = re.search(r"\b%s\s*=\s*[\w:]*NullPrincipal::(Create\w*)\(([^;]*?)\)\s*;" % re.escape(var), window)
        if made:
            if made.group(1) == "CreateWithoutOriginAttributes" or not made.group(2).strip() or "OriginAttributes()" in made.group(2):
                return "no", "%s is a null principal made without attributes" % var
            return "yes", "%s is made with NullPrincipal::%s(%s)" % (var, made.group(1), made.group(2).strip())
        if re.search(r"\b%s\s*=\s*[\w:]*(?:GetSystemPrincipal|getSystemPrincipal)\(" % re.escape(var), window):
            return "no", "%s is the system principal" % var
    if re.search(r"\b(?:aLoadInfo|loadInfo|aDocument|doc|aPrincipal|aLoadingNode|aRequestingNode|mPrincipal|NodePrincipal|[a-zA-Z]*riggeringPrincipal|"
                 r"[a-zA-Z]*OriginAttributes|aOA|mOA)\b", stmt):
        return "yes", "a document, principal, loadinfo or attributes in the call"
    return "unknown", "nothing in the call says where the context comes from"


# ------------------------------------------------------------------------------------------------------------------ the ledger
def load_ledger(path: Path = LEDGER) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_ledger(ledger: dict, path: Path = LEDGER) -> None:
    ledger["entries"] = sorted(ledger["entries"], key=entry_sort_key)
    lines = ["{"]
    for name in ("tag", "scanner", "excluded_note", "chrome_js_http"):
        if name in ledger:
            lines.append(" %s: %s," % (json.dumps(name), json.dumps(ledger[name], ensure_ascii=False)))
    lines.append(' "entries": [')
    lines.append(",\n".join("  " + json.dumps(e, ensure_ascii=False) for e in ledger["entries"]))
    lines.append(" ]")
    lines.append("}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def entry_key(e: dict) -> tuple:
    return (e["file"], e["function"], e["kind"], e["call"], e["n"])


def entry_sort_key(e: dict) -> tuple:
    return entry_key(e)


def ledger_problems(ledger: dict, folders=None) -> list:
    """What is wrong with the ledger as a file, with no tree: every entry decided and complete, sorted, unique, the hooks real. `folders` is SERIES."""
    found, seen, last = [], set(), None
    for e in ledger.get("entries", []):
        where = "%s: %s %s/%s #%d" % (e.get("file"), e.get("function"), e.get("kind"), e.get("call"), e.get("n", 0))
        for name in ("file", "function", "kind", "call", "n", "stmt_sha", "ctx_sig", "carries", "reach", "verdict", "reason"):
            if name not in e:
                found.append("birth ledger: %s has no %r" % (where, name))
        if any(name not in e for name in ("file", "function", "kind", "call", "n")):
            continue
        key = entry_key(e)
        if key in seen:
            found.append("birth ledger: %s is listed twice" % where)
        seen.add(key)
        if last is not None and key < last:
            found.append("birth ledger: %s is out of order (the file is sorted by file, function, kind, call, n)" % where)
        last = key
        verdict, carries, reach = e.get("verdict"), e.get("carries"), e.get("reach")
        if verdict not in VERDICTS:
            found.append("birth ledger: %s has verdict %r, not one of %s" % (where, verdict, "/".join(VERDICTS)))
            continue
        if carries not in YES_NO or reach not in YES_NO:
            found.append("birth ledger: %s carries/reach must be yes, no or unknown" % where)
        reason = (e.get("reason") or "").strip()
        if len(reason) < 20:
            found.append("birth ledger: %s has no reason (20+ characters): say why" % where)
        if verdict == "ok" and carries != "yes":
            found.append("birth ledger: %s is ok but carries %r: a site that does not carry the context is accepted, hooked or dead" % (where, carries))
        if verdict == "hooked":
            hook = e.get("hook")
            if not hook:
                found.append("birth ledger: %s is hooked and names no hook (a folder of SERIES)" % where)
            elif folders is not None and hook not in folders:
                found.append("birth ledger: %s names the hook %r, which is not a folder of SERIES" % (where, hook))
            at = e.get("hook_at")
            if at is not None and not (isinstance(at, dict) and at.get("file") and at.get("contains")):
                found.append("birth ledger: %s has a hook_at that is not {file, contains}" % where)
        if verdict == "dead":
            proof = e.get("proof") or ""
            if not re.match(r"^(pref-off:\S+|platform:\w+|no-caller:\S+|unreachable:.{10,})", proof):
                found.append("birth ledger: %s is dead and its proof %r is none of pref-off:, platform:, no-caller:, unreachable:" % (where, proof))
        if verdict == "accepted" and carries == "yes":
            found.append("birth ledger: %s is accepted but carries the context: it is ok" % where)
        if verdict == "fix":
            opened = e.get("open")
            if not (isinstance(opened, dict) and re.match(r"^\d{4}-\d\d-\d\d$", str(opened.get("since", ""))) and opened.get("item")):
                found.append("birth ledger: %s is a fix and has no dated open state ({since: YYYY-MM-DD, item, owner})" % where)
        elif e.get("open"):
            found.append("birth ledger: %s has an open state but its verdict is %s" % (where, verdict))
    return found


# ------------------------------------------------------------------------------------------------------------------ the judge
@dataclass
class Report:
    new: list = field(default_factory=list)          # Sites
    changed: list = field(default_factory=list)      # (Site, entry, what)
    moved: list = field(default_factory=list)        # (Site, entry)
    gone: list = field(default_factory=list)         # entries
    open: list = field(default_factory=list)         # entries
    invalid: list = field(default_factory=list)      # sentences
    matched: int = 0
    sites: int = 0

    @property
    def red(self) -> bool:
        return bool(self.new or self.changed or self.moved or self.invalid)

    @property
    def status(self) -> int:
        return 1 if self.red else (2 if self.open else 0)


def judge(ledger: dict, sites: list, read=None, folders=None) -> Report:
    """The ledger against the sites. `read(path)` gives the text of a file, for the hooks that live in another file (None: they are not checked)."""
    report = Report(sites=len(sites))
    report.invalid += ledger_problems(ledger, folders)
    entries = {entry_key(e): e for e in ledger.get("entries", []) if all(k in e for k in ("file", "function", "kind", "call", "n"))}
    matched = set()
    unmatched = []
    for site in sites:
        entry = entries.get(site.key)
        if entry is None:
            unmatched.append(site)
            continue
        matched.add(site.key)
        report.matched += 1
        what = []
        if entry.get("stmt_sha") != site.stmt_sha:
            what.append("the statement is not the one that was reviewed (%s -> %s): %s" % (entry.get("stmt_sha"), site.stmt_sha, site.stmt[:140]))
        if entry.get("ctx_sig") != site.ctx_sig:
            what.append("the context signature of %s changed: %r -> %r" % (site.function, entry.get("ctx_sig"), site.ctx_sig))
        if what:
            report.changed.append((site, entry, "; ".join(what)))
        report.invalid += _entry_against_tree(entry, site, read)
        if entry.get("verdict") == "fix" and isinstance(entry.get("open"), dict):
            report.open.append(entry)
    gone = [e for k, e in entries.items() if k not in matched]
    for site in unmatched:
        twin = [e for e in gone if e["file"] != site.file and e.get("stmt_sha") == site.stmt_sha and e.get("ctx_sig") == site.ctx_sig]
        if len(twin) == 1:
            report.moved.append((site, twin[0]))
            gone.remove(twin[0])
        else:
            report.new.append(site)
    report.gone = gone
    return report


def _entry_against_tree(entry: dict, site: Site, read) -> list:
    out = []
    where = "%s: %s %s/%s #%d" % (entry["file"], entry["function"], entry["kind"], entry["call"], entry["n"])
    if entry.get("verdict") == "hooked" and entry.get("hook"):
        tag = HOOK_TAG % entry["hook"]
        marker = entry.get("hook_at") or {}
        if tag not in site.window:
            at_file = marker.get("file", entry["file"])
            text = read(at_file) if read else None
            if text is None:
                return out
            needle = marker.get("contains", tag)
            if tag not in text or needle not in text:
                out.append("%s is hooked by %s and the hook is gone: %s has %s=%s, %s=%s"
                           % (where, entry["hook"], at_file, repr(tag), tag in text, repr(needle), needle in text))
    return out


def judge_chrome_js(ledger: dict, counts: dict) -> list:
    allowed = ledger.get("chrome_js_http", {})
    return ["chrome JS HTTP clients in %s: %d, the ledger allows %d (each is a reader of user context 0: decide it, then raise the number)"
            % (d, n, allowed.get(d, 0)) for d, n in sorted(counts.items()) if n > allowed.get(d, 0)]


# -------------------------------------------------------------------------------------------------------------- the output
def describe(site: Site) -> str:
    return "%s:%d %s %s/%s #%d  %s" % (site.file, site.line, site.function, site.kind, site.call, site.n, site.stmt[:110])


def print_report(report: Report, extra: list, title: str = "") -> None:
    if title:
        print(title)
    for site in report.new:
        print("NEW      %s\n         the text suggests carries=%s: %s" % ((describe(site),) + suggest(site)))
    for site, entry in report.moved:
        print("MOVED    %s\n         same statement and context signature as %s: %s (copy its verdict after reading it)"
              % (describe(site), entry["file"], entry["function"]))
    for site, entry, what in report.changed:
        print("CHANGED  %s:%d %s %s/%s #%d (verdict %s): %s" % (site.file, site.line, site.function, site.kind, site.call, site.n,
                                                                entry.get("verdict"), what))
    for line in report.invalid + extra:
        print("INVALID  %s" % line)
    for e in report.gone:
        print("GONE     %s: %s %s/%s #%d" % (e["file"], e["function"], e["kind"], e["call"], e["n"]))
    for e in report.open:
        o = e["open"]
        print("OPEN     since %s %s: %s (%s #%d) owner %s" % (o["since"], o["item"], e["file"], e["function"], e["n"], o.get("owner", "-")))
    print("births: %d sites, %d matched, NEW %d, CHANGED %d, MOVED %d, GONE %d, INVALID %d, OPEN %d -> %s"
          % (report.sites, report.matched, len(report.new), len(report.changed), len(report.moved), len(report.gone),
             len(report.invalid) + len(extra), len(report.open),
             "RED" if (report.red or extra) else ("red by design (open items)" if report.open else "green")))


def write_tsv(path: Path, sites: list, report: Report, ledger: dict) -> None:
    entries = {entry_key(e): e for e in ledger["entries"]}
    new, changed = {s.key for s in report.new}, {s.key for s, _e, _w in report.changed}
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("file\tline\tcall\tcarries-context\tpage-reachable\tstate\tverdict\tnote\n")
        for s in sites:
            e = entries.get(s.key, {})
            state = "NEW" if s.key in new else ("CHANGED" if s.key in changed else "ok")
            fh.write("\t".join([s.file, str(s.line), "%s/%s" % (s.kind, s.call), e.get("carries", "unknown"), e.get("reach", "unknown"), state,
                                e.get("verdict", "review"), (e.get("reason") or "").replace("\t", " ")]) + "\n")


def skeleton(sites: list) -> list:
    return [{"file": s.file, "function": s.function, "kind": s.kind, "call": s.call, "n": s.n, "stmt_sha": s.stmt_sha, "ctx_sig": s.ctx_sig,
             "carries": suggest(s)[0], "reach": "unknown", "verdict": "review", "reason": "", "_suggested_because": suggest(s)[1], "_stmt": s.stmt[:160]}
            for s in sites]


def run(source: Source, series_folders=None, ledger_path: Path = LEDGER, title: str = "", tsv: Path | None = None,
        accept_changed: bool = False, prune: bool = False, show_skeleton: bool = False) -> int:
    began = time.monotonic()
    ledger = load_ledger(ledger_path)
    sites = scan(source)
    report = judge(ledger, sites, read=source.read, folders=set(series_folders) if series_folders is not None else None)
    counts = source.js_http_counts()
    extra = judge_chrome_js(ledger, counts)
    if accept_changed or prune:
        changed = {site.key: site for site, _e, _w in report.changed}
        keep = []
        gone = {entry_key(e) for e in report.gone}
        for e in ledger["entries"]:
            if accept_changed and entry_key(e) in changed:
                e["stmt_sha"], e["ctx_sig"] = changed[entry_key(e)].stmt_sha, changed[entry_key(e)].ctx_sig
            if prune and entry_key(e) in gone:
                continue
            keep.append(e)
        ledger["entries"] = keep
        save_ledger(ledger, ledger_path)
        print("ledger rewritten: %d entries" % len(keep))
    print_report(report, extra, title)
    if show_skeleton and report.new:
        print(json.dumps(skeleton(report.new), indent=1, ensure_ascii=False))
    if tsv:
        write_tsv(tsv, sites, report, ledger)
    print("scan took %.1f s, %d JS HTTP clients counted in %d directories" % (time.monotonic() - began, sum(counts.values()), len(counts)))
    return 1 if (report.red or extra) else (2 if report.open else 0)


def series_folder_list() -> list:
    return (ROOT / "SERIES").read_text(encoding="utf-8").split()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tree", type=Path, help="a Firefox tree on disk (a working tree or the materialized one)")
    ap.add_argument("--repo", type=Path, help="a repository, with --rev")
    ap.add_argument("--rev", help="the commit of --repo to scan (no checkout)")
    ap.add_argument("--ledger", type=Path, default=LEDGER)
    ap.add_argument("--tsv", type=Path)
    ap.add_argument("--skeleton", action="store_true")
    ap.add_argument("--accept-changed", action="store_true")
    ap.add_argument("--prune", action="store_true")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # a statement may hold any character
    if bool(a.tree) == bool(a.repo):
        raise SystemExit("give --tree <dir>, or --repo <repo> --rev <ref>")
    if a.repo and not a.rev:
        raise SystemExit("--repo needs --rev")
    source = Source(a.tree) if a.tree else Source(a.repo, a.rev)
    return run(source, series_folder_list(), a.ledger, tsv=a.tsv, accept_changed=a.accept_changed, prune=a.prune, show_skeleton=a.skeleton)


if __name__ == "__main__":
    sys.exit(main())
