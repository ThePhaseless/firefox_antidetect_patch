r"""The verdict of the cargo job: the unit tests of OUR Rust code in WebRender ran, and passed.

Our Rust lives in a few Mozilla files (gfx/wr, dom/media/webrtc/transport/mdns_service), with #[cfg(test)] modules and tests of our own. No other round runs them: gtests are the C++ ones. The job
`cargo-tests` of .github/workflows/cargo-tests.yml runs only those modules (libtest filters by name) and writes the log; this reads the log. A run
whose filters matched nothing is green for cargo (`0 passed`), so the verdict is red unless every module of ours reported at least its floor of
tests, each `ok`, and the run ended with no failed and no ignored test.

    python3 scripts/ci/cargo_oracles.py verdict cargo-test.log

Exit 0 when green, 1 and one line per reason when red.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

#: The modules of ours, as the path libtest prints (`test <path> ... ok`), and the least number of tests each must report. Raise a floor when a
#: test is added; lower it never. The first is in the crate `webrender` (render_backend.rs), the second in `wr_glyph_rasterizer` (rasterizer.rs).
OURS = {
    "render_backend::clear_namespace_tests::": 2,
    "rasterizer::test_shared_fonts_clear_namespace::": 3,
    # mdns_service: the module `stealth_tests` of ours (src/stealth_tests.rs, declared in lib.rs by `#[cfg(test)] mod stealth_tests;`); its floor is the count of #[test]
    # in that file. A tree without the file reports `0 passed` and is red: the job is for the tree where the branch hooks/fingerprint__webrtc__declared-network is merged.
    "stealth_tests::": 1,
}
#: The libtest filters that select exactly those modules (a substring of the full path).
FILTERS = ("clear_namespace_tests", "test_shared_fonts_clear_namespace")
#: The filter of the second run (`cargo test --lib`, in the directory of mdns_service).
MDNS_FILTERS = ("stealth_tests::",)

LINE = re.compile(r"^test (\S+) \.\.\. (\S+)", re.M)
RESULT = re.compile(r"^test result: (\w+)\. (\d+) passed; (\d+) failed; (\d+) ignored;", re.M)


def judge(log: str, ours: dict = OURS) -> list:
    """The reasons the run is red, one string each; empty when it is green."""
    lines = LINE.findall(log)
    reasons = []
    for prefix, floor in sorted(ours.items()):
        mine = [(path, how) for path, how in lines if prefix in path]
        ok = [path for path, how in mine if how == "ok"]
        if len(ok) < floor:
            reasons.append("%s: %d tests passed, the floor is %d" % (prefix, len(ok), floor))
        for path, how in mine:
            if how != "ok":
                reasons.append("%s is %s" % (path, how))
    # A test of the run that is not ours and ran anyway is a filter that grew: said, not failed. A failure or an ignored test anywhere is red.
    for status, passed, failed, ignored in RESULT.findall(log):
        if status != "ok" or int(failed) or int(ignored):
            reasons.append("a test binary ended %s (%s failed, %s ignored)" % (status, failed, ignored))
    if not RESULT.search(log):
        reasons.append("no `test result:` line: cargo did not run a test binary")
    return reasons


def main(argv) -> int:
    if len(argv) != 2 or argv[0] != "verdict":
        print(__doc__, file=sys.stderr)
        return 2
    log = Path(argv[1]).read_text(encoding="utf-8", errors="replace")
    reasons = judge(log)
    ran = sum(1 for path, how in LINE.findall(log) if any(p in path for p in OURS) and how == "ok")
    if reasons:
        for r in reasons:
            print("RED: %s" % r)
        return 1
    print("ok: %d tests of ours passed in %d modules" % (ran, len(OURS)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
