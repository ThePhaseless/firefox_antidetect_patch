#!/usr/bin/env python3
# SPDX-License-Identifier: 0BSD
"""linux-arm64 against linux-x86_64, leaf by leaf, on the host gate's dumps.

The wrapper's compare() checks every leg against win-x86_64 and has no Linux-vs-Linux
check, so this is the one that holds arm64 to x86 on every key the gate holds to host
independence. It reads the dumps and the exceptions with the wrapper's own helpers
(leaves, is_diag, load_exceptions, matching, describe) and drops diag. keys only, as
compare() does. Keys the gate excuses on every leg (noise, network, measurement) and
keys in the --allow file are listed as equal or differs and never fail.

    leaf_diff.py --wrapper <invisible_playwright checkout> --dumps host-dump --allow leaf_diff_allow.json
    leaf_diff.py --wrapper <checkout> --selftest

Exit 0: no failures; 1: a checked key differs or is on one side only; 2: a leg has no dumps.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import tempfile
from pathlib import Path

ARM, X86 = "linux-arm64", "linux-x86_64"
MISSING = "<missing>"


def gate_module(wrapper: Path):
    sys.path.insert(0, str(wrapper / "scripts"))
    import ci_host_gate
    return ci_host_gate


def load_allow(path: Path) -> list:
    entries = json.loads(path.read_text(encoding="utf-8"))
    for e in entries:
        if not e.get("keys") or not e.get("why"):
            raise SystemExit("%s: every entry needs keys and why" % path)
    return entries


def load_visits(g, dumps: Path) -> dict:
    visits = {}
    for path in sorted(dumps.glob("*.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        if d["leg"] in (ARM, X86):
            visits[(d["leg"], d["dpr"], d["seed"])] = {
                k: v for k, v in g.leaves(d["result"]["items"]).items() if not g.is_diag(k)}
    return visits


def pixels(a, b) -> str:
    """For two raw images of one shape: differing pixels, max channel delta, first 5 (x,y)."""
    if not (isinstance(a, dict) and isinstance(b, dict) and a.get("enc") == b.get("enc")
            and a.get("enc") in ("rgba8", "alpha8") and (a.get("w"), a.get("h")) == (b.get("w"), b.get("h"))):
        return ""
    x, y = base64.b64decode(a["data"]), base64.b64decode(b["data"])
    if len(x) != len(y):
        return ""
    ch, w = (4 if a["enc"] == "rgba8" else 1), a["w"]
    bad = {}
    for i, (p, q) in enumerate(zip(x, y)):
        if p != q:
            bad[i // ch] = max(bad.get(i // ch, 0), abs(p - q))
    first = ", ".join("(%d,%d)" % (i % w, i // w) for i in sorted(bad)[:5])
    return "; %d of %d pixels differ, max channel delta %d, first at %s" % (
        len(bad), len(x) // ch, max(bad.values(), default=0), first)


def diff(g, visits: dict, exceptions: dict, allow: list) -> dict:
    excusable = exceptions.get("noise", []) + exceptions.get("network", []) + exceptions.get("measurement", [])
    out = {"gate": [], "allow": [], "fail": [], "equal": 0, "visits": 0}
    arm = {(dpr, s) for leg, dpr, s in visits if leg == ARM}
    x86 = {(dpr, s) for leg, dpr, s in visits if leg == X86}
    for dpr, seed in sorted(arm ^ x86):
        out["fail"].append(("dpr %s seed %d" % (dpr, seed), "<visit>",
                            "only on %s" % (ARM if (dpr, seed) in arm else X86)))
    for dpr, seed in sorted(arm & x86):
        out["visits"] += 1
        where = "dpr %s seed %d" % (dpr, seed)
        a, x = visits[(ARM, dpr, seed)], visits[(X86, dpr, seed)]
        for key in sorted(set(a) | set(x)):
            va, vx = a.get(key, MISSING), x.get(key, MISSING)
            state = "equal" if va == vx else "differs: " + g.describe(va, vx) + pixels(va, vx)
            if g.matching(excusable, key):
                out["gate"].append((where, key, state))
            elif g.matching(allow, key):
                out["allow"].append((where, key, state))
            elif va == vx:
                out["equal"] += 1
            else:
                out["fail"].append((where, key, state))
    return out


def report(result: dict) -> None:
    print("leaf diff %s against %s: %d visits, %d checked leaves equal, %d failures"
          % (ARM, X86, result["visits"], result["equal"], len(result["fail"])))
    for title, rows in (("allowed (gate excuses on every leg)", result["gate"]),
                        ("allowed (--allow)", result["allow"]),
                        ("FAILED (checked)", result["fail"])):
        print("\n== %s: %d" % (title, len(rows)))
        for where, key, state in rows:
            print("  %s  %s: %s" % (where, key, state))


def run(wrapper: Path, dumps: Path, allow_path: Path) -> int:
    g = gate_module(wrapper)
    exceptions = g.load_exceptions(wrapper / "scripts" / "host_gate" / "exceptions.json")
    visits = load_visits(g, dumps)
    legs = {leg for leg, _, _ in visits}
    if {ARM, X86} - legs:
        print("no dumps in %s for %s" % (dumps, ", ".join(sorted({ARM, X86} - legs))))
        return 2
    result = diff(g, visits, exceptions, load_allow(allow_path))
    report(result)
    return 1 if result["fail"] else 0


def selftest(wrapper: Path) -> int:
    g = gate_module(wrapper)
    img = lambda px: {"w": 2, "h": 1, "enc": "rgba8", "data": base64.b64encode(bytes(px)).decode()}
    base = {"surface": {"document": {"hasFocus": False}, "audio": {"sum": 1.5}},
            "control": {"webgl1": img([1] * 8), "rects": img([9] * 8)},
            "diag": {"webgl": "llvmpipe"}}
    allow = [{"keys": ["control.webgl1", "control.webgl2"], "why": "test"}]
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        exc = tmp / "exceptions.json"
        exc.write_text(json.dumps({"identity": [], "noise": [], "network": [], "known_defects": [],
                                   "measurement": [{"keys": ["surface.document.hasFocus"], "why": "test"}]}))
        exceptions = g.load_exceptions(exc)

        def case(change):
            d = tmp / ("d%d" % len(list(tmp.iterdir())))
            d.mkdir()
            arm = json.loads(json.dumps(base))
            change(arm)
            for leg, items in ((ARM, arm), (X86, base)):
                (d / ("%s_dpr1.0_seed11.json" % leg)).write_text(
                    json.dumps({"leg": leg, "dpr": 1.0, "seed": 11, "result": {"items": items}}))
            return diff(g, load_visits(g, d), exceptions, allow)

        def keys(rows, state=None):
            return [k for _, k, s in rows if state is None or s.startswith(state)]

        equal = case(lambda i: None)
        checked = case(lambda i: i["control"].update(rects=img([9, 9, 9, 9, 9, 7, 9, 9])))
        allowed = case(lambda i: i["control"].update(webgl1=img([2] * 8)))
        focus = case(lambda i: i["surface"]["document"].update(hasFocus=True))
        diag = case(lambda i: i["diag"].update(webgl="other"))
        one_sided = case(lambda i: i["surface"]["audio"].update(extra=1))
        cases = [
            ("equal inputs pass", not equal["fail"] and equal["equal"] == 2),
            ("a differing checked key fails, with its pixels",
             keys(checked["fail"]) == ["control.rects"]
             and "1 of 2 pixels differ, max channel delta 2, first at (1,0)" in checked["fail"][0][2]),
            ("a differing --allow key passes and is listed as differs",
             not allowed["fail"] and keys(allowed["allow"], "differs") == ["control.webgl1"]),
            ("a measurement-excused key that differs passes, listed as gate-excused",
             not focus["fail"] and keys(focus["gate"], "differs") == ["surface.document.hasFocus"]),
            ("a diag. key that differs is ignored and not listed",
             not diag["fail"] and not any(k.startswith("diag.") for r in ("gate", "allow") for k in keys(diag[r]))),
            ("a key on one side only fails", keys(one_sided["fail"]) == ["surface.audio.extra"]),
        ]
    for name, ok in cases:
        print(("ok    " if ok else "FAIL  ") + name)
    return 0 if all(ok for _, ok in cases) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--wrapper", type=Path, required=True, help="invisible_playwright checkout (scripts/ci_host_gate.py)")
    ap.add_argument("--dumps", type=Path, help="the merged host-dump-* artifacts")
    ap.add_argument("--allow", type=Path, help="JSON list of {keys, why}: listed, never failing")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest(a.wrapper)
    if not a.dumps or not a.allow:
        ap.error("--dumps and --allow are required without --selftest")
    return run(a.wrapper, a.dumps, a.allow)


if __name__ == "__main__":
    sys.exit(main())
