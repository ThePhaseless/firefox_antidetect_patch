#!/usr/bin/env python3
"""The package manifest A/B of the engine's gate: the files of the archives of the engine published before, against the candidate's.

    python3 scripts/ci/ab_package.py seal-check <dir> [--github-output file]
    python3 scripts/ci/ab_package.py list <archive> [--out list.json]
    python3 scripts/ci/ab_package.py explain --series <dir> --from <commit> --to <commit> [--out explained.json]
    python3 scripts/ci/ab_package.py compare <published> <candidate> [--explained explained.json] [--report report.json] [--summary summary.md]
                                              [--published-archive a] [--candidate-archive b] [--expect-identical]

`seal-check` judges a downloaded release: every archive the seal names is in <dir>, with the sha256 and the size the seal says and the sha256 of
checksums.txt; it prints the series commit of the seal (and appends series_commit=<sha> to the file of --github-output).
`list` reads a .tar.gz or .zip and writes one entry per file: path, kind (by magic bytes: elf, so, pe, dll, exe, chk, ja, text, other, link), size and
sha256. A .ja (omni.ja, browser/omni.ja), .xpi or .jar is read with a reader of its own (Mozilla's optimized layout puts the central directory first,
which zipfile refuses) and every member is an entry too, at "<container>!<path inside>".
`compare` takes two lists or two archives. Exit 1 when it is red, 2 when an input cannot be read.

  RED      a file added that no source of ours explains, or a file missing (also a member of a .ja); a file of a non-binary kind (text, other, link) whose content changed and that is neither
           explained nor build identity (the members of a .ja are such files: each one is judged, none is only reported); a kind that changed from or
           to a non-binary one.
  REPORTED compiled files whose content changed (elf, so, pe, dll, exe, chk: the build writes them again; ja: the container).
  BUILD IDENTITY. A changed text file (a member of a .ja too) is build identity when, line by line, the only lines that differ are lines that carry a
           token the build writes (IDENTITY_TOKENS: MOZ_BUILDID, the source stamp, repository and URL, by the shape of the line and of its value, never by the
           name of the file): the file with those values masked is the same on both sides. The proof is printed: of every changed text file (members of a
           .ja included) the report and the summary carry a unified diff, capped at DIFF_LINES lines. The content is read from the archives (compare given
           lists only cannot prove it: --published-archive / --candidate-archive, or archives instead of lists).
  --expect-identical (the A/A: a package against itself) is red when anything at all changed, of any class, binaries and linkage included.

CALLS INTO THE HOST. `list` also reads the linkage of every binary (elf, so, pe, dll, exe), with readers of its own: of a PE the import table and the
delay-load table (per DLL, every function by name or "#ordinal") and the exports; of an ELF the undefined symbols of .dynsym with their version and the
library the version names (.gnu.version, .gnu.version_r: "getifaddrs@GLIBC_2.3" from libc.so.6), DT_NEEDED, DT_SONAME and the defined symbols. For every
binary whose bytes changed, `compare` lists both directions: a new import or a new DT_NEEDED that the package itself does not answer is RED (a new call
into the host, even if no test runs it); one the package answers, and one that is gone, are REPORTED. linkage_ab() says when the package answers it. A
table that cannot be read in the candidate is RED, unless it could not be read in the published package either.

EXPLAINED. `explain` names the files of ours that changed between the series commit of the published seal and the candidate's: the paths of the
series' git diff under <folder>/src/<tree path> (the file as it lies in Firefox's tree), and, for a changed <folder>/hooks.patch, the Mozilla files
whose section of the patch differs between the two commits. A package file is explained when it is one of those, by this rule (the whole of it):
  1. juggler/<rest>  ->  modules/juggler/<rest>   (juggler/moz.build serves it from resource://gre/modules/juggler/; loose on Linux, inside omni.ja on
     Windows: the "<container>!" prefix is dropped before the comparison)
  2. any other source that is not C, C++, Rust, build or script code  ->  the package files with the same basename (jar.mn and moz.build flatten and move
     files, so the basename is what is stable: StealthPingsender.sys.mjs, firefox.js, ...)
  3. a record that one of our builds writes (OWN_BUILD_RECORDS: lavapipe/VERSION.json, whose "inputs" line is the build's cache key)  ->  a source that is
     one of the files that build's key reads (lavapipe_build.INPUTS: tree paths and globs, `*` never crosses `/`); the whole file is explained
A file ADDED to the package is explained by the same rule (the new file of ours that the series adds, named by its source: StealthAtoms.sys.mjs under
juggler/, StealthLaunchCounterLoader.sys.mjs in browser/components/): it is then reported with its source and is not red; an added file that no source maps to is red.
A changed source that maps to nothing is no reason: a package file that changed and that no source maps to is red. A hooks.patch is named by its files,
not by its hunks: a section that changed explains its whole file. An explained file always says which source explained it: "explained" is the list of
those sources (empty when none does), and the report and the summary print it: "(explained by <source>, <source>)".
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import posixpath
import re
import struct
import subprocess
import sys
import tarfile
import zipfile
import zlib
from pathlib import PurePosixPath

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # the sibling module, whichever directory the script is run from
import lavapipe_build  # noqa: E402

JA_EXTS = (".ja", ".xpi", ".jar")
BINARY_KINDS = {"elf", "so", "pe", "dll", "exe", "chk", "ja"}
# What the build writes into a file of the package, and where the tree says so (the Firefox tree of the series, line numbers of the file named):
#   buildid.h        build/variables.py buildid_header(): "#define MOZ_BUILDID <14 digits>" (MOZ_BUILD_DATE or the time of the build)
#   source-repo.h    build/variables.py source_repo_header(): MOZ_SOURCE_STAMP (the changeset), MOZ_SOURCE_REPO, MOZ_SOURCE_URL (<repo>/rev|commit/<changeset>)
#   AppConstants.sys.mjs (#include of both headers, toolkit/modules/moz.build EXTRA_PP_JS_MODULES): MOZ_BUILDID: "@MOZ_BUILDID@" (line 171),
#                    SOURCE_REVISION_URL: "@MOZ_SOURCE_URL@" (line 194; "" when the build records no source info)
#   application.ini  build/application.ini.in: BuildID=@MOZ_BUILDID@ (29), SourceRepository=@MOZ_SOURCE_REPO@ (31), SourceStamp=@MOZ_SOURCE_STAMP@ (34),
#                    ServerURL=...&buildid=@MOZ_BUILDID@ (50); platform.ini carries the same BuildID and source stamp
#   sourcestamp.txt  python/mozbuild/mozbuild/action/make_sourcestamp_file.py: line 1 the BuildID, line 2 the MOZ_SOURCE_URL
# A line is a token line when it matches one of these (group p: before the value, v: the value, s: after it) and its value has the shape of the token.
_HEX = r"[0-9a-f]{12,40}"
_SOURCE_URL = r"https?://[^\s\"']+/(?:rev|commit)/" + _HEX
IDENTITY_TOKENS = tuple((name, re.compile(rx)) for name, rx in (
    ("MOZ_BUILDID", r'^(?P<p>\s*MOZ_BUILDID:\s*")(?P<v>\d{14})(?P<s>",?\s*)$'),
    ("MOZ_SOURCE_URL", r'^(?P<p>\s*SOURCE_REVISION_URL:\s*")(?P<v>|' + _SOURCE_URL + r')(?P<s>",?\s*)$'),
    ("MOZ_BUILDID", r"^(?P<p>BuildID=)(?P<v>\d{14})(?P<s>\s*)$"),
    ("MOZ_SOURCE_STAMP", r"^(?P<p>SourceStamp=)(?P<v>" + _HEX + r")(?P<s>\s*)$"),
    ("MOZ_SOURCE_REPO", r"^(?P<p>SourceRepository=)(?P<v>https?://\S+)(?P<s>\s*)$"),
    ("MOZ_BUILDID", r"^(?P<p>ServerURL=.*[?&]buildid=)(?P<v>\d{14})(?P<s>(?:&.*)?\s*)$"),
    ("MOZ_BUILDID", r"^(?P<p>)(?P<v>\d{14})(?P<s>\s*)$"),  # sourcestamp.txt, line 1
    ("MOZ_SOURCE_URL", r"^(?P<p>)(?P<v>" + _SOURCE_URL + r")(?P<s>\s*)$"),  # sourcestamp.txt, line 2
))
DIFF_LINES = 40
DIFF_LINE_CHARS = 200
MAX_DIFF_BYTES = 4 << 20
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


# ---------------------------------------------------------------- the linkage of a binary: what it asks of the libraries it is loaded with

LINKED_KINDS = {"elf", "so", "pe", "dll", "exe"}
# On Windows 10 and later the loader takes the UCRT and the API sets from System32 even when the application ships a copy: a function of theirs is a call
# into the host whatever the package holds.
SYSTEM_PE = ("api-ms-", "ext-ms-")
SYSTEM_PE_NAMES = {"ucrtbase.dll"}


def _cstr(data: bytes, off: int, limit: int = 4096) -> str:
    end = data.find(b"\0", off, off + limit)
    if off < 0 or off >= len(data) or end < 0:
        raise Unreadable("a string at %#x runs off the file" % off)
    return data[off:end].decode("latin-1")


def pe_linkage(data: bytes) -> dict:
    """{"imports": {dll: [function or "#ordinal"]}, "delay_imports": {...}, "exports": [name and "#ordinal" of every export that is not a forwarder]}."""
    try:
        lfanew = struct.unpack_from("<I", data, 0x3C)[0]
        if data[lfanew:lfanew + 4] != b"PE\0\0":
            raise Unreadable("no PE signature at %#x" % lfanew)
        nsec, opt_size = struct.unpack_from("<H12xH", data, lfanew + 6)
        opt = lfanew + 24
        magic = struct.unpack_from("<H", data, opt)[0]
        if magic == 0x20B:
            image_base, nrva, dirs, tfmt, flag = struct.unpack_from("<Q", data, opt + 24)[0], struct.unpack_from("<I", data, opt + 108)[0], opt + 112, "<Q", 1 << 63
        elif magic == 0x10B:
            image_base, nrva, dirs, tfmt, flag = struct.unpack_from("<I", data, opt + 28)[0], struct.unpack_from("<I", data, opt + 92)[0], opt + 96, "<I", 1 << 31
        else:
            raise Unreadable("optional header magic %#x" % magic)
        headers = struct.unpack_from("<I", data, opt + 60)[0]
        sections = [struct.unpack_from("<8xIIII", data, opt + opt_size + 40 * i) for i in range(nsec)]

        def off(rva: int) -> int:
            if rva < headers:
                return rva
            for vsize, va, rsize, raw in sections:
                if va <= rva < va + max(vsize, rsize) and rva - va < rsize:
                    return rva - va + raw
            raise Unreadable("rva %#x is in no section" % rva)

        def directory(i: int):
            return struct.unpack_from("<II", data, dirs + 8 * i) if i < nrva else (0, 0)

        tsize = struct.calcsize(tfmt)

        def thunks(rva: int) -> list:
            names, pos = [], off(rva)
            for _ in range(1 << 20):
                value = struct.unpack_from(tfmt, data, pos)[0]
                if not value:
                    return names
                names.append("#%d" % (value & 0xFFFF) if value & flag else _cstr(data, off(value & 0x7FFFFFFF) + 2))
                pos += tsize
            raise Unreadable("a thunk array with no end")

        imports, delay, exports = {}, {}, set()
        rva, _size = directory(1)
        if rva:
            pos = off(rva)
            while True:
                oft, _t, _f, name, ft = struct.unpack_from("<5I", data, pos)
                if not (oft or name or ft):
                    break
                imports.setdefault(_cstr(data, off(name)).lower(), set()).update(thunks(oft or ft))
                pos += 20
        rva, _size = directory(13)
        if rva:
            pos = off(rva)
            while True:
                attrs, name, _h, iat, inta, _b, _u, _t = struct.unpack_from("<8I", data, pos)
                if not (name or iat or inta):
                    break
                base = 0 if attrs & 1 else image_base  # attribute bit 0 clear: the fields are addresses, not rvas
                delay.setdefault(_cstr(data, off(name - base)).lower(), set()).update(thunks(inta - base))
                pos += 32
        rva, size = directory(0)
        if rva:
            ordbase, nfun, nnames, afun, anames, aords = struct.unpack_from("<16x6I", data, off(rva))
            funcs = struct.unpack_from("<%dI" % nfun, data, off(afun)) if nfun else ()
            ords = struct.unpack_from("<%dH" % nnames, data, off(aords)) if nnames else ()
            nrvas = struct.unpack_from("<%dI" % nnames, data, off(anames)) if nnames else ()
            real = {i for i, f in enumerate(funcs) if f and not rva <= f < rva + size}  # in the export directory: a forwarder to another DLL
            exports |= {"#%d" % (ordbase + i) for i in real}
            exports |= {_cstr(data, off(n)) for n, i in zip(nrvas, ords) if i in real}
    except (struct.error, IndexError) as exc:
        raise Unreadable("a PE that ends early: %s" % exc)
    return {"imports": {k: sorted(v) for k, v in sorted(imports.items())}, "delay_imports": {k: sorted(v) for k, v in sorted(delay.items())}, "exports": sorted(exports)}


def elf_linkage(data: bytes) -> dict:
    """{"soname", "needed": [DT_NEEDED], "imports": {library of the version, "" when unversioned: ["symbol@VERSION" or "symbol"]}, "exports": [defined names]}."""
    try:
        if data[4] not in (1, 2) or data[5] not in (1, 2):
            raise Unreadable("ELF class %d, data %d" % (data[4], data[5]))
        e = "<" if data[5] == 1 else ">"
        wide = data[4] == 2
        if wide:
            phoff, shoff, phentsize, phnum, shentsize, shnum = struct.unpack_from(e + "8xQQ6xHHHH", data, 24)
        else:
            phoff, shoff, phentsize, phnum, shentsize, shnum = struct.unpack_from(e + "4xII6xHHHH", data, 24)
        shfmt = e + ("IIQQQQIIQQ" if wide else "IIIIIIIIII")
        if shoff and shnum == 0:
            shnum = struct.unpack_from(shfmt, data, shoff)[5]  # more sections than e_shnum holds: section 0 carries the count
        sh = [struct.unpack_from(shfmt, data, shoff + shentsize * i) for i in range(shnum)] if shoff else []
        # (name, type, flags, addr, offset, size, link, info, align, entsize)
        by_type = {}
        for s in sh:
            by_type.setdefault(s[1], s)
        dynamic_segment = any(struct.unpack_from(e + "I", data, phoff + phentsize * i)[0] == 2 for i in range(phnum)) if phoff else False
        dynsym = by_type.get(11)
        if dynsym is None:
            if dynamic_segment or 6 in by_type:
                raise Unreadable("a dynamic ELF with no .dynsym section")
            return {"soname": None, "needed": [], "imports": {}, "exports": []}

        def strtab(link: int):
            s = sh[link]
            return lambda o: _cstr(data, s[4] + o)

        names = strtab(dynsym[6])
        symfmt = e + ("IBBHQQ" if wide else "IIIBBH")
        count = dynsym[5] // struct.calcsize(symfmt)
        syms = list(struct.iter_unpack(symfmt, data[dynsym[4]:dynsym[4] + count * struct.calcsize(symfmt)]))
        if not wide:
            syms = [(n, info, other, shndx, value, size) for n, value, size, info, other, shndx in syms]
        versym = by_type.get(0x6FFFFFFF)
        versions = struct.unpack_from(e + "%dH" % count, data, versym[4]) if versym else (0,) * count
        needed_versions = {}  # index -> (version, file)
        verneed = by_type.get(0x6FFFFFFE)
        if verneed and verneed[5]:
            vstr, pos = strtab(verneed[6]), verneed[4]
            for _ in range(verneed[7] or 1 << 16):
                _v, cnt, vfile, aux, nxt = struct.unpack_from(e + "HHIII", data, pos)
                apos = pos + aux
                for _ in range(cnt):
                    _h, _fl, other, vname, anext = struct.unpack_from(e + "IHHII", data, apos)
                    needed_versions[other] = (vstr(vname), vstr(vfile))
                    apos += anext
                if not nxt:
                    break
                pos += nxt
        imports, exports = {}, set()
        for i, (n, info, _other, shndx, _value, _size) in enumerate(syms):
            if not n or info >> 4 not in (1, 2, 10):  # GLOBAL, WEAK, GNU_UNIQUE
                continue
            name = names(n)
            if shndx:
                exports.add(name)
                continue
            version, vfile = needed_versions.get(versions[i] & 0x7FFF, (None, ""))
            imports.setdefault(vfile, set()).add(name + "@" + version if version else name)
        needed, soname = [], None
        dyn = by_type.get(6)
        if dyn:
            dstr, dfmt = strtab(dyn[6]), e + ("qQ" if wide else "iI")
            for tag, val in struct.iter_unpack(dfmt, data[dyn[4]:dyn[4] + dyn[5] - dyn[5] % struct.calcsize(dfmt)]):
                if tag == 0:
                    break
                if tag == 1:
                    needed.append(dstr(val))
                elif tag == 14:
                    soname = dstr(val)
    except (struct.error, IndexError) as exc:
        raise Unreadable("an ELF that ends early: %s" % exc)
    return {"soname": soname, "needed": needed, "imports": {k: sorted(v) for k, v in sorted(imports.items())}, "exports": sorted(exports)}


def linkage(kind: str, data: bytes) -> dict:
    """The linkage of a binary of the package, or {"error": why} when it cannot be read (red in the candidate when the published one could be read)."""
    try:
        return elf_linkage(data) if kind in ("elf", "so") else pe_linkage(data)
    except Unreadable as exc:
        return {"error": str(exc)}


def _pe_calls(link: dict) -> set:
    """{(dll, function)} of a PE, the delay-loaded ones too: a function moved between the two tables is not a new call."""
    return {(dll, f) for table in ("imports", "delay_imports") for dll, fs in link[table].items() for f in fs}


def _elf_calls(link: dict) -> set:
    return {(lib, s) for lib, ss in link["imports"].items() for s in ss}


def _is_system_pe(name: str) -> bool:
    return name.startswith(SYSTEM_PE) or name in SYSTEM_PE_NAMES


def linkage_ab(published: dict, candidate: dict) -> dict:
    """The calls of every binary of both packages whose bytes changed: new and gone imports (PE: per DLL, the delay-loaded included; ELF: the undefined
    symbols of .dynsym with their version and the library the version names), new and gone libraries (ELF: DT_NEEDED). A new call is inside the package
    when the candidate package itself answers it, by this rule (the whole of it):
      PE   the DLL it names is a file of the package (by basename, any folder) that exports the function (by name, or "#ordinal") and not as a forwarder,
           and the DLL is not one the loader takes from System32 anyway (api-ms-*, ext-ms-*, ucrtbase.dll);
      ELF  a versioned symbol: the library its version names (vn_file) is an ELF of the package (by DT_SONAME or basename) that defines the symbol;
           an unversioned symbol: an ELF of the package that the binary loads (DT_NEEDED, followed through the package's own libraries) defines it;
      a new DT_NEEDED: the library is an ELF of the package.
    Anything else is a call into the host: red. A call that is gone is reported."""
    pub = {e["path"]: e for e in published["entries"] if e.get("kind") in LINKED_KINDS}
    cand = {e["path"]: e for e in candidate["entries"] if e.get("kind") in LINKED_KINDS}
    pe_files, elf_files = {}, {}
    for path, e in cand.items():
        link = e.get("linkage") or {}
        if "!" in path or "error" in link or not link:
            continue
        base = posixpath.basename(path)
        if e["kind"] in ("elf", "so"):
            for name in {base, link.get("soname") or base}:
                elf_files.setdefault(name, []).append((path, link))
        elif not _is_system_pe(base.lower()):
            pe_files.setdefault(base.lower(), []).append((path, link))

    def pe_provider(dll: str, func: str):
        return next((p for p, link in pe_files.get(dll, ()) if func in link["exports"]), None)

    def elf_closure(link: dict) -> list:
        seen, todo, out = set(), list(link["needed"]), []
        while todo:
            name = todo.pop(0)
            if name in seen:
                continue
            seen.add(name)
            for p, l in elf_files.get(name, ()):
                out.append((p, l))
                todo += l["needed"]
        return out

    def elf_provider(link: dict, lib: str, sym: str):
        bare = sym.split("@", 1)[0]
        candidates = elf_files.get(lib, ()) if lib else elf_closure(link)
        return next((p for p, l in candidates if bare in l["exports"]), None)

    out = {k: [] for k in ("new_imports", "gone_imports", "new_needed", "gone_needed", "linkage_unreadable")}
    for path in sorted(set(pub) & set(cand)):
        a, b = pub[path], cand[path]
        if a["sha256"] == b["sha256"]:
            continue
        la, lb = a.get("linkage"), b.get("linkage")
        if la is None or lb is None or "error" in la or "error" in lb or (a["kind"] in ("elf", "so")) != (b["kind"] in ("elf", "so")):
            # a table that cannot be read is never a pass: red, but for a binary that could not be read in the published package either (reported)
            both = bool(la and lb and "error" in la and "error" in lb)
            out["linkage_unreadable"].append({"path": path, "published": (la or {"error": "not read"}).get("error", "read"),
                                              "candidate": (lb or {"error": "not read"}).get("error", "read"), "red": not both})
            continue
        if b["kind"] in ("elf", "so"):
            before, after = _elf_calls(la), _elf_calls(lb)
            provider = lambda lib, sym: elf_provider(lb, lib, sym)  # noqa: E731
            for lib in sorted(set(lb["needed"]) - set(la["needed"])):
                out["new_needed"].append({"path": path, "library": lib, "provider": next((p for p, _l in elf_files.get(lib, ())), None)})
            for lib in sorted(set(la["needed"]) - set(lb["needed"])):
                out["gone_needed"].append({"path": path, "library": lib})
        else:
            before, after = _pe_calls(la), _pe_calls(lb)
            provider = pe_provider
        for lib, sym in sorted(after - before):
            out["new_imports"].append({"path": path, "library": lib, "symbol": sym, "provider": provider(lib, sym)})
        for lib, sym in sorted(before - after):
            out["gone_imports"].append({"path": path, "library": lib, "symbol": sym})
    out["red"] = {
        "new_host_import": [r for r in out["new_imports"] if r["provider"] is None],
        "new_host_library": [r for r in out["new_needed"] if r["provider"] is None],
        "linkage_unreadable": [r for r in out["linkage_unreadable"] if r["red"]],
    }
    return out


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
    entry = {"path": path, "kind": kind_of(path, data[:8192]), "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    if entry["kind"] in LINKED_KINDS:
        entry["linkage"] = linkage(entry["kind"], data)
    return entry


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


# Records one of our builds writes into the package, and the files that build's key reads: a changed source among them explains the record.
OWN_BUILD_RECORDS = {"lavapipe/VERSION.json": lavapipe_build.INPUTS}


def _matches(src: str, pattern: str) -> bool:
    """A tree path against a tree path or a glob: segment by segment, so `*` never crosses `/` and the pattern is anchored at the root."""
    return len(PurePosixPath(src).parts) == len(PurePosixPath(pattern).parts) and PurePosixPath(src).match(pattern)


def _explained_by(path: str, sources) -> list:
    """The sources that explain a package file, sorted; [] when none does."""
    inside = path.rsplit("!", 1)[-1]
    base = posixpath.basename(inside)
    own = OWN_BUILD_RECORDS.get(inside, ())
    by = set()
    for src in sources:
        if src.startswith("juggler/") and inside == "modules/" + src:
            by.add(src)
        elif posixpath.basename(src) == base and base not in NOT_SHIPPED_NAMES and not src.lower().endswith(NOT_SHIPPED_AS_TEXT):
            by.add(src)
        elif any(_matches(src, pattern) for pattern in own):
            by.add(src)
    return sorted(by)


# ---------------------------------------------------------------- the content of a changed file: its diff, and the proof that it is build identity

def read_entries(archive: str, paths) -> dict:
    """{path: bytes} of the given paths of the archive ("<container>!<member>" for a member of a .ja), in one pass over it."""
    want = set(paths)
    containers = {p.split("!", 1)[0] for p in want if "!" in p}
    out = {}
    for name, data, _target in _files(archive):
        if data is None:
            continue
        if name in want:
            out[name] = data
        if name in containers:
            for inner, blob in read_jar(data):
                if name + "!" + inner in want:
                    out[name + "!" + inner] = blob
    return out


def _text(data: bytes) -> list:
    return data.decode("utf-8", "replace").splitlines()


def _mask(line: str):
    """(the line with the value of the token it carries replaced by <NAME>, the name), or (the line, None) when it carries none."""
    for name, rx in IDENTITY_TOKENS:
        m = rx.match(line)
        if m:
            return m.group("p") + "<" + name + ">" + m.group("s"), name
    return line, None


def build_identity(old: bytes, new: bytes) -> list:
    """The tokens that differ when the two texts differ in nothing else: the same number of lines, and every line that differs is a token line on both
    sides, the same line once its value is masked. [] otherwise. By the content of the lines, never by the name of the file."""
    a, b = _text(old), _text(new)
    if len(a) != len(b):
        return []
    tokens = set()
    for x, y in zip(a, b):
        if x == y:
            continue
        mx, nx = _mask(x)
        my, ny = _mask(y)
        if nx is None or mx != my:
            return []
        tokens.add(nx)
    return sorted(tokens)


def unified_diff(old: bytes, new: bytes, cap: int = DIFF_LINES) -> list:
    """The unified diff of two texts (one line of context), at most `cap` lines, each at most DIFF_LINE_CHARS characters, then a line saying how many more."""
    lines = list(difflib.unified_diff(_text(old), _text(new), "published", "candidate", n=1, lineterm=""))
    out = [l if len(l) <= DIFF_LINE_CHARS else l[:DIFF_LINE_CHARS] + "..." for l in lines[:cap]]
    if len(lines) > cap:
        out.append("... %d more lines" % (len(lines) - cap))
    return out


# ---------------------------------------------------------------- compare

def compare(published: dict, candidate: dict, sources=(), published_archive=None, candidate_archive=None, expect_identical=False) -> dict:
    """The A/B of two lists. The archives (when given) are read for the content of the changed text files: their diff and the proof of build identity."""
    pub = {e["path"]: e for e in published["entries"]}
    cand = {e["path"]: e for e in candidate["entries"]}
    out = {k: [] for k in ("added", "missing", "changed_binary", "changed_ja_entry", "changed_build_identity", "changed_non_binary")}
    same = 0
    changed = []
    for path in sorted(set(pub) | set(cand)):
        a, b = pub.get(path), cand.get(path)
        if a is None:
            out["added"].append({"path": path, "kind": b["kind"], "explained": _explained_by(path, sources)})
        elif b is None:
            out["missing"].append({"path": path, "kind": a["kind"], "explained": _explained_by(path, sources)})
        elif a["sha256"] == b["sha256"] and a["kind"] == b["kind"]:
            same += 1
        else:
            changed.append((path, a, b))
    # the content of the changed text files, one pass over each archive
    texts = [p for p, a, b in changed if a["kind"] == "text" and b["kind"] == "text" and max(a["size"], b["size"]) <= MAX_DIFF_BYTES]
    old_data = read_entries(published_archive, texts) if published_archive and texts else {}
    new_data = read_entries(candidate_archive, texts) if candidate_archive and texts else {}
    for path, a, b in changed:
        row = {"path": path, "kind": b["kind"], "was": a["kind"], "size": [a["size"], b["size"]], "explained": _explained_by(path, sources)}
        compiled = a["kind"] in BINARY_KINDS and b["kind"] in BINARY_KINDS
        row["build_identity"] = []
        if path in old_data and path in new_data:
            row["diff"] = unified_diff(old_data[path], new_data[path])
            row["build_identity"] = build_identity(old_data[path], new_data[path])
        # green when the build wrote the whole difference (proved by the content) or a source of ours explains it; compiled files are only reported
        row["red"] = not compiled and not row["build_identity"] and not row["explained"]
        if "!" in path:
            out["changed_ja_entry"].append(row)
        elif compiled:
            out["changed_binary"].append(row)
        elif row["build_identity"]:
            out["changed_build_identity"].append(row)
        else:
            out["changed_non_binary"].append(row)
    links = linkage_ab(published, candidate)
    red = {"added": [r for r in out["added"] if not r["explained"]], "missing": out["missing"],
           "changed_non_binary_unexplained": [r for r in out["changed_non_binary"] if r["red"]],
           "changed_ja_entry_unexplained": [r for r in out["changed_ja_entry"] if r["red"]]}
    red.update(links.pop("red"))
    report = {"published": published.get("archive"), "candidate": candidate.get("archive"), "unchanged": same, "sources_named": len(sources)}
    report.update(out)
    report.update(links)
    report["counts"] = {k: len(v) for k, v in out.items()}
    report["counts"].update({k: len(v) for k, v in links.items()})
    report["counts"]["unchanged"] = same
    if expect_identical:  # the A/A: a package against itself changes nothing, in any class
        red["not_identical"] = ["%s %d" % (k, n) for k, n in report["counts"].items() if k != "unchanged" and n]
    report["red"] = {k: len(v) for k, v in red.items() if v}
    report["verdict"] = "red" if report["red"] else "green"
    return report


def summary(report: dict, limit: int = 40) -> str:
    lines = ["package A/B: %s -> %s: %s" % (report["published"], report["candidate"], report["verdict"].upper())]
    lines.append("  " + ", ".join("%s %d" % (k.replace("_", " "), n) for k, n in report["counts"].items()) + "; %d sources named" % report["sources_named"])
    if report["red"]:
        lines.append("  red: " + ", ".join("%s %d" % (k.replace("_", " "), n) for k, n in report["red"].items()))
    for key in ("added", "missing", "changed_non_binary", "changed_build_identity", "changed_ja_entry"):
        for row in report[key][:limit]:
            if key in ("added", "missing") and not row["explained"]:
                mark = "  <-- RED"
            elif key in ("added", "missing"):
                mark = "  (explained by %s)" % ", ".join(row["explained"])
            elif row.get("build_identity"):
                mark = "  (build identity: %s)" % ", ".join(row["build_identity"])
            elif row["explained"]:
                mark = "  (explained by %s)" % ", ".join(row["explained"])
            elif row["red"]:
                mark = "  <-- RED: no source of ours explains it and its differing lines are not build identity"
            else:
                mark = "  (reported)"
            lines.append("  %-22s %s [%s]%s" % (key.replace("_", " "), row["path"], row["kind"], mark))
            lines += ["      | " + d for d in row.get("diff", ())]
        if len(report[key]) > limit:
            lines.append("  %s: %d more in the report" % (key, len(report[key]) - limit))
    lines.append("  changed binaries (reported): %d" % report["counts"]["changed_binary"])
    # the calls into libraries, both directions: a new one into the host is red, a new one the package answers and a gone one are reported
    for key, label in (("new_imports", "new import"), ("new_needed", "new library"), ("gone_imports", "gone import"), ("gone_needed", "gone library"),
                       ("linkage_unreadable", "unreadable table")):
        rows = report.get(key, [])
        for row in rows[:limit]:
            if key == "linkage_unreadable":
                what, mark = "published: %s; candidate: %s" % (row["published"], row["candidate"]), "  <-- RED" if row["red"] else "  (reported)"
            else:
                what = "%s %s" % (row["library"] or "(unversioned)", row["symbol"]) if "symbol" in row else row["library"]
                if key.startswith("new"):
                    host = "  <-- RED: a new call into the host" if "symbol" in row else "  <-- RED: a new library of the host"
                    mark = host if row["provider"] is None else "  (inside the package: %s)" % row["provider"]
                else:
                    mark = "  (reported)"
            lines.append("  %-16s %s: %s%s" % (label, row["path"], what, mark))
        if len(rows) > limit:
            lines.append("  %s: %d more in the report" % (label, len(rows) - limit))
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
    p.add_argument("--output-name", default="series_commit", help="the name of the output that carries the series commit of the seal")
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
    p.add_argument("--published-archive", help="the archive the published list was made from (default: the first argument when it is an archive)")
    p.add_argument("--candidate-archive", help="the archive the candidate list was made from (default: the second argument when it is an archive)")
    p.add_argument("--expect-identical", action="store_true", help="the A/A: red when anything changed, of any class")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "seal-check":
            result = seal_check(a.directory)
            for problem in result["problems"]:
                print("ab_package: " + problem, file=sys.stderr)
            print("%s: series %s, source %s, %d assets, %d problems" % (result["tag"], result["series_commit"], result["source_commit"], len(result["assets"]), len(result["problems"])))
            if a.github_output and not result["problems"]:
                with open(a.github_output, "a", encoding="utf-8", newline="\n") as f:
                    f.write("%s=%s\n" % (a.output_name, result["series_commit"]))
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
            result = compare(_load(a.published), _load(a.candidate), sources,
                             a.published_archive or (None if a.published.endswith(".json") else a.published),
                             a.candidate_archive or (None if a.candidate.endswith(".json") else a.candidate), a.expect_identical)
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
