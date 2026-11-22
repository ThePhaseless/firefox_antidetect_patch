#!/usr/bin/env python3
"""scripts/ci/cargo_junit.py against the logs `cargo test` writes: one junit per test binary, a testcase per test named as cargo prints it.

The named hook tests judge reads `junit-cargo/*.xml` (a hook `cargo:<crate>::<test path>` is judged on the testcase named <test path> whose classname has
the crate). The cases are the red ones first: a failed test is a failure with its message, an ignored one is skipped (never a pass), a log with no test
binary writes nothing (the judge is red for want of the test, not green), a crate named with a hyphen is found by the hyphenated name.

    python3 scripts/ci/test_cargo_junit.py
"""
from __future__ import annotations

import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cargo_junit as cj  # noqa: E402

LINUX = """   Compiling webrender v0.62.0 (/work/gfx/wr/webrender)
    Finished `test` profile [unoptimized] target(s) in 4m 02s
     Running unittests src/lib.rs (target/debug/deps/webrender-3f9a1c2b4d5e6f70)

running 2 tests
test render_backend::clear_namespace_tests::drops_shared_fonts ... ok
test render_backend::clear_namespace_tests::keeps_other_namespaces ... ok

test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 140 filtered out; finished in 0.00s

     Running unittests src/lib.rs (target/debug/deps/wr_glyph_rasterizer-0a1b2c3d4e5f6071)

running 3 tests
test rasterizer::test_shared_fonts_clear_namespace::one ... ok
test rasterizer::test_shared_fonts_clear_namespace::two ... ok
test rasterizer::test_shared_fonts_clear_namespace::three ... ok

test result: ok. 3 passed; 0 failed; 0 ignored; 0 measured; 9 filtered out; finished in 0.01s

   Doc-tests webrender

running 0 tests

test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s
"""

WINDOWS = LINUX.replace("target/debug/deps/webrender-3f9a1c2b4d5e6f70", "target\\debug\\deps\\webrender-3f9a1c2b4d5e6f70.exe") \
    .replace("target/debug/deps/wr_glyph_rasterizer-0a1b2c3d4e5f6071", "D:\\a\\x\\gfx\\wr\\target\\debug\\deps\\wr_glyph_rasterizer-0a1b2c3d4e5f6071.exe") \
    .replace("\n", "\r\n")

RED = """     Running unittests src/lib.rs (target/debug/deps/wgpu_core-00112233aabbccdd)

running 3 tests
test tests::it_ok ... ok
test tests::it_fails ... FAILED
test tests::it_waits ... ignored, needs a GPU

failures:

---- tests::it_fails stdout ----
thread 'tests::it_fails' panicked at src/lib.rs:12:9:
assertion `left == right` failed: <a> & <b>
  left: 1
 right: 2

failures:
    tests::it_fails

test result: FAILED. 1 passed; 1 failed; 1 ignored; 0 measured; 0 filtered out; finished in 0.00s
"""


def parse_dir(directory: Path) -> dict:
    """{file name: [(classname, name, outcome)]} of the junit files in a folder."""
    out = {}
    for path in sorted(Path(directory).glob("*.xml")):
        cases = []
        for case in ET.parse(str(path)).getroot().iter("testcase"):
            tags = {c.tag for c in case}
            cases.append((case.get("classname"), case.get("name"), "failed" if "failure" in tags else "skipped" if "skipped" in tags else "passed"))
        out[path.name] = cases
    return out


def judge_finds(cases: dict, crate: str, test: str) -> list:
    """The outcomes the judge (hook_tests_judge.judge_cargo) would find for `cargo:<crate>::<test>`."""
    leaf = test.rsplit("::", 1)[-1]
    return [o for found in cases.values() for c, n, o in found if (crate in c or crate in n) and n in (test, leaf, "%s::%s" % (crate, test))]


