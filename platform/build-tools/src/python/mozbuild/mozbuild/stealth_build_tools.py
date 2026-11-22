# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

# Build-tool fixes of the engine's tree. Each function is called by one hook in
# a Mozilla file of python/mozbuild (platform/build-tools); nothing here reads
# or changes what a page sees.

import os


def stealth_absolute_object_path(absolute, relative):
    """The object path the link rules of RecursiveMakeBackend list: the
    absolute one, on every platform and every build, instead of `relative`
    (the path Mozilla lists, relative to the object directory).

    mozmake 4.4.1 on Win32 fails on relative paths over about 150 characters
    (libwebrtc's deeply nested objects); an absolute path bypasses the bug and
    the linker accepts either. The hook passes Mozilla's own expression as
    `relative`, so it is still evaluated; its value is not used.
    """
    return absolute


def stealth_long_path(path):
    """The path JarMaker's flat output opens, as a Windows long path (the
    absolute path with backslashes only, behind the extended-length prefix) where
    os.name is "nt", else `path` unchanged.

    The webcompat built-in add-ons have CSS file names long enough to overflow
    MAX_PATH (260) from the objdir; abspath collapses the `..` so the resolved
    absolute path is much shorter, and the prefix lifts the limit.
    """
    if os.name == "nt":
        return "\\\\?\\" + os.path.abspath(path).replace("/", "\\")
    return path
