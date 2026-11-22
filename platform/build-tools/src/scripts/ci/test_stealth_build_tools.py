# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""The build-tool hooks of python/mozbuild (platform/build-tools).

Run from the tree: `python3 scripts/ci/test_stealth_build_tools.py`. It imports
mozbuild from the tree (python/mozbuild and the vendored packages it needs), so it
needs the whole source tree, not a sparse one.
"""

import glob
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for pattern in ("python/*", "testing/mozbase/*", "third_party/python/*", "config"):
    for d in sorted(glob.glob(os.path.join(ROOT, pattern))):
        if os.path.isdir(d):
            sys.path.append(d)

import mozbuild.jar  # noqa: E402
from mozbuild.frontend.data import UnifiedSources  # noqa: E402
from mozbuild.stealth_build_tools import (  # noqa: E402
    stealth_absolute_object_path,
    stealth_long_path,
)

EXTENDED_PREFIX = "\\\\?\\"


class AbsoluteObjectPathsTest(unittest.TestCase):
    def test_the_link_rule_lists_the_absolute_path_not_the_relative_one(self):
        # recursivemake.py: join(stealth_absolute_object_path(o, os.path.relpath(o, obj.objdir)) for o in objs)
        objdir = os.path.join(ROOT, "obj", "dom")
        obj = os.path.join(ROOT, "obj", "dom", "sub", "x.o")
        relative = os.path.relpath(obj, objdir)
        # Mozilla's own value is the relative one: the hook is what changes it.
        self.assertNotEqual(relative, obj)
        self.assertEqual(stealth_absolute_object_path(obj, relative), obj)
        self.assertTrue(os.path.isabs(stealth_absolute_object_path(obj, relative)))


class LongPathTest(unittest.TestCase):
    PATH = os.path.join("dist", "bin", "x" * 200, "y" * 80 + ".css")

    def test_windows_gets_the_extended_prefix_and_backslashes_only(self):
        with mock.patch.object(os, "name", "nt"):
            got = stealth_long_path(self.PATH)
        self.assertTrue(got.startswith(EXTENDED_PREFIX))
        self.assertNotIn("/", got)
        self.assertEqual(got[len(EXTENDED_PREFIX):], os.path.abspath(self.PATH).replace("/", "\\"))

    def test_every_other_platform_keeps_the_path(self):
        with mock.patch.object(os, "name", "posix"):
            self.assertEqual(stealth_long_path(self.PATH), self.PATH)


class JarFlatOutputTest(unittest.TestCase):
    """The host line: JarMaker.OutputHelper_flat.getOutput of mozbuild/jar.py."""

    def test_the_removal_takes_the_path_mozilla_computed_and_the_open_takes_the_hooked_one(self):
        with tempfile.TemporaryDirectory() as base:
            helper = mozbuild.jar.JarMaker.OutputHelper_flat(base)
            plain = os.path.join(base, "dir/f.css")  # as ensureDirFor joins it
            removed, opened = [], []

            def fake_remove(path):
                removed.append(path)
                raise FileNotFoundError(2, "gone")  # ENOENT, as for a file that was not there

            def fake_open(path, *args, **kwargs):
                opened.append(path)
                return mock.MagicMock()

            with mock.patch.object(
                mozbuild.jar, "stealth_long_path", lambda p: "LONG:" + p
            ), mock.patch.object(mozbuild.jar.os, "remove", fake_remove), mock.patch.object(
                mozbuild.jar, "open", fake_open, create=True
            ):
                helper.getOutput("dir/f.css")
            # A file that stayed before is not removed through the long path.
            self.assertEqual(removed, [plain])
            self.assertEqual(opened, ["LONG:" + plain])

    def test_getOutput_writes_the_file_in_the_directory(self):
        with tempfile.TemporaryDirectory() as base:
            helper = mozbuild.jar.JarMaker.OutputHelper_flat(base)
            with helper.getOutput("a/b.txt", "w") as f:
                f.write("x")
            with open(os.path.join(base, "a", "b.txt")) as f:
                self.assertEqual(f.read(), "x")


class FakeConfig:
    topsrcdir = "/src"
    topobjdir = "/obj"
    substs = {"ENABLE_UNIFIED_BUILD": True}


class FakeContext:
    config = FakeConfig()
    main_path = "/src/moz.build"
    all_paths = ["/src/moz.build"]
    srcdir = "/src/x"
    objdir = "/obj/x"

    def __init__(self, relsrcdir):
        self.relsrcdir = relsrcdir

    def get(self, name, default=None):
        return default


def unified_name(relsrcdir):
    sources = UnifiedSources(FakeContext(relsrcdir), ["a.cpp", "b.cpp"], [], ".cpp")
    return sources.unified_source_mapping[0][0]


class UnifiedNamesTest(unittest.TestCase):
    # libwebrtc: two directories whose last 20 characters are the same.
    A = "third_party/libwebrtc/modules/congestion_controller/goog_cc_scream_network_controller_gn"
    B = "third_party/libwebrtc/modules/congestion_controller/scream_network_controller_gn"

    def test_two_directories_that_collided_at_20_characters_get_two_names(self):
        # The case is real: Mozilla's 20 would give both the same prefix.
        self.assertEqual(self.A[-20:].split("/", 1)[-1], self.B[-20:].split("/", 1)[-1])
        self.assertNotEqual(unified_name(self.A), unified_name(self.B))

    def test_a_short_directory_keeps_its_whole_name(self):
        self.assertEqual(unified_name("dom/base"), "Unified_cpp_dom_base0.cpp")


if __name__ == "__main__":
    unittest.main()