def cases() -> list:
    out = []

    def add(name, ok):
        out.append(("cargo_junit: " + name, bool(ok)))

    with tempfile.TemporaryDirectory() as tmp:
        written = cj.write(LINUX, Path(tmp) / "j", [])
        got = parse_dir(Path(tmp) / "j")
        add("a log of two crates writes one junit per test binary, named by the binary (the doc-tests of an empty crate have a file with no testcase)",
            sorted(got) == ["webrender-doc.xml", "webrender.xml", "wr_glyph_rasterizer.xml"] and len(written) == 3)
        add("each testcase is named by the test path as cargo prints it and classed by the crate, all passed",
            got["webrender.xml"] == [("webrender", "render_backend::clear_namespace_tests::drops_shared_fonts", "passed"),
                                     ("webrender", "render_backend::clear_namespace_tests::keeps_other_namespaces", "passed")]
            and [n for _, n, _ in got["wr_glyph_rasterizer.xml"]] == ["rasterizer::test_shared_fonts_clear_namespace::" + w for w in ("one", "two", "three")])
        add("the judge's lookup finds a test of ours by crate and full path, and none that does not exist",
            judge_finds(got, "webrender", "render_backend::clear_namespace_tests::drops_shared_fonts") == ["passed"]
            and judge_finds(got, "wr_glyph_rasterizer", "rasterizer::test_shared_fonts_clear_namespace::two") == ["passed"] and judge_finds(got, "webrender", "no_such_test") == [])

    with tempfile.TemporaryDirectory() as tmp:
        cj.write(WINDOWS, Path(tmp) / "j", [])
        got = parse_dir(Path(tmp) / "j")
        add("a Windows log (CRLF, backslashes, .exe) reads the same: the binaries' names are the crates'",
            sorted(got) == ["webrender-doc.xml", "webrender.xml", "wr_glyph_rasterizer.xml"] and all(o == "passed" for f in got.values() for _, _, o in f)
            and len(got["wr_glyph_rasterizer.xml"]) == 3 and all(n == n.strip() for f in got.values() for _, n, _ in f))

    with tempfile.TemporaryDirectory() as tmp:
        cj.write(RED, Path(tmp) / "j", ["wgpu-core"])
        got = parse_dir(Path(tmp) / "j")
        root = ET.parse(str(Path(tmp) / "j" / "wgpu_core.xml")).getroot()
        failure = root.find(".//failure")
        add("a failed test is a failure, an ignored one is skipped, an ok one passes: none of them is read as the other",
            got["wgpu_core.xml"] == [("wgpu-core", "tests::it_ok", "passed"), ("wgpu-core", "tests::it_fails", "failed"), ("wgpu-core", "tests::it_waits", "skipped")])
        add("the failure carries the panic message of its `---- <test> stdout ----` block (XML-escaped), and not the lines after `failures:`",
            failure is not None and "left == right" in failure.text and "<a> & <b>" in failure.text and "test result" not in failure.text
            and "tests::it_fails\n" not in failure.text.split("right: 2")[-1])
        add("--packages names the crate with the hyphen (a hook says `wgpu-core`, the binary is wgpu_core) and the judge finds the failed one as failed",
            judge_finds(got, "wgpu-core", "tests::it_fails") == ["failed"] and judge_finds(got, "wgpu-core", "tests::it_waits") == ["skipped"])
        add("the counts of the suite are the testcases' (3 tests, 1 failure, 1 skipped)",
            root.find("testsuite").get("tests") == "3" and root.find("testsuite").get("failures") == "1" and root.find("testsuite").get("skipped") == "1")

    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "cargo-test.log"
        log.write_text("error: could not compile `webrender`\n", encoding="utf-8")
        code = cj.main([str(log), "--out", str(Path(tmp) / "j")])
        add("a log with no test binary (a cargo that did not get to run one) exits 1 and writes nothing, so the judge finds no test and is red",
            code == 1 and not (Path(tmp) / "j").exists())
        add("a log that does not exist exits 2", cj.main([str(Path(tmp) / "none.log"), "--out", str(Path(tmp) / "j")]) == 2)
        log.write_text(LINUX, encoding="utf-8")
        code = cj.main([str(log), "--out", str(Path(tmp) / "j"), "--packages", "webrender,wr_glyph_rasterizer"])
        add("main with a log and --packages writes the files and exits 0", code == 0 and len(list((Path(tmp) / "j").glob("*.xml"))) == 3)

    with tempfile.TemporaryDirectory() as tmp:
        twice = LINUX + "\n     Running unittests src/main.rs (target/debug/deps/webrender-ffeeddccbbaa9988)\n\nrunning 1 test\ntest main_one ... ok\n"
        cj.write(twice, Path(tmp) / "j", [])
        add("two test binaries of one name do not overwrite each other", sorted(p.name for p in (Path(tmp) / "j").glob("*.xml"))
            == ["webrender-2.xml", "webrender-doc.xml", "webrender.xml", "wr_glyph_rasterizer.xml"])
    return out


if __name__ == "__main__":
    results = cases()
    for label, ok in results:
        print(("ok    " if ok else "FAIL  ") + label)
    print("%d/%d cases as expected" % (sum(ok for _, ok in results), len(results)))
    sys.exit(0 if all(ok for _, ok in results) else 1)
