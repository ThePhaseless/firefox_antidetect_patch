#!/usr/bin/env python3
"""The .mozconfig of the coverage build of diagnostics.yml, composed with the layers of scripts/ci/mozconfig.py.

    python3 scripts/ci/coverage_mozconfig.py --compile-cache gha|off [--sccache PATH] [--parallel N]     (rewrites ./.mozconfig, prints it)

Linux x86_64 only, an opt build with `--enable-coverage` (gcov-style: `--coverage` in every C and C++ compile, the tree's own switch), no LTO and no
PGO. The layers are release's own for the compile cache, the platform and the machine (the objdir stays obj-rel); the `symbols` and `toolchain`
layers, which are the retail's PGO profile and full LTO, are replaced by the one below. What it takes from Mozilla's coverage mozconfigs
(browser/config/mozconfigs/linux64/code-coverage and code-coverage-opt): warnings are not errors (the instrumented code warns where the plain one
does not), the wasm-sandboxed libraries are not built (their wasi toolchain does not take --coverage), and lld is asked for --no-fortran-common
(LLD 12 changed what coverage builds link). What it does not take: `--disable-sandbox` (the sandbox stays compiled, so the files of the sandbox
are measured; the suites switch it off at run time, see diagnostics.yml), and the -Zprofile flags of Rust (they need a nightly rustc: Rust is not
instrumented, and the map says so for the hooks written in it).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import legs  # noqa: E402
import mozconfig  # noqa: E402

LEG = "linux-x86_64"


def coverage(leg, plan) -> mozconfig.Layer:
    return mozconfig.Layer("coverage", (
        "gcov-style coverage of every C and C++ object (--enable-coverage: --coverage in each compile, and the tree's own handling of it: no fast "
        "shutdown, NS_FREE_PERMANENT_DATA, so a child process writes its counters at exit), an opt build with no LTO and no PGO, built only to "
        "measure and never shipped (scripts/ci/coverage_mozconfig.py says what is and is not taken from Mozilla's coverage mozconfigs)."), [
        "ac_add_options --enable-coverage",
        "ac_add_options --disable-lto",
        "ac_add_options --disable-warnings-as-errors",
        "ac_add_options --without-wasm-sandboxed-libraries",
        'export LDFLAGS="$LDFLAGS -Wl,--no-fortran-common"'])


LAYERS = (mozconfig.cache, coverage, mozconfig.platform, mozconfig.machine)


def compose(base: str, plan: mozconfig.Plan) -> str:
    leg = legs.by_name(LEG)
    kept = [line for line in base.splitlines() if not mozconfig._SCCACHE_ACTIVE.match(line)]
    out = kept + ["", "# --- diagnostics CI layers for the coverage build of %s (never published) ---" % leg.leg]
    for make in LAYERS:
        layer = make(leg, plan)
        out.append("# [%s] %s" % (layer.name, layer.why))
        out.extend(layer.lines)
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--compile-cache", required=True, choices=("gha", "off"))
    ap.add_argument("--sccache", default=os.environ.get("SCCACHE_PATH", ""))
    ap.add_argument("--parallel", type=int, default=int(os.environ.get("CI_PARALLEL") or 4))
    a = ap.parse_args(argv)
    path = Path(".mozconfig")
    if not path.is_file():
        print("ERROR: no .mozconfig in the source", file=sys.stderr)
        return 1
    text = compose(path.read_text(encoding="utf-8"), mozconfig.Plan(a.compile_cache, a.sccache, parallel=a.parallel))
    path.write_text(text, encoding="utf-8", newline="\n")
    print("----- final .mozconfig (coverage) -----")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
